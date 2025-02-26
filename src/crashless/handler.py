import os
import re
import ast
import sys
import types
import inspect
import tokenize
import tempfile
import traceback
import subprocess
from io import BytesIO
from types import ModuleType
from typing import List, Dict, Optional
from collections import defaultdict
from pip._internal.operations import freeze

import requests
from halo import Halo
from pydantic import BaseModel

from crashless.cts import DEBUG, MAX_CHAR_WITH_BOUND, BACKEND_DOMAIN

GIT_HEADER_REGEX = r'@@.*@@.*\n'
MAX_CONTEXT_MARGIN = 100
OPTIONAL_COMMENT = r'\s*(?:#.*)?'
FUNCTION_NAME = '\w+(?:\.\w+)*'
FUNCTION_CALL = rf'{FUNCTION_NAME}\s*\('
FUNCTION_CALL_WRAPPER = r'^[^#]*{function_name}\s*\(.*$'
FUNCTION_CALLING_LINE = FUNCTION_CALL_WRAPPER.format(function_name=FUNCTION_NAME)


class Code(BaseModel):
    index: int = None
    file_path: str
    code: str
    start_scope_index: int
    end_scope_index: int


class Environment(Code):
    error_code_line: str
    local_vars: str
    error_line_number: int
    total_file_lines: int
    used_additional_definitions: List[str]


class Definition(Code):
    name: str


class Payload(BaseModel):
    packages: List[str]
    stacktrace_str: str
    environments: List[Environment]
    additional_definitions: Dict[str, Definition]


def get_function_call_matches(line, single_regex, double_regex):

    # This is an approximation, it's too uncommon to have a def where a param cals a function...
    if re.match('(\b|\s)*def\s+', line):
        return []

    matches = re.findall(single_regex, line) + re.findall(double_regex, line)
    if not matches:
        return []

    # Check it's not inside a string, if there's an odd number of string symbols, so the string is 'open'
    first_split = re.split(FUNCTION_CALL, line)[0]
    is_in_string = first_split.count("'") % 2 or first_split.count('"') % 2
    if is_in_string:
        return []

    return matches


class CodeFix(BaseModel):
    index: Optional[int] = None
    file_path: str = None
    fixed_code: str = None
    explanation: str = None
    error: str = None


def get_code_fix(payload: Payload):
    request_params = {
        'url': f'{BACKEND_DOMAIN}/crashless/get-crash-fix',
        'data': payload.json(),
        'headers': {'accept': 'application/json', 'accept-language': 'en'}
    }
    if DEBUG:
        response = requests.post(**request_params)
    else:
        with Halo(text=get_str_with_color(f'Thinking possible solution', BColors.WARNING), spinner='dots'):
            response = requests.post(**request_params)

    if response.status_code != 200:
        return CodeFix(error=f'Failed request with {response.status_code=} and detail={response.json().get("detail")}')

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
    result = subprocess.run(["git", "rev-parse", '--show-toplevel'], capture_output=True, text=True)
    if result.returncode != 0:
        print_error(result)

    return result.stdout.strip()


def get_git_path(absolute_path):
    root_of_git = get_git_root()
    if root_of_git:  # There's a git repo on the path.
        # Removes the absolute path part, and uses relatives paths to that .git file.
        return absolute_path.replace(root_of_git, '')
    else:
        # There's no .git on the path, will use absolute paths.
        return f'/{absolute_path}'  # Needs to add a / to read the absolute path


