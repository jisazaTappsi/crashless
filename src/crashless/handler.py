import inspect
import os
import re
import ast
import shutil
import time
import tokenize
import tempfile
import traceback
import subprocess
from io import BytesIO
from typing import List, Union, Optional
from collections import defaultdict

import requests
from pip._internal.operations import freeze

from pydantic import BaseModel
from starlette.requests import Request
from fastapi.responses import JSONResponse

GIT_HEADER_REGEX = r'@@.*@@.*\n'
MAX_CONTEXT_MARGIN = 100


class CodeFix(BaseModel):
    fixed_code: str
    explanation: str


def process_code_fix_suggestion(environment):

    url = 'https://api.peaku.io/crashless/process-code-fix-suggestion'
    #url = 'http://localhost:8000/crashless/process-code-fix-suggestion'
    response = requests.post(url, data=environment.to_json(),
                             headers={'accept': 'application/json', 'accept-language': 'en'})
    json_response = response.json()

    return CodeFix(fixed_code=json_response.get('fixed_code'),
                   explanation=json_response.get('explanation'))


class BColors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def get_diffs(code1, code2):
    with tempfile.NamedTemporaryFile(mode='w') as diff_file1, tempfile.NamedTemporaryFile(mode='w') as diff_file2:
        try:
            diff_file1.write(code1)
            diff_file2.write(code2)
        except UnicodeEncodeError:
            return None

        diff_file1.flush()  # makes sure that contents are written to file
        diff_file2.flush()

        # Run "git diff" comparing temporary files.
        subprocess_result = subprocess.run(f'git diff --no-index {diff_file1.name} {diff_file2.name}',
                                           capture_output=True, text=True, shell=True)

        # Removes header with the context to get only the code resulting from the "git diff".
        result_str = subprocess_result.stdout
        diff_content = re.split(GIT_HEADER_REGEX, result_str)

    try:
        return diff_content[1:]  # returns a list of changes in different parts.
    except IndexError:
        return None


def print_with_color(line, color):
    print(f'{color}{line}{BColors.ENDC}')


def print_diff(content):
    if content is None:
        return

    for line in content.split('\n'):
        if line.startswith('-'):
            print_with_color(line, BColors.FAIL)
        elif line.startswith('+'):
            print_with_color(line, BColors.OKGREEN)
        else:
            print(line)


def add_newline_every_n_chars(input_string, n_words=20):
    words = input_string.split(r' ')
    return '\n'.join(' '.join(words[i:i + n_words]) for i in range(0, len(words), n_words))


def ask_to_fix_code(solution):
    print_with_color(f'The following code changes will be applied:', BColors.WARNING)
    for diff in solution.diffs:
        print_diff(diff)

    print_with_color(f'Explanation: {add_newline_every_n_chars(solution.explanation)}', BColors.OKBLUE)
    apply_changes = True if input('Apply changes(y/n)?: ') == 'y' else False
    if apply_changes:
        print_with_color('Please wait while changes are deployed...', BColors.WARNING)
        with open(solution.file_path, "w") as file:
            file.write(solution.new_code)
            file.flush()  # Flush internal buffer
            os.fsync(file.fileno())  # Force write to disk
        #os.utime(solution.file_path, None)

        # Rename the file to trigger watcher
        temp_path = solution.file_path + 'temp'
        shutil.move(solution.file_path, temp_path)
        shutil.move(temp_path, solution.file_path)
        time.sleep(1)
        solution.action = 'Changes have been deployed :)'
    else:
        solution.action = 'Code still has this pesky bug :('

    print_with_color(solution.action, BColors.WARNING)
    return solution


class CodeEnvironment(BaseModel):
    file_path: str
    code: str
    start_scope_index: int
    end_scope_index: int
    error_code_line: str
    local_vars: Union[dict, str]
    error_line_number: int
    total_file_lines: int
    packages: List[str]
    stacktrace_str: str
    code_definitions: List[str]

    def to_json(self):
        self.local_vars = str(self.local_vars)
        return self.json()


def get_code_lines(code):
    lines_dict = dict()
    tokens = list(tokenize.tokenize(BytesIO(code.encode('utf-8')).readline))
    for token in tokens:
        start_position = token.start
        end_position = token.end
        start_line = start_position[0]
        end_line = end_position[0]

        if lines_dict.get(start_line) is None and start_line > 0:
            lines_dict[start_line] = token.line

        if start_line < end_line:  # multiline token, will add missing lines
            for idx, line in enumerate(token.line.split('\n')):
                lines_dict[start_line + idx] = f'{line}\n'

    return list(lines_dict.values())


class ScopeAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.scopes = []
        self.line_scopes = defaultdict(list)  # dict()

    def visit_FunctionDef(self, node):
        self.scopes.append(f"Function: {node.name}_{node.__hash__()}")
        self.generic_visit(node)
        self.scopes.pop()

    def visit_ClassDef(self, node):
        self.scopes.append(f"Class: {node.name}_{node.__hash__()}")
        self.generic_visit(node)
        self.scopes.pop()

    def visit(self, node):
        if hasattr(node, 'lineno') and not self.line_scopes[node.lineno]:
            self.line_scopes[node.lineno].extend(self.scopes)
        super().visit(node)


