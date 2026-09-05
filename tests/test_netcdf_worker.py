"""Verify process-wide serialization across both lightning decoders.

Instrumented dataset boundaries assert thread ownership without provoking an
unsafe native-library race; provider tests separately decode real fixtures.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading
import time
from types import SimpleNamespace

import pytest

from gaia_scape_host import eumetsat_li, noaa_glm


def test_all_native_entry_points_use_one_worker(monkeypatch):
    threads = []
    active = 0
    peak = 0

    @contextmanager
    def dataset(payload):
        nonlocal active, peak
        threads.append(threading.get_ident())
        active += 1
        peak = max(peak, active)
        try:
            time.sleep(.002)
            yield SimpleNamespace(variables={}, dimensions={}, groups={})
        finally:
            active -= 1

    monkeypatch.setattr(noaa_glm, '_open_dataset', dataset)
    monkeypatch.setattr(eumetsat_li, '_open_dataset', dataset)

    def decode(index):
        if index % 3 == 0:
            assert noaa_glm.count_glm_flashes(b'fixture') == 0
        elif index % 3 == 1:
            with pytest.raises(ValueError, match='lacks'):
                noaa_glm.parse_glm_document(b'fixture', 'fixture.nc')
        else:
            with pytest.raises(ValueError, match='lacks'):
                eumetsat_li.parse_li_chunk(b'fixture', 'fixture.nc', 'product')

    with ThreadPoolExecutor(max_workers=6) as callers:
        list(callers.map(decode, range(18)))
    assert peak == 1
    assert len(set(threads)) == 1
    assert threads[0] != threading.get_ident()
