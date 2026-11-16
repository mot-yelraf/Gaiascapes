"""Define complete, non-combinatorial coverage of the settings interface.

Selectors cover every offered value, checkboxes both states, and continuous
ranges their minimum, midpoint, and maximum. Location fields and action controls
have explicit behavioral cases; password fields are excluded from discovery.
"""

from copy import deepcopy


SOURCE_FIELDS = {
    'sourceUsgs': 'usgs', 'sourceMarine': 'open_meteo_marine',
    'sourceStorm': 'open_meteo_storm', 'sourceGlm': 'noaa_glm',
    'sourceMtgLi': 'eumetsat_mtg_li',
}
SELECT_FIELDS = {
    'backgroundPalette': 'background_palette',
    'backgroundMurmurationPalette': 'background_murmuration_palette',
    'backgroundPaintShape': 'background_paint_shape', 'backgroundEvents': 'background_events',
    'mapProjection': 'map_projection', 'mapCenterLongitude': 'map_center_longitude',
    'soundLocationOrder': 'sound_location_order', 'displayUnits': 'units',
    'birdsongProvider': 'birdsong_provider', 'announcementSynthesizer': 'announcement_synthesizer',
    'announcementVoice': 'announcement_voice', 'announcementVariant': 'announcement_variant',
    **{f'event{i}Instrument': f'event_instruments.event_{i}' for i in range(1, 4)},
    'backgroundInstrument': 'event_instruments.background',
}
CHECK_FIELDS = {
    'announcementsEnabled': 'announcements_enabled', 'systemLocationEnabled': 'system_location_enabled',
    'sourceBirdsong': 'birdsong_enabled', 'sourceFrogCalls': 'frog_calls_enabled',
    'sourceWhaleSong': 'whale_song_enabled', 'sourceDolphinCalls': 'dolphin_calls_enabled',
    **{f'source_{kind}': f'{kind}_enabled' for kind in
       ('feline_calls', 'canine_calls', 'elephant_calls', 'primate_calls')},
}
RANGE_FIELDS = {
    **{f'event{i}Volume': f'instrument_volumes.event_{i}' for i in range(1, 4)},
    'backgroundVolume': 'instrument_volumes.background', 'announcementVolume': 'announcement_volume',
    **{f'event{i}LightningSampleRate': 'lightning_sample_rate' for i in range(1, 4)},
}


def config_value(config, path):
    """Read a dotted configuration field used by a rendered control."""
    for part in path.split('.'):
        config = config[int(part)] if isinstance(config, list) else config[part]
    return config


