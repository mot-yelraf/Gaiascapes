"""Build the offline terrain and town assets for the map magnifier.

Use the Natural Earth NE1_LR_LC_SR_W and populated places simple ZIP archives.
Pillow and pyshp are build-time dependencies only.
"""

import argparse
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile

from PIL import Image
import shapefile


def build_magnifier(terrain_archive: Path, places_archive: Path, destination: Path) -> None:
    """Write aligned 45-degree terrain tiles and sorted place labels."""
    destination.mkdir(parents=True, exist_ok=True)
    tile_size = 1350
    with ZipFile(terrain_archive) as archive, tempfile.TemporaryDirectory() as working_dir:
        name = next(name for name in archive.namelist() if name.lower().endswith(".tif"))
        with Image.open(archive.extract(name, working_dir)) as original:
            terrain = original.convert("RGB").resize(
                (8 * tile_size, 4 * tile_size), Image.Resampling.LANCZOS
            )
    for row in range(4):
        for column in range(8):
            bounds = (column * tile_size, row * tile_size,
                      (column + 1) * tile_size, (row + 1) * tile_size)
            terrain.crop(bounds).save(destination / f"terrain-{row}-{column}.jpg",
                                      quality=78, optimize=True)

    with ZipFile(places_archive) as archive:
        stem = next(name.removesuffix(".shp") for name in archive.namelist() if name.endswith(".shp"))
        with shapefile.Reader(shp=archive.open(f"{stem}.shp"), dbf=archive.open(f"{stem}.dbf"),
                              shx=archive.open(f"{stem}.shx")) as source:
            places = []
            for entry in source.iterShapeRecords():
                name = entry.record.name
                if name:
                    longitude, latitude = entry.shape.points[0]
                    places.append((entry.record.scalerank, -entry.record.pop_max, name,
                                   round(latitude, 5), round(longitude, 5)))
    labels = [place[2:] for place in sorted(places)]
    (destination / "places.json").write_text(
        json.dumps(labels, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("terrain", type=Path)
    parser.add_argument("places", type=Path)
    args = parser.parse_args()
    static = Path(__file__).resolve().parents[1] / "src/gaiascapes_host/static"
    build_magnifier(args.terrain, args.places, static / "map-magnifier")
