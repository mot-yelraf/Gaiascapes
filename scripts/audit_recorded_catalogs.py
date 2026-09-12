"""Verify coverage and rotating samples for every default recording catalog.

The maintenance command uses the production clients in an isolated temporary
data directory. Reports contain public attribution and recording coordinates;
only the Xeno-canto key is read from the optional installed configuration.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.request

from gaiascapes_host.commons_birdsong import COMMONS_CATALOG, CommonsBirdsongClient
from gaiascapes_host.config import default_birdsong_locations, default_frog_locations
from gaiascapes_host.sanctsound import MARINE_KINDS, SanctSoundClient, available_locations
from gaiascapes_host.xeno_canto import XenoCantoClient


def audit_catalog(client, locations, counts, *, samples=2):
    """Visit all sites before sampling their next distinct available recording."""
    results = [dict(location, eligible_recordings=count, samples=[], errors=[])
               for location, count in zip(locations, counts)]
    for cycle in range(samples):
        for index, row in enumerate(results):
            if cycle >= row["eligible_recordings"]:
                continue
            try:
                event = client.event_at(index + cycle * len(locations))
                traits = event.traits
                row["samples"].append({
                    "recording_id": traits.get("recording_id", str(traits.get("commons_page_id", ""))),
                    "title": traits["title"], "source_url": traits["source_url"],
                    "creator": traits["creator"], "license": traits["license"],
                    "latitude": event.latitude, "longitude": event.longitude,
                })
            except (RuntimeError, OSError, ValueError) as exc:
                row["errors"].append(str(exc))
            print(f"{client.__class__.__name__}: {row['name']}, pass {cycle + 1}", flush=True)
    for row in results:
        identities = {sample["recording_id"] for sample in row["samples"]}
        expected = min(samples, row["eligible_recordings"])
        if row["errors"] or not expected or len(identities) != expected:
            row["status"] = "error"
        else:
            row["status"] = "multiple" if row["eligible_recordings"] > 1 else "single"
    return results


def main():
    """Write a fresh source audit without modifying installed settings or media."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Read only the Xeno-canto key from this configuration")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=2, help="Recordings to download per location")
    parser.add_argument("--catalog", action="append", choices=("commons", "whales", "dolphins", "birds", "frogs"),
                        help="Audit only the named catalog; repeat to select several")
    parser.add_argument("--request-interval", type=float, default=3.0, help="Minimum seconds between source requests")
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    if args.request_interval < 0:
        parser.error("--request-interval must not be negative")
    if args.config and args.output.resolve() == args.config.resolve():
        parser.error("The report must not overwrite the configuration")
    key = json.loads(args.config.read_text()).get("xeno_canto_api_key", "") if args.config else ""
    catalogs = []
    selected = set(args.catalog or ("commons", "whales", "dolphins", "birds", "frogs"))
    last_request = 0.0

    def opener(request, timeout):
        nonlocal last_request
        time.sleep(max(0, args.request_interval - (time.monotonic() - last_request)))
        last_request = time.monotonic()
        return urllib.request.urlopen(request, timeout=timeout)

    with tempfile.TemporaryDirectory(prefix="gaiascapes-recording-audit-") as temporary:
        os.environ["GAIA_SCAPE_DATA_DIR"] = temporary
        data_dir = Path(temporary)
        if "commons" in selected:
            client = CommonsBirdsongClient(data_dir, opener=opener)
            locations = [{key: location[key] for key in ("id", "name", "latitude", "longitude")}
                         for location in COMMONS_CATALOG]
            catalogs.append({"kind": "birdsong", "provider": "wikimedia_commons", "locations": audit_catalog(
                client, locations, [len(location["recordings"]) for location in COMMONS_CATALOG], samples=args.samples)})
        for kind in MARINE_KINDS:
            if ("whales" if kind == "whale_song" else "dolphins") not in selected:
                continue
            client = SanctSoundClient(data_dir, kind, opener=opener)
            locations = available_locations(kind)
            catalogs.append({"kind": kind, "provider": "marine_archives", "locations": audit_catalog(
                client, locations, [location["recording_count"] for location in locations], samples=args.samples)})
        for group, defaults in (("birds", default_birdsong_locations), ("frogs", default_frog_locations)):
            if group not in selected:
                continue
            locations = defaults()
            client = XenoCantoClient(data_dir, key, opener=opener, locations=locations, group=group)
            counts = []
            errors = {}
            for index, location in enumerate(locations):
                try:
                    if not key:
                        raise RuntimeError("No Xeno-canto key supplied for this audit")
                    counts.append(len(client._catalog(location["name"], location)))
                except (RuntimeError, OSError, ValueError) as exc:
                    counts.append(0)
                    errors[index] = str(exc)
            rows = audit_catalog(client, locations, counts, samples=args.samples)
            for index, error in errors.items():
                rows[index]["errors"].append(error)
            catalogs.append({"kind": client.kind, "provider": "xeno_canto", "locations": rows})
    for catalog in catalogs:
        catalog["location_count"] = len(catalog["locations"])
        catalog["single_recording_locations"] = [row["name"] for row in catalog["locations"] if row["status"] == "single"]
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "target_locations": 19,
              "samples_per_location": args.samples, "catalogs": catalogs}
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0 if all(catalog["location_count"] == 19 and all(row["status"] != "error" for row in catalog["locations"])
                    for catalog in catalogs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
