"""Regression checks for documented KMA observations and credential handling.

Capture is exercised against an isolated app with synthetic responses.
"""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from gaiascapes_host.app import create_app
from gaiascapes_host.kma_lightning import parse_strokes


# Field layout from KMA's published "new_lgt_data_format.pdf" example.
ROW = (
    "111182 2015-01-22 01:59:27.655747+09:00 5 "
    "0101000020E6100000000000202F7D5F40000000200F8B4040 "
    "125.956 33.0864 0.0 -23.3 0.94 1 8 21 20 19 18 17 11 22 13 0 22670"
)


def test_kma_normalizes_documented_stroke_format():
    bad_quality = ROW.removesuffix("0 22670") + "1 22670"
    event, = parse_strokes(f"# KMA observations\n{ROW}\n{bad_quality}")
    expected = datetime(2015, 1, 21, 16, 59, 27, 655747, tzinfo=timezone.utc)
    assert event.timestamp == pytest.approx(expected.timestamp(), abs=1e-6, rel=0)
    assert (event.latitude, event.longitude) == (33.0864, 125.956)
    assert event.traits["current_ka"] == -23.3
    assert event.traits["stroke_type"] == "cloud_to_ground"
    assert event.kind == "lightning_flash"
    assert parse_strokes("\n") == ()
    with pytest.raises(ValueError, match="Unexpected KMA"):
        parse_strokes("<html>Access denied</html>")


def test_kma_settings_and_capture(tmp_path, monkeypatch):
    app = create_app(tmp_path, auto_capture=False)
    service = app.state.service
    with TestClient(app) as client:
        payload = {"enabled_sources": ["kma_lightning"],
                   "instrument_slots": service.config.instrument_slots()}
        endpoint = "/api/settings/audio"
        assert client.put(endpoint, json=payload).status_code == 422
        result = client.put(endpoint, json={**payload, "kma_api_key": "private-test-key"})
        assert result.status_code == 200
        assert result.json()["kma_credentials_configured"]
        assert client.put(endpoint, json=payload).status_code == 200
        assert service.config.kma_api_key == "private-test-key"
        home = client.get("/")
        for response in (result, home, client.get("/api/config")):
            assert "private-test-key" not in response.text
        group = home.text.split('aria-labelledby="lightningSourcesHeading"', 1)[1]
        group = group.split('aria-label="Other event sound sources"', 1)[0]
        assert all(f'id="{source}"' in group for source in
                   ("sourceKma", "sourceGlm", "sourceMtgLi"))

    observed = datetime.now(timezone.utc).isoformat(sep=" ")
    event, = parse_strokes(ROW.replace("2015-01-22 01:59:27.655747+09:00", observed))
    played = []

    async def fetch(source, provider):
        assert source == "kma_lightning"
        assert provider is service.kma_lightning
        return (event,)

    async def play(observed):
        played.append(observed)

    monkeypatch.setattr(service, "_fetch_source", fetch)
    monkeypatch.setattr(service, "_play_live_event", play)

    async def capture():
        service.config.live_mode = "continuous"
        service.playback.start()
        try:
            assert (await service.capture_once(source="kma_lightning"))["inserted"] == 1
            assert (await service.capture_once(source="kma_lightning"))["inserted"] == 0
        finally:
            await service.playback.stop()

    asyncio.run(capture())
    assert played == [event]
