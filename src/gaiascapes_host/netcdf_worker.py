"""Isolate native NetCDF decoding in deadline-bound processes.

Native libraries never run concurrently in one process. Standalone decodes use
short-lived workers; provider workers already supply isolation and a deadline.
"""

from functools import wraps
import subprocess

from . import worker

DECODE_TIMEOUT_SECONDS = 20.0


def netcdf_decoder(function):
    """Decode natively in a process that can be terminated if it hangs."""
    @wraps(function)
    def decode(*args, **kwargs):
        if worker.IN_WORKER:
            return function(*args, **kwargs)
        try:
            result, _changes, error = worker.run_operation(
                ('function', function.__module__, function.__name__, args, kwargs),
                DECODE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError("NetCDF decoding timed out; worker restarted") from None
        if error is not None:
            raise error
        return result
    return decode
