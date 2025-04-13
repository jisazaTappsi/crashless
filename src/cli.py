import io
import pytest

import typer
from enum import Enum
from rich.console import Console
from rich import print as rich_print


import sys
import importlib.util
from cli_helper import fetch_integration_tests, write_to_file
from crashless.handler import print_error

console = Console()
err_console = Console(stderr=True)

DEFAULT_APP_PATH = './main.py'


class Mode(str, Enum):
    fast = "integration-test"
    slow = "unit-test"

typer_app = typer.Typer()


def import_module_from_path(module_path):
    spec = importlib.util.spec_from_file_location("module.name", module_path)  # Create module spec
    module = importlib.util.module_from_spec(spec)  # Create module from spec
    sys.modules["module.name"] = module  # Add module to sys.modules
    spec.loader.exec_module(module)  # Execute the module
    return module


def get_app(main_path):
    main_module = import_module_from_path(main_path or DEFAULT_APP_PATH)
    return main_module.app


def run_pytest_and_capture_output(args=None):
    """Runs pytest.main() with given arguments and captures stdout and stderr."""
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    redirected_output = io.StringIO()
    redirected_error = io.StringIO()
    sys.stdout = redirected_output
    sys.stderr = redirected_error
    try:
        pytest.main(args)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return redirected_output.getvalue(), redirected_error.getvalue()


@typer_app.command()
def main(mode: Mode, method: str, endpoint: str, main_path: str = None):
    """
    Builds unit or integration tests for a given endpoint.
    """
    app = get_app(main_path)
    if mode == 'integration-test':
        rich_print(f"building integration test for {endpoint}")
        test_case_str = fetch_integration_tests(method, endpoint, app)
        test_path = write_to_file(test_case_str, method, endpoint, app)
        rich_print(f'Successfully build integration test, check it out: {test_path}')
        stdout, stderr = run_pytest_and_capture_output([test_path])
        print("Captured Standard Output:")
        print(stdout)
        print("\nCaptured Standard Error:")
        print_error(stderr)

    elif mode == 'unit-test':
        raise NotImplementedError('unit-test mode has not been implemented yet')


if __name__ == "__main__":
    typer_app()
