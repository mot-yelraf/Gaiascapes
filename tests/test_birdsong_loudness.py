"""Check offline audio measurement parsing without network or sound devices.

Synthetic FFmpeg reports protect silence handling and duration weighting, so
fully silent windows cannot be mistaken for missing or audible measurements.
"""

from pathlib import Path
import runpy

import pytest


AUDIT = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/audit_birdsong_loudness.py'))


def test_silent_and_partial_windows_are_time_weighted():
    log = '''lavfi.astats.Overall.RMS_level=-inf
lavfi.astats.Overall.RMS_level=-60.0
lavfi.astats.Overall.RMS_level=-20.0
lavfi.astats.Overall.RMS_level=-60.0
mean_volume: -43.0 dB
max_volume: -2.0 dB
I: -40.0 LUFS
time=00:00:03.50
'''
    measured = AUDIT['parse_analysis'](log)
    assert measured['mean_dbfs'] == -43
    assert measured['integrated_lufs'] == -40
    assert measured['quiet_fraction_below_minus50_dbfs'] == pytest.approx(2.5 / 3.5, abs=.0001)
    assert measured['longest_quiet_seconds'] == 2
    assert measured['loudest_second_dbfs'] == -20
    assert measured['one_second_rms_dbfs'][0] == -120


@pytest.mark.parametrize('log', ['', 'time=00:00:00.00', 'time=00:00:01.00'])
def test_empty_or_incomplete_audio_reports_fail(log):
    with pytest.raises(ValueError):
        AUDIT['parse_analysis'](log)


def test_curation_limits_flag_extreme_levels_and_long_quiet_stretches():
    good = {'mean_dbfs': -45., 'integrated_lufs': -45., 'longest_quiet_seconds': 19.99}
    issues = AUDIT['quality_issues']
    assert issues(good) == []
    assert issues({**good, 'integrated_lufs': -12.}) == []
    assert issues({**good, 'mean_dbfs': -45.1}) == ['average_below_minus45_dbfs']
    assert issues({**good, 'integrated_lufs': -45.1}) == ['loudness_below_minus45_lufs']
    assert issues({**good, 'integrated_lufs': -11.9}) == ['loudness_above_minus12_lufs']
    assert issues({**good, 'longest_quiet_seconds': 20.}) == ['quiet_stretch_at_least20_seconds']


def test_current_catalog_matches_the_reviewed_audible_set():
    import json
    from gaiascapes_host.commons_birdsong import COMMONS_CATALOG, SUPPORTED_LICENSES

    report = json.loads((Path(__file__).parents[1] / 'docs/birdsong-quality-audit.json').read_text())
    accepted = {row['recording_id']: row for row in report['accepted']}
    excluded = {row['recording_id'] for row in report['excluded']}
    actual = {r['recording_id']: r for loc in COMMONS_CATALOG for r in loc['recordings']}
    assert len(COMMONS_CATALOG) == 19
    assert len(actual) == len(accepted) == 68
    assert actual.keys() == accepted.keys()
    assert not actual.keys() & excluded
    assert {'442361', '442377'} <= excluded
    assert len({row['sha256'] for row in accepted.values()}) == 68
    for rid, row in accepted.items():
        assert AUDIT['quality_issues'](row) == [], rid
        assert actual[rid]['license'] in SUPPORTED_LICENSES
        assert row['source_url'] == actual[rid]['source_url']
