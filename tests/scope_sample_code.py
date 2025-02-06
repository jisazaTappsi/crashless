import os


def first_level_method():
    print('has some context on level 1: line 1')
    raise Exception
    print('has some context on level 1: line 2')
    print('has some context on level 1: line 3')


class FirstLevelClass:

    def method_inside_class(self):
        print('has some context on level 2: line 1')
        raise Exception
        print('has some context on level 2: line 2')
        print('has some context on level 2: line 3')
