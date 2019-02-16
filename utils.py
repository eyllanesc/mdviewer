from functools import lru_cache

import decorator

enable_log = True


def cached_property(getter):
    # https://github.com/mherrmann/fbs/blob/master/fbs_runtime/application_context.py#L18
    """
    A cached Python @property. You use it in conjunction with ApplicationContext
    below to instantiate the components that comprise your application. For more
    information, please consult the Manual:
        https://build-system.fman.io/manual/#cached_property
    """
    return property(lru_cache()(getter))


@decorator.decorator
def log(function, *args, **kwargs):
    """Decorates a function by tracing the begining and
    end of the function execution, if doTrace global is True"""
    if enable_log:
        print("> " + function.__name__, args, kwargs)
    result = function(*args, **kwargs)
    if enable_log:
        print("< " + function.__name__, args, kwargs, "->", result)
    return result
