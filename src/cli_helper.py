import inspect
from typing import Optional, List

import requests
from pathlib import Path
from pydantic import BaseModel

from crashless.cts import BACKEND_DOMAIN


class TestCaseExample(BaseModel):
    title: str
    prompt: Optional[str] = None
    source_code: str
    endpoint: str
    http_methods: List[str]
    test_cases: str


class TestCasePayload(BaseModel):
    source_code: str
    endpoint: str
    http_methods: List[str]
    examples: List[TestCaseExample] = []
    prompt: Optional[str] = None
    project_recommendations: Optional[str] = None
    project_settings: Optional[str] = None
    testing_code: Optional[str] = None
    previous_implementation: Optional[str] = None
    last_stdout: Optional[str] = None
    last_stderr: Optional[str] = None


def get_first_matching_route(method, endpoint_str, app):
    routes = [route for route in app.routes if route.path == endpoint_str and method in route.methods]
    if routes:
        return routes[0]
    else:
        return None


def get_endpoint_function(method, endpoint_str, app):
    route = get_first_matching_route(method, endpoint_str, app)
    return route.endpoint if route else None


def get_endpoint_methods(endpoint_str, app):
    # Flattens the methods into a single set.
    methods_set = {method for route in app.routes if route.path == endpoint_str for method in route.methods}
    try:
        methods_set.remove('HEAD')
    except KeyError:
        pass
    return methods_set


def get_handler_source(handler) -> str:
    """Get the source code of an endpoint handler."""
    source_lines, start_line = inspect.getsourcelines(handler)
    return ''.join(source_lines)


def get_test_example(title, example_path, method, endpoint_str, app, prompt=None):
    with open(example_path, 'r') as f:
        simple_function = get_endpoint_function(method, endpoint_str, app)
        simple_source = get_handler_source(simple_function)
        endpoint_test_cases = f.read()
        return TestCaseExample(
            title=title,
            source_code=simple_source,
            endpoint=endpoint_str,
            http_methods=[method],
            test_cases=endpoint_test_cases,
            prompt=prompt,
        )


def get_endpoint_str(endpoint):
    endpoint_str = endpoint.replace('/{', '_').replace('}', '')
    endpoint_str = endpoint_str.replace(f'{API_V2}/', '')  # TODO: how to deal with this?
    return endpoint_str.replace('-', '_')


def get_endpoint_basename(method, endpoint, app):
    endpoint_str = get_endpoint_str(endpoint)
    endpoint_splits = endpoint_str.split('/')
    endpoint_name = endpoint_splits[-1]
    if len(get_endpoint_methods(endpoint, app)) > 1:  # Disambiguation case
        return f"test_{endpoint_name}_{method}"
    else:
        return f"test_{endpoint_name}"


def get_endpoint_filepath_base_name(method, endpoint, app):
    endpoint_str = get_endpoint_str(endpoint)
    endpoint_splits = endpoint_str.split('/')
    paths = endpoint_splits[:-1] + [get_endpoint_basename(method, endpoint, app)]
    return '/'.join(paths)


def get_endpoint_filepath(method, endpoint, app):
    endpoint_str = get_endpoint_str(endpoint)
    endpoint_splits = endpoint_str.split('/')
    filename = f"{get_endpoint_basename(method, endpoint, app)}.py"
    paths = endpoint_splits[:-1] + [filename]
    return '/'.join(paths)


def get_file_content(filepath):
    try:
        with open(filepath, 'r') as f:
            content = f.read()
            print(f'read {filepath}')
    except FileNotFoundError:
        content = None
    return content


# TODO: dont hard code here.
BASE_DIR = '.'
API_V2 = '/api-v2'
EXAMPLE_NO_AUTH_TEST = f'{BASE_DIR}/test_get_countries.py'
EXAMPLE_NO_AUTH_ENDPOINT = f'{API_V2}/get-countries'
EXAMPLE_NO_AUTH_METHOD = 'GET'

EXAMPLE_AUTH_TEST = f'{BASE_DIR}/business/test_mark_carousel_completed_job_id.py'
EXAMPLE_AUTH_ENDPOINT = f'{API_V2}/business/mark-carousel-completed/{{job_id}}'
EXAMPLE_AUTH_METHOD = 'PATCH'


def get_examples(app):
    examples = []
    examples.append(get_test_example(
        title='Example of a simple endpoint without any authentication',
        example_path=EXAMPLE_NO_AUTH_TEST,
        method=EXAMPLE_NO_AUTH_METHOD,
        endpoint_str=EXAMPLE_NO_AUTH_ENDPOINT,
        app=app,
        )
    )
    examples.append(get_test_example(
        title='Example of an endpoint WITH authentication',
        example_path=EXAMPLE_AUTH_TEST,
        method=EXAMPLE_AUTH_METHOD,
        endpoint_str=EXAMPLE_AUTH_ENDPOINT,
        app=app,
        prompt="Notice that when there's a login the function has a token parameter, this "
               "token is sent on the header of the HTTP request by calling the method testing_common.get_header(client), "
               "as shown in the example. Call the method instead of adding summy tokens.",
        )
    )
    return examples


def fetch_integration_tests(method, endpoint, app, last_stdout=None, last_stderr=None):

    endpoint_function = get_endpoint_function(method, endpoint, app)
    if not endpoint_function:
        raise ModuleNotFoundError(f'No endpoint found in: {method} {endpoint}')

    base_name = f'{BASE_DIR}/{get_endpoint_filepath_base_name(method, endpoint, app)}'
    prompt = get_file_content(f'{base_name}.prompt')
    project_settings = get_file_content(f'{BASE_DIR}/settings.ini')
    testing_code = get_file_content(f'{BASE_DIR}/testing_common.py')
    project_recommendations = get_file_content(f'{BASE_DIR}/project_recommendations.txt')
    previous_implementation = get_file_content(f'{base_name}.py')

    response = requests.post(
        url=f'{BACKEND_DOMAIN}/crashless/build-test',
        json=TestCasePayload(
            source_code=get_handler_source(endpoint_function),
            endpoint=endpoint,
            http_methods=[method],
            examples=get_examples(app),
            prompt=prompt,
            project_recommendations=project_recommendations,
            project_settings=project_settings,
            testing_code=testing_code,
            previous_implementation=previous_implementation,
            last_stdout=last_stdout,
            last_stderr=last_stderr,
        ).dict()
    )
    if response.status_code != 200:
        raise Exception(f'build-test endpoint responded: {response.status_code} and {response.text}')

    return response.json().get('test_cases')


def write_to_file(test_case_str, method, endpoint, app):
    endpoint_filepath = get_endpoint_filepath(method, endpoint, app)
    test_path = f'{BASE_DIR}/{endpoint_filepath}'
    file_path = Path(test_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)  # Creates all missing directories

    if test_case_str is None:
        raise Exception("Response returned None :(, something's wrong upstream")

    with open(file_path, 'w') as file:
        file.write(test_case_str)

    return test_path
