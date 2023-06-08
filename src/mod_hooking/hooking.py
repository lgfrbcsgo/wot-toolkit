import inspect
import sys
from functools import wraps

from mod_logging import LOG_CURRENT_EXCEPTION


def monkey_patch(module, func_name, func):
    target = sys.modules[module.__name__] if inspect.ismodule(module) else module

    # raises an error if the target attribute does not exist
    getattr(target, func_name, func)

    setattr(target, func_name, func)


def hooking_strategy(strategy_func):
    def build_decorator(module, func_name):
        def decorator(func):
            orig_func = getattr(module, func_name)

            @wraps(orig_func)
            def patch(*args, **kwargs):
                return strategy_func(orig_func, func, *args, **kwargs)

            monkey_patch(module, func_name, patch)
            return func

        return decorator

    return build_decorator


def safe_callback(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            LOG_CURRENT_EXCEPTION()

    return wrapper
