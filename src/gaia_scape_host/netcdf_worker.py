"""Serialize native NetCDF decoding on one process-wide worker.

Provider downloads remain concurrent, but all native dataset operations run
on the same thread because netcdf-c does not support concurrent threaded IO.
"""

from concurrent.futures import ThreadPoolExecutor
from functools import wraps


_DECODER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gaia-netcdf")


def netcdf_decoder(function):
    """Run a synchronous decoding entry point on the shared native worker."""
    @wraps(function)
    def decode(*args, **kwargs):
        return _DECODER.submit(function, *args, **kwargs).result()
    return decode
