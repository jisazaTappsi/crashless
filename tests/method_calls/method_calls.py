from sample_code import my_scope
from crashless.handler import get_environments, get_function_call_match

assert get_function_call_match('     my_function()')
assert get_function_call_match('another_function_call()')
assert not get_function_call_match('     # my_function()')
assert not get_function_call_match('     my_function')  # Missing parentheses
assert not get_function_call_match('def my_function():')  # Function definition
assert not get_function_call_match('""" my_function() """')  # Inside multiline comment
assert get_function_call_match('\t\tsome_function_call()')  # Matches with tabs
assert get_function_call_match('if some_function_call() else x')
#assert line_has_function_call("print(f'some text={function_call()}")  # TODO: missing f string case.


# Test that method definitions are retrieved
try:
    my_scope()
except Exception as exc:
    environments = get_environments(exc)
    sample_environment = environments[1]

    assert 'my_local_function1' in sample_environment.code_definitions
    assert 'my_local_function2' in sample_environment.code_definitions
    assert 'my_local_function3' in sample_environment.code_definitions
    assert 'function_called_directly' in sample_environment.code_definitions
    assert 'another_module.function_called_indirectly' in sample_environment.code_definitions
    assert 'un_used_method' not in sample_environment.code_definitions
    assert 'intricate_call' in sample_environment.code_definitions
    #assert 'call_in_f_string' in sample_environment.code_definitions  # TODO: missing f-string case
