from scope_sample_code import first_level_method
from tests.scope_sample_code import FirstLevelClass
from crashless.handler import get_environments_and_defs, missing_definition_with_regex

assert missing_definition_with_regex('def')
assert missing_definition_with_regex('class')
assert not missing_definition_with_regex('    class     MyNormalClass:    ')
assert not missing_definition_with_regex('     def     my_method(self):    ')
assert missing_definition_with_regex('     def     my_method:    ')
assert not missing_definition_with_regex('@classmethod  ')
assert not missing_definition_with_regex('@app.get("/crash")  # This endpoint has a fatal bug :(\n')


# Test that the method definition is always included, when we are on a first level of depth.
try:
    first_level_method()
except Exception as exc:
    environments, _ = get_environments_and_defs(exc)
    sample_environment = environments[1]
    lines = sample_environment.code.split('\n')
    first_line = lines[0]
    print(f'{first_line=}')
    assert first_line == 'def first_level_method():'

# Test that the method definition is always included, when we are on top of a class.
try:
    instance = FirstLevelClass()
    instance.method_inside_class()
except Exception as exc:
    environments, _ = get_environments_and_defs(exc)
    sample_environment = environments[1]
    lines = sample_environment.code.split('\n')
    first_line = lines[0]
    print(f'{first_line=}')
    assert first_line == '    def method_inside_class(self):'
