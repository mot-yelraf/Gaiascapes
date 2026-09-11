"""Verify isolated native decodes and recovery after a worker deadline.

Parallel invalid decodes exercise the real subprocess boundary without sharing
native state. Fixture tests separately verify normalized NetCDF results.
"""

from concurrent.futures import ThreadPoolExecutor
import subprocess
from pathlib import Path

import pytest

from gaiascapes_host import eumetsat_li, noaa_glm, worker


def test_native_entry_points_are_isolated():
    def decode(index):
        if index % 3 == 0:
            function, args = noaa_glm.count_glm_flashes, (b'',)
        elif index % 3 == 1:
            function, args = noaa_glm.parse_glm_document, (b'', 'fixture.nc')
        else:
            function, args = eumetsat_li.parse_li_chunk, (b'', 'fixture.nc', 'product')
        try:
            function(*args)
        except (ValueError, OSError):
            pass
    with ThreadPoolExecutor(max_workers=3) as callers:
        list(callers.map(decode, range(6)))


def test_worker_timeout_does_not_poison_next_operation():
    with pytest.raises(subprocess.TimeoutExpired):
        worker.run_operation(('function', 'time', 'sleep', (10,), {}), .1)
    result, changes, error = worker.run_operation(('function', 'builtins', 'sum', ([1, 2],), {}), 5)
    assert (result, changes, error) == (3, {}, None)


def test_worker_removes_its_native_temporary_directory():
    path, _changes, error = worker.run_operation(('function', 'tempfile', 'gettempdir', (), {}), 5)
    assert error is None
    assert not Path(path).exists()
