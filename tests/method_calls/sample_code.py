import another_module
from another_module import function_called_directly, call_in_f_string, intricate_call


def my_local_function1(a, b):
    return a + b


def my_local_function2(c, d):
    return c * d


def my_local_function3(f, e):
    return f - e


def un_used_method():
    pass


def my_scope():
    my_local_function1(1, 1)
    raise Exception
    my_local_function2(1, 1)
    my_local_function3(1, 1)
    another_module.function_called_indirectly(1, 1)
    function_called_directly(1,1)
    list()  # built-in function

    if intricate_call():
        print('blah')
    print(f'{True if call_in_f_string() else False}')

