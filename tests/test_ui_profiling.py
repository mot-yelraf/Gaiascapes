"""Verify soak-profile evidence and isolation without launching a browser.

Clock progress, fresh cues, and non-silent output are independent requirements;
saved dropdown values alone must never turn a failed transition into a pass.
"""

import math
from pathlib import Path
import runpy
import struct
import wave
from types import SimpleNamespace

import pytest


PROFILE = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/ui_profiling.py'))


def test_recording_activation_requires_fresh_matching_audio_progress_and_signal():
    """Reject stale, silent, stalled, paused, and wrong-kind playback."""
    active = PROFILE['playback_active']
    cue = {'sequence': 12, 'instrument': 'birdsong', 'output_channel': 'background'}
    previous = {'sequence': 12, 'position': 1.0}
    browser = {'kind': 'birdsong', 'sequence': 12, 'position': 2.0,
               'paused': False, 'gain': .2, 'rms': .01, 'active_players': 1}
    assert active('birdsong', browser, [cue], 10, previous)
    for changes in ({'rms': 0}, {'position': 1.0}, {'kind': 'frog_calls'},
                    {'paused': True}, {'gain': 0}, {'sequence': 11}):
        assert not active('birdsong', {**browser, **changes}, [cue], 10, previous)
    assert not active('birdsong', browser, [cue], 12, previous)
    assert active('birdsong', browser, [cue], 12, previous, retained_sequence=12)
    assert not active('birdsong', {**browser, 'rms': 0}, [cue], 12, previous, retained_sequence=12)
    assert not active('birdsong', browser, [{**cue, 'output_channel': 'preview'}], 10, previous)
    assert not active('birdsong', browser, [cue], 10, None)


def test_disabled_sound_requires_silence_and_generated_voice_requires_dispatch():
    """Distinguish intentional silence from generated-voice dispatch evidence."""
    active = PROFILE['playback_active']
    silent = {'active_players': 0, 'rms': 0}
    assert active('none', silent, [], 0, None)
    assert active('muted', {**silent, 'gain': 0, 'active_players': 1}, [], 0, None)
    assert not active('muted', {**silent, 'gain': .5}, [], 0, None)
    assert not active('none', {**silent, 'active_players': 1}, [], 0, None)
    assert not active('none', {**silent, 'rms': .05}, [], 0, None)
    cue = {'sequence': 2, 'instrument': 'ocean_swell', 'output_channel': 'background'}
    assert active('ocean_swell', {}, [cue], 1, None)
    assert not active('ocean_swell', {}, [cue], 2, None)


def test_plan_covers_sound_values_returns_and_source_reenable():
    """Include switching back, each voice slot, and disabled/re-enabled recordings."""
    recordings = PROFILE['RECORDINGS']
    inventory = {key: [{'value': value} for value in values] for key, values in {
        'backgroundInstrument': ['none', 'ocean_swell', *recordings],
        'event1Instrument': ['none', 'earthquake', 'natural_thunder'],
        'event2Instrument': ['none', 'earthquake', 'natural_thunder'],
        'event3Instrument': ['none', 'earthquake', 'natural_thunder'],
        'theme': ['earth', 'ocean'], 'backgroundAnimation': ['burst', 'paint', 'murmuration'],
        'displayUnits': ['metric', 'imperial'],
        **{control: ['a', 'b'] for control in PROFILE['DISPLAY_CONTROLS'].values()},
    }.items()}
    plan = PROFILE['build_plan'](inventory, False)
    assert [step['background'] for step in plan[:3]] == ['birdsong', 'feline_calls', 'birdsong']
    assert set(step['background'] for step in plan) == set(item['value'] for item in inventory['backgroundInstrument'])
    for slot in ('event_1', 'event_2', 'event_3'):
        assert {step['voices'][slot] for step in plan} == {'none', 'earthquake', 'natural_thunder'}
    assert all('skip' in step for step in plan if step['background'] == 'frog_calls')
    for kind in recordings:
        assert [step['source_enabled'] for step in plan if step['background'] == kind][-4:] == [False, True, True, True]


def test_fixture_recording_is_decodable_non_silent_and_served_in_isolated_data(tmp_path):
    """Create a short WAV without external files, renderer, or provider access."""
    client = PROFILE['FixtureRecording'](tmp_path, 'frog_calls', .1)
    event = client.event_at(1)
    assert event.kind == 'frog_calls'
    assert event.traits['media_url'] == '/frog-calls-media/profile.wav'
    with wave.open(str(tmp_path / 'media/frog_calls/profile.wav'), 'rb') as source:
        assert source.getnframes() == 1600
        data = source.readframes(1600)
    samples = struct.unpack('<1600h', data)
    assert math.sqrt(sum(value * value for value in samples) / len(samples)) > 100
    PROFILE['FixtureRecording'](tmp_path, 'frog_calls', .1, silent=True)
    with wave.open(str(tmp_path / 'media/frog_calls/profile.wav'), 'rb') as source:
        assert set(source.readframes(1600)) == {0}


