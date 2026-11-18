"""Tests for keyless Wikimedia Commons birdsong caching.

Synthetic API and audio responses verify licensing, local persistence, and
normalized attribution without relying on the external Commons service.
"""

import io
import json
import os

import pytest

from gaiascapes_host.commons_birdsong import (
    BIRDSONG_LOCATIONS,
    COMMONS_CATALOG,
    CommonsBirdsongClient,
)


class FakeOpener:
    def __init__(self, document, audio=b"ID3-test-audio!"):
        self.responses = [io.BytesIO(json.dumps(document).encode()), io.BytesIO(audio)]
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


def commons_document(license_name="CC BY 4.0"):
    return {
        "query": {
            "pages": [
                {
                    "pageid": 42,
                    "title": "File:Forest birds.mp3",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/forest-birds.mp3",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Forest_birds.mp3",
                            "mime": "audio/mpeg",
                            "size": 15,
                            "extmetadata": {
                                "Artist": {"value": '<a href="/user">A. Recordist</a>'},
                                "LicenseShortName": {"value": license_name},
                                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"},
                            },
                        }
                    ],
                }
            ]
        }
    }


def test_catalog_has_nineteen_global_locations():
    assert len(BIRDSONG_LOCATIONS) == 19
    assert len({location[0] for location in BIRDSONG_LOCATIONS}) == 19
    assert any(location[2] < 0 for location in BIRDSONG_LOCATIONS)
    assert any(location[2] > 0 for location in BIRDSONG_LOCATIONS)
    assert any(location[3] < 0 for location in BIRDSONG_LOCATIONS)
    assert any(location[3] > 0 for location in BIRDSONG_LOCATIONS)


def test_client_discovers_downloads_and_reuses_cached_commons_audio(tmp_path):
    opener = FakeOpener(commons_document())
    client = CommonsBirdsongClient(tmp_path, opener=opener, allow_downloads=True)

    first = client.event_at(0)
    second = client.event_at(0)

    assert first.kind == "birdsong"
    assert first.provider == "wikimedia_commons"
    assert first.traits["creator"] == "A. Recordist"
    assert first.traits["license"] == "CC BY 4.0"
    filename = first.traits["media_url"].rsplit("/", 1)[-1]
    assert filename.startswith("canada-churchill-XC")
    assert second.traits["commons_page_id"] == 42
    assert len(opener.requests) == 2
    assert (tmp_path / "media" / "birdsong" / filename).read_bytes() == b"ID3-test-audio!"
    assert "key=" not in opener.requests[0][0].full_url
    assert opener.requests[0][0].get_header("Authorization") is None


def test_client_rejects_incompatible_or_missing_audio(tmp_path):
    opener = FakeOpener(commons_document("Copyrighted"))
    client = CommonsBirdsongClient(tmp_path, opener=opener, allow_downloads=True)

    with pytest.raises(RuntimeError, match="no compatible audio"):
        client.event_at(0)


def test_commons_visits_all_locations_before_advancing_and_wraps_independently(tmp_path, monkeypatch):
    client = CommonsBirdsongClient(tmp_path, allow_downloads=True)
    titles = []

    def discover(title):
        titles.append(title)
        return dict(title=title, creator="Recordist", license="CC BY 4.0", license_url="https://example.org/license",
                    source_url="https://example.org/source", page_id=len(titles), download_url="https://example.org/audio.mp3")

    def download(slug, metadata):
        path = client.media_dir / (slug + ".mp3")
        path.write_bytes(b"OggS-recording")
        return path

    monkeypatch.setattr(client, "_discover", discover)
    monkeypatch.setattr(client, "_download", download)
    count = len(COMMONS_CATALOG)
    for cycle in range(max(len(location['recordings']) for location in COMMONS_CATALOG) + 1):
        for index, location in enumerate(COMMONS_CATALOG):
            event = client.event_at(cycle * count + index)
            expected = location["recordings"][cycle % len(location["recordings"])]
            assert event.traits["region_id"] == location["id"]
            assert event.traits["recording_id"] == expected["recording_id"]
            assert (event.latitude, event.longitude) == (expected["latitude"], expected["longitude"])
    assert len(titles) == sum(len(location["recordings"]) for location in COMMONS_CATALOG)