def get_diffs_and_patch(old_code, new_code, file_path, temp_patch_file):
    with tempfile.NamedTemporaryFile(mode='w') as temp_old_file, tempfile.NamedTemporaryFile(mode='w') as temp_new_file:
        try:
            temp_old_file.write(old_code)
            temp_new_file.write(new_code)
        except UnicodeEncodeError:
            return None

        temp_old_file.flush()  # makes sure that contents are written to file
        temp_new_file.flush()

        # Run "git diff" comparing temporary files.
        result_diff = subprocess.run(["git", "diff", '--no-index', temp_old_file.name, temp_new_file.name],
                                capture_output=True, text=True)
        # Codes for actual errors are >= 2, while 0 and 1 are success with no diff and diff respectively.
        if result_diff.returncode >= 2:
            print_error(result_diff)

        patch_content = result_diff.stdout
        git_path = get_git_path(file_path)
        patch_content = patch_content.replace(temp_old_file.name, git_path).replace(temp_new_file.name, git_path)

        # Move the pointer to the beginning
        temp_patch_file.seek(0)

        # Write the modified content
        temp_patch_file.write(patch_content)

        # Truncate the remaining part of the file
        temp_patch_file.truncate()

        # Removes header with the context to get only the code resulting from the "git diff".
        diff_content = re.split(GIT_HEADER_REGEX, patch_content)

    try:
        return diff_content[1:]  # returns a list of changes in different parts.
    except IndexError:
        return []


def get_str_with_color(line, color):
    return f'{color}{line}{BColors.ENDC}'


def print_with_color(line, color):
    print(get_str_with_color(line, color))


def print_error(result):
    error_message = result.stderr.strip() or "Unknown error occurred"
    print_with_color(error_message, BColors.FAIL)


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
    print_with_color(f'AI got an answer, the following code changes will be applied:', BColors.WARNING)
    print(f'In {solution.file_path}:')
    for diff in solution.diffs:
        print_diff(diff)

    print_with_color(f'Explanation: {add_newline_every_n_chars(solution.explanation)}', BColors.OKBLUE)
    user_input = input('Apply changes(Y/n)?: ')
    apply_changes = user_input in ('Y', '')
    if apply_changes:
        print_with_color('Please wait while changes are deployed...', BColors.WARNING)
        print_with_color("On PyCharm reload file with: Ctrl+Alt+Y, on mac: option+command+Y", BColors.WARNING)

        # Uses unsafe-paths option to be able to modify when provided absolute paths.
        result = subprocess.run(["git", "apply", temp_patch_file.name, '--unsafe-paths'],
                                capture_output=True, text=True)

        if result.returncode == 0:
            print_with_color("Changes have been deployed :)", BColors.OKGREEN)
        else:
            print_error(result)
    else:
        print_with_color('Code still has this pesky bug :(', BColors.WARNING)

    return solution


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


def get_end_scope_index(scope_error, analyzer, error_line_number):
    """Outputs, zero based indexing"""
    end_index = max([line for line, scope in analyzer.line_scopes.items() if scope == scope_error])
    end_index = min(error_line_number + MAX_CONTEXT_MARGIN, end_index)  # hard limit on data amount
    end_index -= 1  # change from 1 based indexing to 0 based indexing

    return max(end_index, 0)  # cannot be negative


def missing_definition_with_regex(line):
    """Detects whether the line contains a class or method definition."""
    def_regex = rf'^\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(.*\)\s*:{OPTIONAL_COMMENT}'
    class_regex = rf'^\s*class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*(\(.*\))?\s*:{OPTIONAL_COMMENT}'
    decorator_regex = rf'^\s*@\w+(\([^)]*\))?{OPTIONAL_COMMENT}'
    def_match = re.match(def_regex, line)
    class_match = re.match(class_regex, line)
    decorator_match = re.match(decorator_regex, line)
    return def_match is None and class_match is None and decorator_match is None


def missing_definition(first_index, lines):
    if first_index == 0:
        return False
    return missing_definition_with_regex(line=lines[first_index])


def get_start_scope_index(scope_error, analyzer, error_line_number, file_length, file_lines):
    """Outputs, zero based indexing"""
    first_index = min([line for line, scope in analyzer.line_scopes.items() if scope == scope_error])
    first_index -= 1  # change from 1 based indexing to 0 based indexing

    first_index = max(error_line_number - MAX_CONTEXT_MARGIN, first_index)  # hard limit on data amount
    first_index = min(first_index, file_length)  # cannot exceed the file's length

    # Sometimes definition of class or function is off by one line.
    if first_index > 0 and missing_definition(first_index, file_lines):
        first_index -= 1

    return first_index