def test_output_and_server_reject_installed_or_preexisting_runtime(tmp_path, monkeypatch):
    """Never attach to an installed configuration or create test state beneath it."""
    data_dir = tmp_path / 'installation' / 'data'
    data_dir.mkdir(parents=True)
    config_path = data_dir / 'config.json'
    config_path.write_text('{"http_port":8769,"osc_port":57130}')
    protected = {str(config_path): 'fingerprint'}
    for path in (data_dir, data_dir / 'profiling'):
        with pytest.raises(ValueError, match='outside installed runtime'):
            PROFILE['validate_output'](path, protected)
    PROFILE['validate_output'](tmp_path / 'artifacts', protected)
    monkeypatch.setenv('GAIA_SCAPE_DATA_DIR', str(data_dir))
    monkeypatch.setenv('UI_PROFILING_TOKEN', 'test-session')
    (data_dir / '.ui-profiling').write_text('test-session')
    with pytest.raises(RuntimeError, match='new, marked runtime'):
        PROFILE['serve'](SimpleNamespace())
    assert config_path.read_text() == '{"http_port":8769,"osc_port":57130}'


@pytest.mark.parametrize('value', ['0', '-1', 'nan', 'inf'])
def test_nonfinite_or_nonpositive_durations_are_rejected(value):
    """Do not accidentally start an unbounded or zero-observation soak."""
    with pytest.raises(SystemExit, match='finite and positive'):
        PROFILE['main'](['--minutes', value])


def test_preview_length_intervals_are_rejected():
    """Keep the soak on the full-recording path rather than short previews."""
    with pytest.raises(SystemExit, match='preserve full-recording playback'):
        PROFILE['main'](['--interval-seconds', '5'])


def test_default_profile_splits_thirty_minutes_and_continues_after_failure(tmp_path):
    """Keep baseline failures while still collecting independent real-mode evidence."""
    credential_source = tmp_path / 'installed-config.json'
    args = PROFILE['parser']().parse_args(['--output', str(tmp_path / 'combined'),
                                           '--credentials-from', str(credential_source)])
    assert args.mode == 'both' and args.minutes is None and args.runs == 3
    calls = []

    def phase(arguments):
        parsed = PROFILE['parser']().parse_args(arguments)
        calls.append(parsed)
        return 1 if parsed.mode == 'fixture' else 0

    assert PROFILE['run_both'](args, run_phase=phase) == 1
    assert [(call.mode, call.minutes) for call in calls] == [('fixture', None), ('real', None)] * 3
    assert calls[0].output != calls[1].output
    assert all(call.credentials_from is None for call in calls if call.mode == 'fixture')
    assert all(call.credentials_from == credential_source for call in calls if call.mode == 'real')


def test_combined_profile_stops_after_interruption_and_preserves_options(tmp_path):
    """Do not start real providers after a canceled baseline."""
    args = PROFILE['parser']().parse_args([
        '--output', str(tmp_path / 'interrupted'), '--max-steps', '2',
        '--start-step', '3', '--headed', '--trace-all', '--fixture-silent-kind', 'birdsong'])
    calls = []

    def phase(arguments):
        parsed = PROFILE['parser']().parse_args(arguments)
        calls.append(parsed)
        return 130

    assert PROFILE['run_both'](args, run_phase=phase) == 130
    assert len(calls) == 1
    assert calls[0].max_steps == 2 and calls[0].start_step == 3
    assert calls[0].headed and calls[0].trace_all
    assert calls[0].fixture_silent_kind == 'birdsong'


def test_real_profile_can_populate_its_own_birdsong_cache(tmp_path):
    """Fresh real-mode data must not require borrowing the installation's cache."""
    from gaiascapes_host.commons_birdsong import CommonsBirdsongClient

    owned = CommonsBirdsongClient(tmp_path / 'profile')
    separate = CommonsBirdsongClient(tmp_path / 'other')
    PROFILE['prepare_real_recordings'](SimpleNamespace(birdsong=owned))
    assert owned.allow_downloads is True
    assert separate.allow_downloads is False


def test_interrupt_is_observed_at_safe_browser_boundaries(monkeypatch):
    """Pending stop requests raise between operations, not inside Playwright callbacks."""
    check = PROFILE['check_interrupted']
    monkeypatch.setitem(check.__globals__, '_STOP_REQUESTED', False)
    check()
    monkeypatch.setitem(check.__globals__, '_STOP_REQUESTED', True)
    with pytest.raises(KeyboardInterrupt):
        check()