def test_playback_reads_local_audio_without_network_and_reports_missing_files(tmp_path):
    setup = CommonsBirdsongClient(tmp_path, opener=FakeOpener(commons_document()), allow_downloads=True)
    installed = setup.event_at(0)

    def no_network(*_args, **_kwargs):
        pytest.fail('Local Birdsong playback must not contact Commons')

    playback = CommonsBirdsongClient(tmp_path, opener=no_network)
    assert playback.event_at(0).traits['media_url'] == installed.traits['media_url']
    with pytest.raises(FileNotFoundError, match='not installed locally'):
        playback.event_at(1)
    audio = tmp_path / 'media/birdsong' / installed.traits['media_url'].rsplit('/', 1)[-1]
    audio.write_bytes(b'')
    with pytest.raises(FileNotFoundError, match='Rerun the Gaiascapes installer'):
        playback.event_at(0)


def test_catalog_installer_covers_each_recording_once_and_can_resume(tmp_path, monkeypatch, capsys):
    from gaiascapes_host.birdsong_cache import install_recordings

    client = CommonsBirdsongClient(tmp_path, allow_downloads=True)
    discovered = []

    def discover(title):
        discovered.append(title)
        return dict(title=title, creator='Recordist', license='CC BY 4.0', license_url='https://example.org/license',
                    source_url='https://example.org/source', page_id=42, download_url='https://example.org/audio.mp3')

    def download(slug, metadata):
        from gaiascapes_host.birdsong_cache import read_download_progress

        progress = read_download_progress(tmp_path)
        assert progress['state'] == 'downloading'
        assert progress['title'] == metadata['title']
        assert progress['current'] == len(discovered)
        assert progress['completed'] == len(discovered) - 1
        path = client.media_dir / (slug + '.mp3')
        path.write_bytes(b'OggS-local-recording')
        return path

    monkeypatch.setattr(client, '_discover', discover)
    monkeypatch.setattr(client, '_download', download)
    assert install_recordings(tmp_path, client=client) == 0
    expected = [recording['title'] for location in COMMONS_CATALOG for recording in location['recordings']]
    assert sorted(discovered) == sorted(expected)
    discovered.clear()
    assert install_recordings(tmp_path, client=client) == 0
    assert discovered == []
    assert f'{len(expected)}/{len(expected)} available locally; 0 failed' in capsys.readouterr().out
    from gaiascapes_host.birdsong_cache import read_download_progress

    progress = read_download_progress(tmp_path)
    assert progress['state'] == 'complete'
    assert progress['completed'] == progress['total'] == len(expected)


def test_catalog_installer_reports_failures_and_continues(tmp_path, capsys):
    from gaiascapes_host.birdsong_cache import install_recordings

    class Client:
        def __init__(self):
            self.indices = []

        def event_at(self, index):
            self.indices.append(index)
            if index == 0:
                raise OSError('connection unavailable')

    client = Client()
    assert install_recordings(tmp_path, client=client) == 1
    from gaiascapes_host.birdsong_cache import read_download_progress

    progress = read_download_progress(tmp_path)
    assert progress['state'] == 'error'
    assert progress['completed'] == progress['total'] - 1
    assert '1 failed' in progress['error']
    assert len(client.indices) == sum(len(location['recordings']) for location in COMMONS_CATALOG)
    assert 'connection unavailable' in capsys.readouterr().out


def test_setup_connection_prefers_ipv4_and_falls_back_without_global_changes(monkeypatch):
    import socket
    from gaiascapes_host.http_transport import _connect

    ipv6 = (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('::1', 443, 0, 0))
    ipv4 = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *_a, **_kw: [ipv6, ipv4])
    attempts = []

    class Connection:
        def __init__(self, family, *_args):
            self.family = family
            self.closed = False

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, address):
            attempts.append((address, self.timeout))
            if self.family == socket.AF_INET:
                raise OSError('IPv4 unavailable')

        def close(self):
            self.closed = True

    connections = []

    def create(*args):
        connection = Connection(*args)
        connections.append(connection)
        return connection

    monkeypatch.setattr(socket, 'socket', create)
    connected = _connect(('example.org', 443), timeout=60)
    assert attempts == [(ipv4[4], 5), (ipv6[4], 5)]
    assert connections[0].closed
    assert connected.timeout == 60
    assert connected is connections[1]


