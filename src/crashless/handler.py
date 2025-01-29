import os
import re
import ast
import inspect
import tokenize
import tempfile
import traceback
import subprocess
from io import BytesIO
from collections import defaultdict
from typing import List, Union, Optional
from pip._internal.operations import freeze

import requests
from pydantic import BaseModel

from crashless.cts import DEBUG, MAX_CHAR_WITH_BOUND, BACKEND_DOMAIN

GIT_HEADER_REGEX = r'@@.*@@.*\n'
MAX_CONTEXT_MARGIN = 100


class CodeFix(BaseModel):
    index: int = None
    file_path: str = None
    fixed_code: str = None
    explanation: str = None
    error: str = None


def get_code_fix(environments, stacktrace_str):
    response = requests.post(
        url=f'{BACKEND_DOMAIN}/crashless/get-crash-fix',
        data=Payload(packages=list(freeze.freeze()),
                     stacktrace_str=stacktrace_str,
                     environments=environments).json(),
        headers={'accept': 'application/json', 'accept-language': 'en'}
    )
    json_response = response.json()
    return CodeFix(**json_response)


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


def get_git_root():
    result = subprocess.run('git rev-parse --show-toplevel', capture_output=True, text=True, shell=True)
    return result.stdout.strip()


def get_git_path(absolute_path):
    return absolute_path.replace(get_git_root(), '')


def get_diffs_and_patch(old_code, new_code, code_environment, temp_patch_file):
    with tempfile.NamedTemporaryFile(mode='w') as temp_old_file, tempfile.NamedTemporaryFile(mode='w') as temp_new_file:
        try:
            temp_old_file.write(old_code)
            temp_new_file.write(new_code)
        except UnicodeEncodeError:
            return None

        temp_old_file.flush()  # makes sure that contents are written to file
        temp_new_file.flush()

        # Run "git diff" comparing temporary files.
        result = subprocess.run(f'git diff --no-index {temp_old_file.name} {temp_new_file.name}',
                                capture_output=True, text=True, shell=True)

        subprocess.run(f'git diff --no-index {temp_old_file.name} {temp_new_file.name} > {temp_patch_file.name}',
                       capture_output=True, text=True, shell=True)
        patch_content = temp_patch_file.read()
        git_path = get_git_path(code_environment.file_path)
        patch_content = patch_content.replace(temp_old_file.name, git_path).replace(temp_new_file.name, git_path)

        # Move the pointer to the beginning
        # patch_file.seek(0)
        temp_patch_file.seek(0)

        # Write the modified content
        # patch_file.write(patch_content)
        temp_patch_file.write(patch_content)

        # Truncate the remaining part of the file
        # patch_file.truncate()
        temp_patch_file.truncate()

        # Removes header with the context to get only the code resulting from the "git diff".
        result_str = result.stdout
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


def ask_to_fix_code(solution, temp_patch_file):
    print_with_color(f'The following code changes will be applied:', BColors.WARNING)
    for diff in solution.diffs:
        print_diff(diff)

    print_with_color(f'Explanation: {add_newline_every_n_chars(solution.explanation)}', BColors.OKBLUE)
    apply_changes = True if input('Apply changes(y/n)?: ') == 'y' else False
    if apply_changes:
        print_with_color('Please wait while changes are deployed...', BColors.WARNING)
        print_with_color("On PyCharm reload file with: Ctrl+Alt+Y, on mac: option+command+Y", BColors.WARNING)
        subprocess.run(f'git apply {temp_patch_file.name}', capture_output=True, text=True, shell=True)
        print_with_color("Changes have been deployed :)", BColors.OKGREEN)
    else:
        print_with_color('Code still has this pesky bug :(', BColors.WARNING)

    return solution


class CodeEnvironment(BaseModel):
    index: int
    file_path: str
    code: str
    start_scope_index: int
    end_scope_index: int
    error_code_line: str
    local_vars: str
    error_line_number: int
    total_file_lines: int
    code_definitions: List[str]


class Payload(BaseModel):
    packages: List[str]
    stacktrace_str: str
    environments: List[CodeEnvironment]

    def to_json(self):
        environment_jsons = [e.to_json() for e in self.environments]
        normal_json = self.json()
        self.environments = environment_jsons
        return self


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
        total_chars = sum([len(str(d)) for d in definitions])
        if total_chars > MAX_CHAR_WITH_BOUND:
            if DEBUG:
                print(f'CHARS_LIMIT exceeded, {total_chars=} on get_code_definitions()')
            break

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