def required_values(control):
    """Cover finite choices fully and continuous ranges at boundaries and midpoint."""
    if control['type'] not in ('checkbox', 'range', 'select'):
        raise RuntimeError(f'Unsupported settings control type: {control["type"]}')
    if control['type'] == 'checkbox':
        return [False, True]
    if control['type'] == 'range':
        low, high = int(control['min']), int(control['max'])
        if high - low <= 16:
            return list(range(low, high + 1))
        return sorted({low, (low + high) // 2, high})
    return control.get('values', [])


def build_settings_plan(inventory, base_plan):
    """Extend sound transitions to cover every discovered non-credential control."""
    controls = inventory['_controls']
    known = set(SELECT_FIELDS) | set(CHECK_FIELDS) | set(RANGE_FIELDS) | set(SOURCE_FIELDS)
    unknown = set(controls) - known
    if unknown:
        raise RuntimeError(f'Unmapped settings controls: {sorted(unknown)}')
    plan = []
    seen = {}

    def add(case_id, template, covers, **updates):
        case = deepcopy(template)
        case.update(updates, case_id=case_id, covers=covers)
        plan.append(case)
        for key, value in covers.items():
            seen.setdefault(key, set()).add(str(value))

    for index, step in enumerate(base_plan):
        covers = {'backgroundInstrument': step['background'], 'displayUnits': step['units'],
                  **{f'event{i}Instrument': step['voices'][f'event_{i}'] for i in range(1, 4)},
                  **{key: step['volume'] for key in RANGE_FIELDS if key.endswith('Volume') and key != 'announcementVolume'},
                  **step['radios']}
        for control, field in SELECT_FIELDS.items():
            if field in step['controls']:
                covers[control] = step['controls'][field]
        add(f'sounds/{index + 1:03d}', step, covers)
    neutral = deepcopy(base_plan[0])
    neutral.pop('skip', None)
    neutral.update(background='none', voices={f'event_{i}': 'none' for i in range(1, 4)},
                   volume=50, source_enabled=True)
    for control, metadata in controls.items():
        for value in required_values(metadata):
            if str(value) in seen.get(control, set()):
                continue
            extra = {control: value}
            template = deepcopy(neutral)
            if control == 'birdsongProvider':
                template['background'] = 'birdsong'
            if control.startswith('announcement'):
                template['background'] = 'feline_calls'
                extra.update(announcementsEnabled=True)
                extra[control] = value
                if control != 'announcementVolume':
                    extra['announcementVolume'] = 75
            if control.startswith('event') and control.endswith('LightningSampleRate'):
                template['voices'] = {f'event_{i}': 'natural_thunder' for i in range(1, 4)}
            audio_case = template['background'] != 'none'
            add(f'setting/{control}/{str(value).lower()}', template, {control: value},
                extra=extra, short_check=not audio_case,
                restart_recording=control.startswith('announcement'),
                verify_announcement=(bool(extra.get('announcementsEnabled'))
                                     and extra.get('announcementVolume', 75) > 0)
                if control.startswith('announcement') else None)
    for catalog in ('birdsong', 'frog_calls', 'ocean_swell', 'storm_outlook'):
        for action in ('edit', 'map', 'restore'):
            add(f'locations/{catalog}/{action}', neutral, {f'locations:{catalog}:{action}': True},
                action={'kind': 'locations', 'catalog': catalog, 'operation': action}, short_check=True,
                extra={'birdsongProvider': 'xeno_canto'} if catalog == 'birdsong' else {})
    for catalog in ('whale_song', 'dolphin_calls'):
        for site in inventory['_locations'][catalog]:
            for included in ((False, True) if site.get('selected', True) else (True, False)):
                add(f'locations/{catalog}/{site["id"]}/{included}', neutral,
                    {f'locations:{catalog}:{site["id"]}': included}, short_check=True,
                    action={'kind': 'marine_site', 'catalog': catalog, 'site': site, 'included': included})
        add(f'locations/{catalog}/restore', neutral, {f'locations:{catalog}:restore': True}, short_check=True,
            action={'kind': 'locations', 'catalog': catalog, 'operation': 'restore'})
    add('locations/birdsong/read-only', neutral, {'locations:birdsong:read-only': True}, short_check=True,
        action={'kind': 'read_only'})
    for control in ('displayUnits', 'backgroundInstrument', 'event1Instrument', 'event2Instrument', 'event3Instrument'):
        add(f'navigation/{control}', neutral, {f'navigation:{control}': True}, short_check=True,
            action={'kind': 'navigation', 'control': control})
    for slot in ('background', 'event1', 'event2', 'event3'):
        template = deepcopy(neutral)
        if slot == 'background':
            template['background'] = 'feline_calls'
        else:
            template['voices'][f'event_{slot[-1]}'] = 'earthquake'
        add(f'preview/{slot}', template, {f'preview:{slot}': True}, short_check=True,
            action={'kind': 'preview', 'slot': slot})
    for listening in (True, False, True):
        template = deepcopy(neutral)
        template['background'] = 'feline_calls'
        add(f'listening/{len(plan)}/{listening}', template, {'listenButton': listening},
            action={'kind': 'listen', 'enabled': listening})
    add('history/view', neutral, {'history:view': True}, short_check=True, action={'kind': 'history'})
    return plan


def coverage_audit(plan, results):
    """Distinguish attempted cases, verified cases, and unexecuted coverage."""
    required = {case['case_id'] for case in plan}
    attempted = {row['selection'].get('case_id') for row in results}
    verified = {row['selection'].get('case_id') for row in results if row['outcome'] == 'passed'}
    return {'required_cases': len(required), 'attempted_cases': len(required & attempted),
            'verified_cases': len(required & verified), 'plan_complete': required <= attempted,
            'verification_complete': required <= verified,
            'unattempted': sorted(required - attempted), 'unverified': sorted(required - verified)}


def apply_extra_controls(profiler, step):
    """Operate additional settings through their real controls and return expectations."""
    expected = {}
    for control, value in step.get('extra', {}).items():
        metadata = profiler.inventory_data['_controls'][control]
        profiler.pane(metadata['pane'])
        element = profiler.page.locator(f'#{control}')
        if metadata['type'] == 'checkbox':
            element.set_checked(bool(value))
            field = CHECK_FIELDS.get(control, f'@source:{SOURCE_FIELDS.get(control)}')
        elif metadata['type'] == 'range':
            if control.endswith('LightningSampleRate'):
                for slot, select in (('event_1', 'event1Instrument'), ('event_2', 'event2Instrument'), ('event_3', 'event3Instrument')):
                    profiler.sound(select, step['voices'][slot])
            element.fill(str(value))
            element.dispatch_event('input')
            field = RANGE_FIELDS[control]
            value = float(value) / 100 if control.endswith('Volume') else int(value)
        else:
            element.select_option(str(value))
            field = SELECT_FIELDS[control]
        expected[field] = value
    action = step.get('action', {})
    if action.get('kind') in ('locations', 'marine_site', 'read_only'):
        expected.update(apply_location_action(profiler, action))
    if action.get('kind') == 'navigation':
        profiler.pane('instruments')
        control = action['control']
        picker = profiler.page.locator(f'[data-sound-picker][data-select="{control}"]')
        track = picker.locator('.sound-track')
        track.locator('[aria-checked="true"]').press('Home')
        profiler.page.wait_for_timeout(200)
        options = profiler.inventory_data[control]
        for direction, value in ((1, options[1]['value']), (-1, options[0]['value'])):
            picker.locator(f'[data-sound-step="{direction}"]').click()
            if profiler.page.locator(f'#{control}').input_value() != value:
                raise RuntimeError(f'Sound navigation failed for {control}')
        track.locator('[aria-checked="true"]').press('End')
        if profiler.page.locator(f'#{control}').input_value() != options[-1]['value']:
            raise RuntimeError(f'End navigation failed for {control}')
        track.locator('[aria-checked="true"]').press('Home')
        profiler.page.wait_for_timeout(200)
        expected[SELECT_FIELDS[control]] = options[0]['value']
    if action.get('kind') == 'history':
        profiler.pane('history')
        if not profiler.page.locator('#eventList').is_visible():
            raise RuntimeError('Event History did not render')
    return expected


def apply_location_action(profiler, action):
    """Edit all location fields, move a marker, restore defaults, or select marine sites."""
    catalog = action.get('catalog', 'birdsong')
    profiler.pane('locations')
    profiler.page.locator(f'[data-location-catalog="{catalog}"]').click()
    if action['kind'] == 'read_only':
        fields = profiler.page.locator('#forecastLocationList input')
        if not fields.count() or not fields.evaluate_all('(fields) => fields.every(e => e.readOnly)'):
            raise RuntimeError('Commons Birdsong locations must remain read-only')
        if not profiler.page.locator('#restoreForecastLocations').is_disabled():
            raise RuntimeError('Commons Birdsong restore control must be disabled')
        return {}
    field = catalog + ('_regions' if catalog in ('whale_song', 'dolphin_calls') else '_locations')
    before = profiler.api('/api/config')[field]
    if action['kind'] == 'marine_site':
        site = action['site']
        profiler.page.get_by_label(f'Include {site["name"]}', exact=True).set_checked(action['included'])
        selected = set(before)
        if not action['included'] and selected == {site['id']}:
            alternate = next(item for item in profiler.inventory_data['_locations'][catalog] if item['id'] != site['id'])
            profiler.page.get_by_label(f'Include {alternate["name"]}', exact=True).check()
            selected.add(alternate['id'])
        (selected.add if action['included'] else selected.discard)(site['id'])
        return {field: sorted(selected)}
    operation = action['operation']
    if operation == 'restore':
        profiler.page.locator('#restoreForecastLocations').click()
    if catalog in ('whale_song', 'dolphin_calls'):
        sites = profiler.inventory_data['_locations'][catalog]
        selected = [site['id'] for site in sites if profiler.page.get_by_label(
            f'Include {site["name"]}', exact=True).is_checked()]
        return {field: sorted(selected)}
    if operation == 'edit':
        for index, location in enumerate(before):
            profiler.page.get_by_role('button', name=f'Select location {index + 1}', exact=True).click()
            profiler.page.get_by_label(f'Location {index + 1} name', exact=True).fill(f'UI profile {catalog} {index + 1}')
            profiler.page.get_by_label(f'Location {index + 1} name', exact=True).press('Tab')
            for label, coordinate, bound in (('Lat', 'latitude', 89), ('Lon', 'longitude', 179)):
                row = profiler.page.locator('.forecast-location-row.is-selected')
                value = max(-bound, min(bound, round(location[coordinate] + .01, 2)))
                row.get_by_label(label, exact=True).fill(str(value))
                row.get_by_label(label, exact=True).dispatch_event('change')
    if operation == 'map':
        profiler.page.get_by_role('button', name='Select location 1', exact=True).click()
        map_element = profiler.page.locator('#forecastLocationMap')
        bounds = map_element.bounding_box()
        map_element.click(position={'x': bounds['width'] * .53, 'y': bounds['height'] * .55})
    expected = {}
    for index in range(len(before)):
        profiler.page.get_by_role('button', name=f'Select location {index + 1}', exact=True).click()
        row = profiler.page.locator('.forecast-location-row.is-selected')
        expected[f'{field}.{index}.name'] = profiler.page.get_by_label(f'Location {index + 1} name', exact=True).input_value()
        expected[f'{field}.{index}.latitude'] = float(row.get_by_label('Lat', exact=True).input_value())
        expected[f'{field}.{index}.longitude'] = float(row.get_by_label('Lon', exact=True).input_value())
    return expected


def assert_settings(config, expected):
    """Compare saved settings with selected controls, preserving coordinate display precision."""
    for path, value in expected.items():
        if path.startswith('@source:'):
            actual = path.split(':', 1)[1] in config['enabled_sources']
        else:
            actual = config_value(config, path)
        if path.endswith('_regions'):
            actual, value = sorted(actual), sorted(value)
        if path.endswith(('.latitude', '.longitude')):
            actual, value = round(float(actual), 2), round(float(value), 2)
        if str(actual) != str(value):
            # Numeric inputs and JSON sometimes use 0 versus 0.0.
            if isinstance(actual, (int, float)) and isinstance(value, (int, float)) and abs(actual - value) < .001:
                continue
            raise RuntimeError(f'Saved {path}={actual!r}; expected {value!r}')