def get_context_code_lines(error_line_number, file_lines, code):
    """Uses the scope to know what should be included"""

    tree = ast.parse(code)
    analyzer = ScopeAnalyzer()
    analyzer.visit(tree)

    scope_error = analyzer.line_scopes[error_line_number]
    start_index = get_start_scope_index(scope_error=scope_error,
                                        analyzer=analyzer,
                                        error_line_number=error_line_number,
                                        file_length=len(file_lines),
                                        file_lines=file_lines)
    end_index = get_end_scope_index(scope_error=scope_error,
                                    analyzer=analyzer,
                                    error_line_number=error_line_number)

    including_last_line_index = end_index + 1
    return file_lines[start_index: including_last_line_index], start_index, end_index


def is_user_module(module):
    """User defined no builtin or third party module"""
    if module is None:
        return False
    if not hasattr(module, '__file__') or module.__file__ is None:
        return False

    return path_is_in_user_code(module.__file__) and module.__name__ != '__builtins__'


def get_imported_modules(module: ModuleType):
    return [obj for name, obj in module.__dict__.items() if isinstance(obj, ModuleType) and is_user_module(obj)]


def get_functions_from_module(module):
    """Filter functions defined in this module"""
    function_tuples = inspect.getmembers(module, lambda obj: isinstance(obj, types.FunctionType))
    return {name: func for name, func in function_tuples if path_is_in_user_code(inspect.getfile(func))}


def get_functions_from_module_recursively(module, scrapped_module_names=[], base_module=False):
    """This recursion is efficient by storing what's already scrapped and not repeating."""
    # TODO: what happens with direct imports, ie from module_x import my_function

    # my local functions
    module_dict = get_functions_from_module(module)
    if not base_module:  # Prepends name, to be able to use later on regex, and don't mix workspaces.
        module_dict = {**module_dict, **{f'{module.__name__}.{name}': func for name, func in module_dict.items()}}

    # Stores what's scrapped already so it won't repeat
    scrapped_module_names.append(module.__name__)

    imported_modules = get_imported_modules(module)
    imported_modules = [imported_module for imported_module in imported_modules
                        if imported_module.__name__ not in scrapped_module_names]
    for imported_module in imported_modules:
        # Prepends name, to abel to use later on regex, and don't mix workspaces.
        imported_module_dict, scrapped_module_names = get_functions_from_module_recursively(imported_module,
                                                                                            scrapped_module_names)
        module_dict = {**module_dict, **imported_module_dict}

    return module_dict, scrapped_module_names


def get_user_defined_functions_from_frame(frame):

    # Get the module associated with the input frame
    module = inspect.getmodule(frame)
    if not module:
        return dict()

    module_dict, scrapped_module_names = get_functions_from_module_recursively(module, base_module=True)
    return module_dict


def get_function_specific_regex(functions):
    """Matching several options of users defined functions. Needs to escape the names because some have dots."""
    # having parenthesis produces a capturing group.
    escaped_function_names = f"({'|'.join([re.escape(name) for name in functions])})"
    return FUNCTION_CALL_WRAPPER.format(function_name=escaped_function_names)


def get_function_regexes(function_dict):
    single_functions = [name for name, _ in function_dict.items() if '.' not in name]
    double_functions = [name for name, _ in function_dict.items() if '.' in name]
    return get_function_specific_regex(single_functions), get_function_specific_regex(double_functions)


def get_definition(name, obj):
    source_lines, start_line = inspect.getsourcelines(obj)
    start_line -= 1  # zero based indexing
    end_line = start_line + len(source_lines) - 1
    source_code = ''.join(source_lines)  # \n already in the lines

    if source_code[-1] == '\n':  # prevent a last \n from introducing a fake extra line.
        source_code = source_code[:-1]

    return Definition(
        name=name,
        code=source_code,
        file_path=inspect.getfile(obj),
        start_scope_index=start_line,
        end_scope_index=end_line,
    )


