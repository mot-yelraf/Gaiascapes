"""Tests for EUMETSAT MTG Lightning Imager product normalization.

Synthetic nested NetCDF chunks exercise the operational LI flash variable
layout without contacting or requiring credentials for the Data Store.
"""

import io
import zipfile

from netCDF4 import Dataset

from gaiascapes.events import GaiaEvent
from gaiascapes_host.eumetsat_li import (
    MAX_FLASHES_PER_PRODUCT,
    _select_geographically_distributed,
    parse_li_product,
)


def _li_chunk(path):
    with Dataset(path, "w") as dataset:
        data = dataset.createGroup("data")
        data.createDimension("flashes", 2)
        flash_time = data.createVariable("flash_time", "f8", ("flashes",))
        flash_time.units = "seconds since 2000-01-01 00:00:00.0"
        flash_time[:] = [10.0, 11.5]
        data.createVariable("latitude", "f4", ("flashes",))[:] = [48.2, -1.3]
        data.createVariable("longitude", "f4", ("flashes",))[:] = [15.4, 32.5]
        data.createVariable("flash_id", "u4", ("flashes",))[:] = [17, 18]
        data.createVariable("radiance", "f4", ("flashes",))[:] = [10.0, 1000.0]
        data.createVariable("flash_duration", "u2", ("flashes",))[:] = [120, 340]
        data.createVariable("number_of_events", "u2", ("flashes",))[:] = [3, 8]
        data.createVariable("number_of_groups", "u2", ("flashes",))[:] = [2, 4]
        data.createVariable("flash_footprint", "u2", ("flashes",))[:] = [1, 5]


def test_li_zip_product_normalizes_nested_flash_variables(tmp_path):
    chunk = tmp_path / "flash.nc"
    _li_chunk(chunk)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.write(
            chunk,
            "W_XX-EUMETSAT,MTI1+LI-2-LFL--FD--CHK-BODY---NC4E.nc",
        )

    events = parse_li_product(payload.getvalue(), "MTG-LI-product")

    assert len(events) == 2
    assert {event.provider for event in events} == {"eumetsat_mtg_li"}
    assert {event.kind for event in events} == {"lightning_flash"}
    assert [round(event.longitude, 1) for event in events] == [15.4, 32.5]
    assert events[1].strength > events[0].strength
    assert events[1].traits["flash_duration_ms"] == 340
    assert events[1].traits["event_count"] == 8
    assert events[1].traits["group_count"] == 4
    assert events[1].traits["flash_footprint_pixels"] == 5
    assert events[1].traits["product"] == "MTG-LI-product"


def test_li_sampling_distributes_flashes_across_geographic_cells():
    dense = [
        GaiaEvent(
            "eumetsat_mtg_li",
            f"dense-{index}",
            "lightning_flash",
            float(index),
            latitude=1.0,
            longitude=21.0,
            strength=1.0,
        )
        for index in range(MAX_FLASHES_PER_PRODUCT + 40)
    ]
    outliers = [
        GaiaEvent(
            "eumetsat_mtg_li",
            "europe",
            "lightning_flash",
            500.0,
            latitude=48.0,
            longitude=10.0,
            strength=0.1,
        ),
        GaiaEvent(
            "eumetsat_mtg_li",
            "south-america",
            "lightning_flash",
            501.0,
            latitude=-20.0,
            longitude=-45.0,
            strength=0.1,
        ),
    ]

    sampled = _select_geographically_distributed(
        dense + outliers, MAX_FLASHES_PER_PRODUCT
    )

    assert len(sampled) == MAX_FLASHES_PER_PRODUCT
    assert {event.event_id for event in outliers}.issubset(
        event.event_id for event in sampled
    )


def test_li_sampling_keeps_strongest_flashes_within_each_cell():
    events = [
        GaiaEvent(
            "eumetsat_mtg_li",
            str(index),
            "lightning_flash",
            float(index),
            latitude=1.0,
            longitude=21.0,
            strength=index / 10.0,
        )
        for index in range(5)
    ]

    sampled = _select_geographically_distributed(events, 2)

    assert [event.event_id for event in sampled] == ["4", "3"]
