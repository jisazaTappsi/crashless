import inspect


def get_first_matching_route(endpoint_str, method, app):
    routes = [route for route in app.routes if route.path == endpoint_str and method in route.methods]
    if routes:
        return routes[0]
    else:
        return None


def get_endpoint_function(endpoint_str, method, app):
    route = get_first_matching_route(endpoint_str, method, app)
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


def get_test_example(title, example_path, endpoint_str, method, additional_comments=None):
    with open(example_path, 'r') as f:
        simple_function = get_endpoint_function(endpoint_str, method)
        simple_source = get_handler_source(simple_function)
        endpoint_test_cases = f.read()
        return TestCaseExample(
            title=title,
            source_code=simple_source,
            endpoint=endpoint_str,
            http_methods=[method],
            test_cases=endpoint_test_cases,
            additional_comments=additional_comments,
        )


def get_endpoint_str(endpoint):
    endpoint_str = endpoint.replace('/{', '_').replace('}', '')
    endpoint_str = endpoint_str.replace(f'{API_V2}/', '')
    return endpoint_str.replace('-', '_')


def get_endpoint_basename(endpoint):
    endpoint_str = get_endpoint_str(endpoint)
    endpoint_splits = endpoint_str.split('/')
    endpoint_name = endpoint_splits[-1]
    if len(get_endpoint_methods(endpoint)) > 1:  # Disambiguation case
        return f"test_{endpoint_name}_{method}"
    else:
        return f"test_{endpoint_name}"


def get_endpoint_filepath_base_name(endpoint):
    endpoint_str = get_endpoint_str(endpoint)
    endpoint_splits = endpoint_str.split('/')
    paths = endpoint_splits[:-1] + [get_endpoint_basename(endpoint)]
    return '/'.join(paths)


def get_endpoint_filepath(endpoint):
    endpoint_str = get_endpoint_str(endpoint)
    endpoint_splits = endpoint_str.split('/')
    filename = f"{get_endpoint_basename(endpoint)}.py"
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