def get_method_definitions_recursively(function_dict, code_lines, single_regex, double_regex,
                                       method_name_called_from=None):
    called_methods = dict()
    for line in code_lines:
        matched_functions = get_function_call_matches(line, single_regex, double_regex)
        for matched_function in matched_functions:
            try:  # Tries module import, ie module.function
                called_methods[matched_function] = function_dict[matched_function]
            except KeyError:
                try:  # Tries function import
                    called_methods[matched_function] = function_dict[matched_function.split('.')[-1]]
                except KeyError:
                    pass

    # removes the method it's been called from, to prevent infinite recursion when there's a
    # recursion on the user code.
    called_methods.pop(method_name_called_from, None)

    source_code_dict = dict()
    for method_name, func in called_methods.items():
        func_definition = get_definition(method_name, func)
        source_code_dict[method_name] = func_definition
        source_code_dict = {
            **source_code_dict,
            **get_method_definitions_recursively(function_dict, func_definition.code.split('\n'),
                                                 single_regex=single_regex, double_regex=double_regex,
                                                 method_name_called_from=method_name)
        }

    return source_code_dict


def get_method_definitions(stacktrace, code_lines):
    frame = stacktrace.tb_frame
    function_dict = get_user_defined_functions_from_frame(frame)
    single_regex, double_regex = get_function_regexes(function_dict)
    return get_method_definitions_recursively(function_dict, code_lines, single_regex, double_regex)


def get_length_of_dict(my_dict):
    return len(str(my_dict))


def cut_definitions(definitions):
    shortened_definitions = dict()
    for name, definition in definitions.items():
        total_chars = get_length_of_dict(shortened_definitions)
        if total_chars > MAX_CHAR_WITH_BOUND:
            if DEBUG:
                print(f'CHARS_LIMIT exceeded, {total_chars=} on definitions')
            break
        shortened_definitions[name] = definition

    return shortened_definitions


def get_instances_and_classes_definitions(local_vars):
    # TODO: find definitions recursively
    definitions = dict()
    for var in local_vars.values():
        try:
            the_class = var if inspect.isclass(var) else var.__class__
            if path_is_in_user_code(inspect.getfile(the_class)):
                class_name = the_class.__name__
                definitions[class_name] = get_definition(class_name, the_class)
        except (TypeError, OSError):
            pass

    return definitions


def get_file_path(stacktrace):
    frame = stacktrace.tb_frame
    return frame.f_code.co_filename


def get_local_vars(stacktrace):
    frame = stacktrace.tb_frame
    return frame.f_locals


def get_definitions(local_vars, stacktrace, code_lines):
    objects_definitions = get_instances_and_classes_definitions(local_vars)
    methods_definitions = get_method_definitions(stacktrace, code_lines)
    additional_definitions = {**objects_definitions, **methods_definitions}
    return cut_definitions(additional_definitions)


def get_local_vars_str(local_vars):
    """Calling local vars can randomly raise an error"""
    var_dict = {}
    for name in local_vars.keys():  # cannot call item here cause will explode if a local variable has an exception.
        try:
            # Can only call the value inside the try except.
            var_dict[name] = str(local_vars[name])
        except Exception:
            pass
    return str(var_dict)


def get_environment_and_defs(stacktrace, idx):
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
    additional_definitions = get_definitions(local_vars, stacktrace, code_lines)

    environment = Environment(
        index=idx,
        file_path=file_path,
        code=code,
        start_scope_index=start_scope_index,
        end_scope_index=end_scope_index,
        error_code_line=error_code_line,
        local_vars=get_local_vars_str(local_vars),
        error_line_number=error_line_number,
        total_file_lines=total_file_lines,
        used_additional_definitions=list(additional_definitions.keys()),
    )
    return environment, additional_definitions


