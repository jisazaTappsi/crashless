from sample_code import my_scope
from crashless.handler import get_environments_and_defs, get_function_call_matches, get_function_regexes

functions_dict = {'my_function': 'anything'}
single_regex, double_regex = get_function_regexes(functions_dict)

assert get_function_call_matches('     my_function()', single_regex=single_regex, double_regex=double_regex)
assert get_function_call_matches('my_function()', single_regex=single_regex, double_regex=double_regex)
assert not get_function_call_matches('     # my_function()', single_regex=single_regex, double_regex=double_regex)
assert not get_function_call_matches('     my_function', single_regex=single_regex, double_regex=double_regex)  # Missing parentheses
assert not get_function_call_matches('def my_function():', single_regex=single_regex, double_regex=double_regex)  # Function definition
assert not get_function_call_matches('""" my_function() """', single_regex=single_regex, double_regex=double_regex)  # Inside multiline comment
assert get_function_call_matches('\t\tmy_function()', single_regex=single_regex, double_regex=double_regex)  # Matches with tabs
assert get_function_call_matches('if my_function() else x', single_regex=single_regex, double_regex=double_regex)
assert get_function_call_matches('my_function(a, b, c="asd") # sometinh', single_regex=single_regex, double_regex=double_regex)
assert not get_function_call_matches(" somethin #   common.my_function()", single_regex=single_regex, double_regex=double_regex)
assert get_function_call_matches("    candidate_queryset = common.my_function(", single_regex=single_regex, double_regex=double_regex)

# TODO: missing f string case.
#assert line_has_function_call("print(f'some text={function_call()}", single_regex=single_regex, double_regex=double_regex)

# Test that method definitions are retrieved
try:
    my_scope()
except Exception as exc:
    environments, _ = get_environments_and_defs(exc)
    sample_environment = environments[1]

    assert 'my_local_function1' in sample_environment.used_additional_definitions
    assert 'my_local_function2' in sample_environment.used_additional_definitions
    assert 'my_local_function3' in sample_environment.used_additional_definitions
    assert 'function_called_directly' in sample_environment.used_additional_definitions
    assert 'another_module.function_called_indirectly' in sample_environment.used_additional_definitions
    assert 'un_used_method' not in sample_environment.used_additional_definitions
    assert 'intricate_call' in sample_environment.used_additional_definitions
    assert 'starts_with_same_string' in sample_environment.used_additional_definitions
    assert 'starts_with_same_string_but_is_a_lot_longer' in sample_environment.used_additional_definitions
    #assert 'call_in_f_string' in sample_environment.used_additional_definitions  # TODO: missing f-string case