def test_all_installers_populate_selected_local_birdsong_directory():
    from pathlib import Path

    shell = Path('install.sh').read_text()
    windows = Path('install.ps1').read_text()
    assert '-m gaiascapes_host.birdsong_cache --data-dir "$INSTALL_DIR/data"' in shell
    assert "-m gaiascapes_host.birdsong_cache --data-dir (Join-Path $InstallDir 'data')" in windows
    assert '${GAIA_SCAPE_INSTALL_BIRDSONG:-yes}' in shell
    assert "$env:GAIA_SCAPE_INSTALL_BIRDSONG -ne 'no'" in windows
    smoke = Path('scripts/smoke_windows_install.py').read_text()
    assert "GAIA_SCAPE_INSTALL_BIRDSONG='no'" in smoke


def test_catalog_installer_stops_requests_when_commons_rate_limits(tmp_path, capsys):
    import urllib.error
    from gaiascapes_host.birdsong_cache import install_recordings

    class Client:
        def __init__(self):
            self.calls = 0

        def event_at(self, index):
            self.calls += 1
            raise urllib.error.HTTPError('https://commons.wikimedia.org', 429, 'rate limit', {'Retry-After': '60'}, None)

    client = Client()
    total = sum(len(location['recordings']) for location in COMMONS_CATALOG)
    assert install_recordings(tmp_path, client=client) == total
    assert client.calls == 1
    assert 'Retry after 60' in capsys.readouterr().out
    from gaiascapes_host.birdsong_cache import read_download_progress

    progress = read_download_progress(tmp_path)
    assert progress['state'] == 'error'
    assert 'Retry after 60' in progress['error']


@pytest.mark.parametrize('contents', ['{', '[]', '{"state": "downloading"}'])
def test_invalid_download_progress_does_not_break_status(tmp_path, contents):
    from gaiascapes_host.birdsong_cache import read_download_progress

    (tmp_path / 'birdsong-download.json').write_text(contents)
    assert read_download_progress(tmp_path)['state'] == 'error'


@pytest.mark.skipif(os.name == 'nt', reason='Process liveness probing uses POSIX signals')
def test_interrupted_download_progress_is_reported(tmp_path, monkeypatch):
    from gaiascapes_host import birdsong_cache

    birdsong_cache._write_download_progress(
        tmp_path, state='downloading', current=1, total=68,
        completed=0, title='Bird song.mp3', error='',
    )

    def missing_process(*args):
        raise ProcessLookupError()

    monkeypatch.setattr(birdsong_cache.os, 'kill', missing_process)
    progress = birdsong_cache.read_download_progress(tmp_path)
    assert progress['state'] == 'error'
    assert 'interrupted' in progress['error']