def complete_inventory():
    """Build a small independent control inventory for coverage contract tests."""
    from ui_profile_settings import CHECK_FIELDS, RANGE_FIELDS, SELECT_FIELDS, SOURCE_FIELDS
    inventory = {key: [{'value': 'none'}, {'value': 'birdsong'}, {'value': 'feline_calls'}]
                 if key == 'backgroundInstrument' else [{'value': 'none'}, {'value': 'earthquake'}]
                 if key.startswith('event') and key.endswith('Instrument') else [{'value': 'a'}, {'value': 'b'}]
                 for key in SELECT_FIELDS}
    inventory.update(theme=[{'value': 'earth'}, {'value': 'ocean'}],
                     backgroundAnimation=[{'value': 'burst'}, {'value': 'paint'}])
    controls = {key: {'type': 'select', 'values': [item['value'] for item in inventory[key]], 'pane': 'instruments'}
                for key in SELECT_FIELDS}
    controls.update({key: {'type': 'checkbox', 'checked': False, 'pane': 'sources'}
                     for key in set(CHECK_FIELDS) | set(SOURCE_FIELDS)})
    controls.update({key: {'type': 'range', 'min': '1' if key.endswith('LightningSampleRate') else '0',
                          'max': '11' if key.endswith('LightningSampleRate') else '100', 'pane': 'instruments'}
                     for key in RANGE_FIELDS})
    inventory['_controls'] = controls
    inventory['_locations'] = {kind: [{'id': 'site-1', 'name': 'First site', 'selected': True},
                                     {'id': 'site-2', 'name': 'Second site', 'selected': False}]
                               for kind in ('whale_song', 'dolphin_calls')}
    return inventory


def test_complete_plan_covers_every_control_value_and_location_actions():
    """Prevent a passing sound-only subset from being reported as full coverage."""
    from ui_profile_settings import required_values
    inventory = complete_inventory()
    plan = PROFILE['build_settings_plan'](inventory, PROFILE['build_plan'](inventory, True))
    assert len({case['case_id'] for case in plan}) == len(plan)
    for control, metadata in inventory['_controls'].items():
        covered = {str(case['covers'][control]) for case in plan if control in case['covers']}
        assert {str(value) for value in required_values(metadata)} <= covered, control
    cases = {case['case_id'] for case in plan}
    for catalog in ('birdsong', 'frog_calls', 'ocean_swell', 'storm_outlook'):
        assert {f'locations/{catalog}/{action}' for action in ('edit', 'map', 'restore')} <= cases
    assert 'history/view' in cases and 'locations/birdsong/read-only' in cases
    assert all('password' not in case.get('extra', {}) for case in plan)


def test_unknown_controls_and_unsupported_types_block_completeness():
    """New UI controls must be mapped deliberately rather than silently omitted."""
    inventory = complete_inventory()
    base = PROFILE['build_plan'](inventory, True)
    inventory['_controls']['newSetting'] = {'type': 'checkbox'}
    with pytest.raises(RuntimeError, match='Unmapped settings controls'):
        PROFILE['build_settings_plan'](inventory, base)
    from ui_profile_settings import required_values
    with pytest.raises(RuntimeError, match='Unsupported settings control'):
        required_values({'type': 'text'})


def test_coverage_separates_attempted_verified_and_truncated_runs():
    """Failed, blocked, and unexecuted cases cannot satisfy verified coverage."""
    audit = PROFILE['coverage_audit']
    plan = [{'case_id': 'one'}, {'case_id': 'two'}]
    partial = [{'selection': plan[0], 'outcome': 'passed'}]
    assert not audit(plan, partial)['plan_complete']
    assert audit(plan, partial)['unattempted'] == ['two']
    attempted = partial + [{'selection': plan[1], 'outcome': 'blocked'}]
    assert audit(plan, attempted)['plan_complete']
    assert not audit(plan, attempted)['verification_complete']
    attempted[1]['outcome'] = 'passed'
    assert audit(plan, attempted)['verification_complete']


def test_nested_saved_settings_and_source_membership_are_verified():
    """Use actual saved fields, including region sets and coordinate precision."""
    from ui_profile_settings import assert_settings
    config = {'enabled_sources': ['usgs'], 'sites': [{'latitude': 1.2345}],
              'whale_song_regions': ['b', 'a'], 'gain': .5}
    assert_settings(config, {'@source:usgs': True, 'sites.0.latitude': 1.23,
                             'whale_song_regions': ['a', 'b'], 'gain': .5})
    with pytest.raises(RuntimeError, match='Saved'):
        assert_settings(config, {'@source:usgs': False})


def test_fixture_provider_returns_normalized_events_through_capture_contract():
    """Exercise source toggles with valid events, rather than only saved flags."""
    provider = PROFILE['FixtureProvider']('eumetsat_mtg_li', 'lightning_flash')
    events = provider.fetch()
    assert len(events) == 1
    assert events[0].provider == 'eumetsat_mtg_li'
    assert events[0].kind == 'lightning_flash'
    assert events[0].timestamp > 0
    assert provider.status()['configured'] is True