def path_is_in_user_code(file_path):
    not_in_packages = "site-packages" not in file_path and "lib/python" not in file_path
    in_project_dir = os.getcwd() in file_path
    return not_in_packages and in_project_dir


def get_stacktrace(exc):
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def get_environments_and_defs(exc):
    # Find lowest non-lib level
    levels = []
    stacktrace_level = exc.__traceback__
    while True:
        if stacktrace_level is None:
            break

        file_path = get_file_path(stacktrace_level)
        if path_is_in_user_code(file_path):
            levels.append(stacktrace_level)

        stacktrace_level = stacktrace_level.tb_next  # Move to the next level in the stack trace

    environments = []
    all_definitions = dict()
    for idx, level in enumerate(levels):
        environment, definitions = get_environment_and_defs(level, idx)
        environments.append(environment)
        all_definitions = {**all_definitions, **definitions}
    return environments, all_definitions


def environment_or_definition(index, payload):
    possibilities = payload.environments + [d for d in list(payload.additional_definitions.values())]
    try:
        return [e_d for e_d in possibilities if e_d.index == index][0]
    except IndexError:
        return None


def get_new_code_and_diffs(code_fix, payload, temp_patch_file):
    if code_fix.index is None:
        return None, []

    fixed_env_or_def = environment_or_definition(code_fix.index, payload)
    with open(code_fix.file_path, "r") as file_code:
        old_code = file_code.read()
        file_lines = old_code.split('\n')

    lines_above = file_lines[:fixed_env_or_def.start_scope_index]
    lines_below = file_lines[fixed_env_or_def.end_scope_index + 1:]  # cannot include end line.
    code_pieces = code_fix.fixed_code.split('\n')
    new_code = '\n'.join(lines_above + code_pieces + lines_below)
    diffs = get_diffs_and_patch(old_code, new_code, code_fix.file_path, temp_patch_file)
    return new_code, diffs


def get_solution(payload: Payload, temp_patch_file):
    code_fix = get_code_fix(payload)
    explanation = code_fix.explanation

    # there's nothing
    if code_fix.fixed_code is None and explanation is None:
        return Solution(
            not_found=True,
            file_path=code_fix.file_path,
            stacktrace_str=payload.stacktrace_str,
            error=code_fix.error,
        )

    # there's no code
    if code_fix.fixed_code is None or code_fix.index is None:
        return Solution(
            not_found=False,
            file_path=code_fix.file_path,
            explanation=explanation,
            stacktrace_str=payload.stacktrace_str,
            error=code_fix.error,
        )

    new_code, diffs = get_new_code_and_diffs(code_fix, payload, temp_patch_file)
    return Solution(
        diffs=diffs,
        new_code=new_code,
        file_path=code_fix.file_path,
        explanation=explanation,
        stacktrace_str=payload.stacktrace_str,
        error=code_fix.error,
    )


class Solution(BaseModel):
    not_found: bool = False
    diffs: List[str] = []
    new_code: str = None
    file_path: str = None
    explanation: str = None
    stacktrace_str: str = None
    error: str = None


def get_candidate_solution(exc, temp_patch_file):
    print_with_color("Crashless detected an error, let's fix it!", BColors.WARNING)
    environments, additional_definitions = get_environments_and_defs(exc)

    if environments:  # needs at least 1 environment
        max_index = max([e.index for e in environments])
        for idx, (name, defi) in enumerate(additional_definitions.items()):
            defi.index = max_index + idx + 1
            additional_definitions[name] = defi

    stacktrace_str = get_stacktrace(exc)
    payload = Payload(
        packages=list(freeze.freeze()),
        stacktrace_str=stacktrace_str,
        environments=environments,
        additional_definitions=additional_definitions
    )
    return get_solution(payload, temp_patch_file)


def get_content_message(exc):
    return {
        'error': str(exc),
        'action': 'Check terminal to see a possible solution',
    }


def threaded_function(exc):
    with tempfile.NamedTemporaryFile(mode='r+') as temp_patch_file:
        temp_patch_file.flush()  # makes sure that contents are written to file
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
