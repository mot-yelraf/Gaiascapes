from datetime import datetime, timezone

from netCDF4 import Dataset

from gaia_rhythms_host.noaa_glm import (
    NoaaGlmClient,
    count_glm_flashes,
    parse_glm_document,
    select_sonification_events,
)


def _glm_payload(tmp_path):
    path = tmp_path / "glm.nc"
    with Dataset(path, "w", format="NETCDF4") as dataset:
        dataset.platform_ID = "G19"
        dataset.createDimension("number_of_flashes", 3)
        values = {
            "flash_id": ("i4", [41, 42, 43]),
            "flash_lat": ("f4", [30.0, 31.0, -12.0]),
            "flash_lon": ("f4", [-90.0, -91.0, 150.0]),
            "flash_energy": ("f8", [1e-13, 9e-12, 5e-12]),
            "flash_area": ("f8", [2e8, 3e8, 4e8]),
            "flash_quality_flag": ("i2", [0, 3, 0]),
        }
        for name, (kind, data) in values.items():
            variable = dataset.createVariable(name, kind, ("number_of_flashes",))
            variable[:] = data
        for name, data in (
            ("flash_time_offset_of_first_event", [0.2, 0.4, 0.6]),
            ("flash_time_offset_of_last_event", [0.5, 0.8, 1.1]),
        ):
            variable = dataset.createVariable(name, "f8", ("number_of_flashes",))
            variable.units = "seconds since 2026-08-24 22:28:40.000"
            variable[:] = data
    return path.read_bytes()


def test_glm_granule_normalizes_timestamped_quality_flashes(tmp_path, capfd):
    payload = _glm_payload(tmp_path)
    key = (
        "GLM-L2-LCFA/2026/236/22/"
        "OR_GLM-L2-LCFA_G19_s20262362228400_e20262362229000_c.nc"
    )

    events = parse_glm_document(payload, key)
    raw_count = count_glm_flashes(payload)

    assert [event.event_id for event in events] == [
        "G19-20262362228400-41", "G19-20262362228400-43"
    ]
    assert events[0].timestamp == datetime(
        2026, 8, 24, 22, 28, 40, 200000, tzinfo=timezone.utc
    ).timestamp()
    assert events[0].kind == "lightning_flash"
    assert events[0].provider == "noaa_glm"
    assert events[0].traits["satellite"] == "GOES-19"
    assert events[0].traits["flash_area_km2"] == 200.0
    assert events[0].traits["flash_duration_ms"] == 300.0
    assert raw_count == 3
    assert "HDF5-DIAG" not in capfd.readouterr().err


def test_glm_client_starts_with_latest_granule_and_deduplicates(tmp_path):
    payload = _glm_payload(tmp_path)

    class StubClient(NoaaGlmClient):
        def __init__(self):
            super().__init__(now=lambda: datetime(2026, 8, 24, 22, 29, tzinfo=timezone.utc))
            self.keys = {
                "noaa-goes19": ["older.nc", "latest.nc"],
                "noaa-goes18": [],
            }

        def _available_keys(self, bucket, now):
            return list(self.keys[bucket])

        def _download(self, bucket, key):
            return payload

    client = StubClient()

    first = client.fetch()
    repeated = client.fetch()
    client.keys["noaa-goes19"].append("next.nc")
    following = client.fetch()

    assert len(first) == 2
    assert repeated == ()
    assert len(following) == 2
    assert client.last_granule_count == 1
    assert client.last_raw_flash_count == 3
    assert client.last_sampled_flash_count == 2
    assert client.last_sonified_flash_count == 1


def test_sonification_selects_every_eleventh_flash_in_timestamp_order():
    from gaia_rhythms.events import GaiaEvent

    events = tuple(
        GaiaEvent("noaa_glm", str(index), "lightning_flash", 100 + index)
        for index in reversed(range(25))
    )

    selected = select_sonification_events(events)

    assert [event.event_id for event in selected] == ["0", "11", "22"]
    assert [event.timestamp for event in selected] == [100.0, 111.0, 122.0]
