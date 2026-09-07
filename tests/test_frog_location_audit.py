"""Verify frog-default evidence and the offline behavior of the audit command.

Live API access is reserved for the maintenance command. These checks keep its
recorded evidence aligned with defaults and exercise download failure reporting.
"""

import json
from pathlib import Path
import runpy

import pytest

from gaiascapes_host.config import default_frog_locations
from gaiascapes_host.xeno_canto import NoRecordingsError, _within_region


ROOT = Path(__file__).parents[1]


def test_default_frog_regions_have_downloaded_samples_in_the_audit_report():
    report = json.loads((ROOT / 'docs/frog-locations-audit.json').read_text())
    assert [row['location'] for row in report['locations']] == default_frog_locations()
    for row in report['locations']:
        assert row['status'] == 'verified'
        assert row['eligible_matches'] > 0
        assert row['sample']['download_bytes'] > 0
        assert _within_region(row['sample'], row['location'])
        assert row['sample']['source_url'] == f"https://xeno-canto.org/{row['sample']['id']}"


@pytest.mark.parametrize('failure,status', [('empty', 'empty'), ('network', 'error'),
                                           ('download', 'error'), (None, 'verified')])
def test_audit_distinguishes_empty_catalogs_from_failed_requests(tmp_path, failure, status):
    audit = runpy.run_path(str(ROOT / 'scripts/audit_frog_locations.py'))['audit_locations']
    sample = dict(id='42', extension='.mp3', source_url='https://xeno-canto.org/42',
                  latitude=1, longitude=2, license='CC BY 4.0')

    class Client:
        media_dir = tmp_path

        def _catalog(self, name, location):
            if failure == 'empty':
                raise NoRecordingsError('No frogs')
            if failure == 'network':
                raise RuntimeError('Request failed')
            return [sample]

        def _download(self, record, destination):
            if failure == 'download':
                raise RuntimeError('Download failed')
            destination.write_bytes(b'ID3-sample')

    result = audit(Client(), [dict(name='Wetland', latitude=1, longitude=2)])[0]
    assert result['status'] == status
    if status == 'verified':
        assert result['sample']['download_bytes'] == 10
    else:
        assert 'sample' not in result