def get_last_scope_index(scope_error, analyzer, error_line_number):
    last_index = max([line for line, scope in analyzer.line_scopes.items() if scope == scope_error])
    last_index = min(error_line_number + MAX_CONTEXT_MARGIN, last_index)  # hard limit on data amount
    return max(last_index, 0)  # cannot be negative


def get_start_scope_index(scope_error, analyzer, error_line_number, file_length):
    first_index = min([line for line, scope in analyzer.line_scopes.items() if scope == scope_error])
    first_index -= 1  # to include the method or class definition.
    first_index = max(error_line_number - MAX_CONTEXT_MARGIN, first_index)  # hard limit on data amount
    return min(first_index, file_length)  # cannot exceed the file's length


def get_context_code_lines(error_line_number, file_lines, code):
    """Uses the scope to know what should be included"""

    tree = ast.parse(code)
    analyzer = ScopeAnalyzer()
    analyzer.visit(tree)

    scope_error = analyzer.line_scopes[error_line_number]
    start_index = get_start_scope_index(scope_error=scope_error,
                                        analyzer=analyzer,
                                        error_line_number=error_line_number,
                                        file_length=len(file_lines))
    end_index = get_last_scope_index(scope_error=scope_error,
                                     analyzer=analyzer,
                                     error_line_number=error_line_number)

    return file_lines[start_index: end_index], start_index, end_index


def get_code_definitions(local_vars):
    definitions = set()
    for var in local_vars.values():
        try:
            definitions.add(inspect.getsource(var.__class__))
        except (TypeError, OSError):
            pass
    return list(definitions)


def get_file_path(stacktrace):
    frame = stacktrace.tb_frame
    return frame.f_code.co_filename


def get_local_vars(stacktrace):
    frame = stacktrace.tb_frame
    return frame.f_locals


def get_environment(stacktrace, exc):
    file_path = get_file_path(stacktrace)
    error_line_number = stacktrace.tb_lineno
    with open(file_path, 'r') as file_code:
        file_content = file_code.read()
    file_lines = get_code_lines(file_content)
    total_file_lines = len(file_lines)
    error_code_line = file_lines[error_line_number - 1]  # zero based counting
    code_lines, start_scope_index, end_scope_index = get_context_code_lines(error_line_number, file_lines, file_content)
    code = ''.join(code_lines)

    local_vars = get_local_vars(stacktrace)
    code_definitions = get_code_definitions(local_vars)

    return CodeEnvironment(
        file_path=file_path,
        code=code,
        start_scope_index=start_scope_index,
        end_scope_index=end_scope_index,
        error_code_line=error_code_line,
        local_vars=local_vars,
        error_line_number=error_line_number,
        total_file_lines=total_file_lines,
        packages=list(freeze.freeze()),
        stacktrace_str=get_stacktrace(exc),
        code_definitions=code_definitions,
    )


def in_my_code(file_path):
    return "site-packages" not in file_path and "lib/python" not in file_path


def get_stacktrace(exc):
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def get_last_environment(exc):
    # Find lowest non-lib level
    levels = []
    stacktrace_level = exc.__traceback__
    while True:
        if stacktrace_level is None:
            break

        file_path = get_file_path(stacktrace_level)
        if in_my_code(file_path):
            levels.append(stacktrace_level)

        stacktrace_level = stacktrace_level.tb_next  # Move to the next level in the stack trace

    # no pieces of code left to fix.
    if not levels:
        raise exc

    return get_environment(levels[-1], exc)


def get_solution(last_environment):
    code_fix = process_code_fix_suggestion(last_environment)
    code_pieces = code_fix.fixed_code.split('\n')
    explanation = code_fix.explanation

    with open(last_environment.file_path, "r") as file_code:
        old_code = file_code.read()
        file_lines = old_code.split('\n')

    lines_above = file_lines[:last_environment.start_scope_index]
    lines_below = file_lines[last_environment.end_scope_index:]
    new_code = '\n'.join(lines_above + code_pieces + lines_below)

    diffs = get_diffs(old_code, new_code)

    return Solution(
        diffs=diffs,
        new_code=new_code,
        file_path=last_environment.file_path,
        explanation=explanation,
        stacktrace_str=last_environment.stacktrace_str
    )


class Solution(BaseModel):
    diffs: List[str]
    new_code: str
    file_path: str
    explanation: str
    stacktrace_str: str
    action: str = 'No solution found :(, probably the stacktrace has no pieces of your code to change.'


def get_candidate_solution(exc):
    print_with_color("Error detected, let's fix it!", BColors.WARNING)
    print_with_color("Breaking our heads trying to find the best solution...", BColors.WARNING)
    last_environment = get_last_environment(exc)
    return get_solution(last_environment)


def get_content_message(exc):
    return {
        'error': str(exc),
        'action': 'Check terminal to see a possible solution',
    }


def threaded_function(exc):
    solution = get_candidate_solution(exc)

    if solution.diffs is None:  # Can't change anything.
        print_with_color(solution.explanation, BColors.WARNING)
        return

    ask_to_fix_code(solution)
