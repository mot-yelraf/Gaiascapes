"""Verify default frog regions against Xeno-canto and download a sample from each.

This maintenance command uses the runtime search and eligibility rules. It reads
only the API key from the supplied configuration and keeps catalogs and audio in
temporary storage; the output report contains public metadata, never credentials.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from gaiascapes_host.config import default_frog_locations
from gaiascapes_host.xeno_canto import NoRecordingsError, REGION_RADIUS_KM, XenoCantoClient


def audit_locations(client, locations):
    """Report eligible matches and one successfully downloaded sample per region."""
    results = []
    for location in locations:
        result = {"location": location}
        try:
            records = client._catalog(location["name"], location)
            result["eligible_matches"] = len(records)
            for record in records:
                destination = client.media_dir / f"XC{record['id']}{record['extension']}"
                try:
                    client._download(record, destination)
                except RuntimeError:
                    continue
                result["sample"] = {
                    key: record[key] for key in (
                        "id", "source_url", "latitude", "longitude", "license",
                    )
                }
                result["sample"]["download_bytes"] = destination.stat().st_size
                result["status"] = "verified"
                break
            else:
                result.update(status="error", error="No eligible sample could be downloaded")
        except NoRecordingsError:
            result.update(status="empty", eligible_matches=0)
        except RuntimeError as exc:
            result.update(status="error", error=str(exc))
        results.append(result)
        print(f"{location['name']}: {result['status']}", flush=True)
    return results


def main():
    """Audit defaults with fresh temporary caches and write a public JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve() == args.config.resolve():
        parser.error("The report must not overwrite the configuration")
    key = json.loads(args.config.read_text(encoding="utf-8")).get("xeno_canto_api_key")
    if not key:
        parser.error("The supplied configuration has no Xeno-canto API key")
    with tempfile.TemporaryDirectory(prefix="gaiascapes-frog-audit-") as temporary:
        os.environ["GAIA_SCAPE_DATA_DIR"] = temporary
        client = XenoCantoClient(Path(temporary), key, group="frogs")
        results = audit_locations(client, default_frog_locations())
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "radius_km": REGION_RADIUS_KM,
        "locations": results,
    }
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if all(result["status"] == "verified" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