def get_environment(stacktrace, idx):
    file_path = get_file_path(stacktrace)
    error_line_number = stacktrace.tb_lineno
    with open(file_path, 'r') as file_code:
        file_content = file_code.read()
    file_lines = get_code_lines(file_content)
    total_file_lines = len(file_lines)
    error_code_line = file_lines[error_line_number - 1]  # zero based counting
    code_lines, start_scope_index, end_scope_index = get_context_code_lines(error_line_number, file_lines, file_content)
    code = ''.join(code_lines)

    if code[-1] == '\n':  # prevent a last \n from introducing a fake extra line.
        code = code[:-1]

    local_vars = get_local_vars(stacktrace)
    code_definitions = get_code_definitions(local_vars)

    return CodeEnvironment(
        index=idx,
        file_path=file_path,
        code=code,
        start_scope_index=start_scope_index,
        end_scope_index=end_scope_index,
        error_code_line=error_code_line,
        local_vars=str(local_vars),
        error_line_number=error_line_number,
        total_file_lines=total_file_lines,
        code_definitions=code_definitions,
    )


def in_my_code(file_path):
    not_in_packages = "site-packages" not in file_path and "lib/python" not in file_path
    in_project_dir = os.getcwd() in file_path
    return not_in_packages and in_project_dir


def get_stacktrace(exc):
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def get_environments(exc):
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

    return [get_environment(level, idx) for idx, level in enumerate(levels)]


def get_solution(environments, temp_patch_file, exc):
    stacktrace_str = get_stacktrace(exc)
    code_fix = get_code_fix(environments, stacktrace_str)
    explanation = code_fix.explanation

    # there's nothing
    if code_fix.fixed_code is None and explanation is None:
        return Solution(
            not_found=True,
            file_path=code_fix.file_path,
            stacktrace_str=stacktrace_str,
            error=code_fix.error,
        )

    # there's no code
    if code_fix.fixed_code is None:
        return Solution(
            not_found=False,
            file_path=code_fix.file_path,
            explanation=explanation,
            stacktrace_str=stacktrace_str,
            error=code_fix.error,
        )

    code_pieces = code_fix.fixed_code.split('\n')

    with open(code_fix.file_path, "r") as file_code:
        old_code = file_code.read()
        file_lines = old_code.split('\n')

    fixed_environment = environments[code_fix.index]
    lines_above = file_lines[:fixed_environment.start_scope_index]
    lines_below = file_lines[fixed_environment.end_scope_index:]
    new_code = '\n'.join(lines_above + code_pieces + lines_below)

    diffs = get_diffs_and_patch(old_code, new_code, fixed_environment, temp_patch_file)

    return Solution(
        diffs=diffs,
        new_code=new_code,
        file_path=fixed_environment.file_path,
        explanation=explanation,
        stacktrace_str=stacktrace_str,
        error=code_fix.error,
    )


class Solution(BaseModel):
    not_found: bool = False
    diffs: List[str] = []
    new_code: Optional[str]
    file_path: Optional[str]
    explanation: Optional[str]
    stacktrace_str: Optional[str]
    error: Optional[str]


def get_candidate_solution(exc, temp_patch_file):
    print_with_color("Crashless detected an error, let's fix it!", BColors.WARNING)
    print_with_color("Loading possible solution...", BColors.WARNING)
    environments = get_environments(exc)
    return get_solution(environments, temp_patch_file, exc)


def get_content_message(exc):
    return {
        'error': str(exc),
        'action': 'Check terminal to see a possible solution',
    }


def threaded_function(exc):
    with tempfile.NamedTemporaryFile(mode='r+') as temp_patch_file:
        solution = get_candidate_solution(exc, temp_patch_file)

        if solution.error:  # No changes but with explanation.
            print_with_color("There was an error in crashless :(, please report it", BColors.WARNING)
            print_with_color(f'Error: {add_newline_every_n_chars(solution.error)}', BColors.FAIL)
            return

        if solution.not_found:
            print_with_color("No solution found :(, we'll try harder next time", BColors.WARNING)
            return

        if not solution.diffs and solution.explanation:  # No changes but with explanation.
            print_with_color("There's no code to change, but we have a possible explanation.", BColors.WARNING)
            print_with_color(f'Explanation: {add_newline_every_n_chars(solution.explanation)}', BColors.OKBLUE)
            return

        ask_to_fix_code(solution, temp_patch_file)