def test_setup_requests_are_paced_without_delaying_cached_playback(monkeypatch):
    from gaiascapes_host import birdsong_cache

    opener = birdsong_cache._DownloadOpener()
    requests = []
    sleeps = []
    clock = iter([10.0, 10.0, 10.5, 12.0])
    monkeypatch.setattr(birdsong_cache.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(birdsong_cache.time, 'sleep', sleeps.append)
    monkeypatch.setattr(opener._opener, 'open', lambda request, timeout: requests.append((request, timeout)))
    opener('metadata', 30)
    opener('audio', 60)
    assert sleeps == [1.5]
    assert requests == [('metadata', 30), ('audio', 60)]


def test_incomplete_setup_download_is_not_installed(tmp_path):
    client = CommonsBirdsongClient(
        tmp_path, opener=FakeOpener(commons_document(), audio=b'truncated'), allow_downloads=True,
    )
    with pytest.raises(RuntimeError, match='download is incomplete'):
        client.event_at(0)
    assert list(client.media_dir.iterdir()) == []


def ogg_document():
    """Model an original Ogg file with attribution distinct from its MP3 size."""
    document = commons_document()
    page = document['query']['pages'][0]
    page['title'] = 'File:Forest birds.ogg'
    info = page['imageinfo'][0]
    info.update(url='https://upload.wikimedia.org/forest-birds.ogg',
                descriptionurl='https://commons.wikimedia.org/wiki/File:Forest_birds.ogg',
                mime='application/ogg', size=1000)
    return document


def derivative_document(available=True):
    return {'query': {'pages': [{'videoinfo': [{'derivatives': ([{
        'src': 'https://upload.wikimedia.org/transcoded/forest-birds.ogg.mp3',
        'type': 'audio/mpeg',
    }] if available else [])}]}]}}


def test_ogg_uses_commons_mp3_derivative_with_original_attribution(tmp_path):
    opener = FakeOpener(ogg_document())
    opener.responses.insert(1, io.BytesIO(json.dumps(derivative_document()).encode()))
    client = CommonsBirdsongClient(tmp_path, opener=opener, allow_downloads=True)
    event = client.event_at(0)
    assert event.traits['media_url'].endswith('.mp3')
    assert event.traits['title'] == 'Forest birds.ogg'
    assert event.traits['source_url'].endswith('File:Forest_birds.ogg')
    assert event.traits['license'] == 'CC BY 4.0'
    metadata = json.loads(next(client.media_dir.glob('*.json')).read_text())
    assert metadata['size'] == 15  # MP3 size, not the 1000-byte Ogg original.
    assert metadata['mime'] == 'audio/mpeg'
    assert 'prop=videoinfo' in opener.requests[1][0].full_url
    assert len(opener.requests) == 3
    client.event_at(0)
    assert len(opener.requests) == 3


def test_setup_upgrades_cached_ogg_without_deleting_original(tmp_path):
    opener = FakeOpener(ogg_document())
    opener.responses.insert(1, io.BytesIO(json.dumps(derivative_document()).encode()))
    client = CommonsBirdsongClient(tmp_path, opener=opener, allow_downloads=True)
    first = COMMONS_CATALOG[0]['recordings'][0]
    slug = COMMONS_CATALOG[0]['id'] + '-XC' + first['recording_id']
    original = client.media_dir / (slug + '.ogg')
    original.write_bytes(b'original-ogg')
    metadata = dict(file=original.name, title='Forest birds.ogg', creator='Recordist',
                    license='CC BY 4.0', license_url='https://example.org/license',
                    source_url='https://commons.wikimedia.org/wiki/File:Forest_birds.ogg',
                    page_id=42, download_url='https://upload.wikimedia.org/forest-birds.ogg',
                    mime='application/ogg', size=len(b'original-ogg'))
    client._write_metadata(client.media_dir / (slug + '.json'), metadata)
    with pytest.raises(FileNotFoundError):
        CommonsBirdsongClient(tmp_path).event_at(0)
    event = client.event_at(0)
    assert event.traits['media_url'].endswith('.mp3')
    assert original.read_bytes() == b'original-ogg'
    assert (client.media_dir / (slug + '.mp3')).read_bytes() == b'ID3-test-audio!'


def test_ogg_without_compatible_mp3_reports_failure(tmp_path):
    opener = FakeOpener(ogg_document())
    opener.responses.insert(1, io.BytesIO(json.dumps(derivative_document(False)).encode()))
    client = CommonsBirdsongClient(tmp_path, opener=opener, allow_downloads=True)
    with pytest.raises(RuntimeError, match='no compatible MP3 version'):
        client.event_at(0)
    assert list(client.media_dir.iterdir()) == []


def test_derivative_rejects_truncated_http_body(tmp_path):
    opener = FakeOpener(ogg_document())
    opener.responses.insert(1, io.BytesIO(json.dumps(derivative_document()).encode()))
    opener.responses[-1].headers = {'Content-Length': '100'}
    client = CommonsBirdsongClient(tmp_path, opener=opener, allow_downloads=True)
    with pytest.raises(RuntimeError, match='download is incomplete'):
        client.event_at(0)
    assert list(client.media_dir.iterdir()) == []
