"""Build offline terrain images in the browser's two map projections.

Run with the public-domain Natural Earth NE1_50M_SR_W.zip archive as the
argument. Pillow and NumPy are build-time tools only; the host serves PNGs.
Projection dimensions and Robinson tables match static/app.js so terrain,
coordinate picking, and event markers share the same geographic positions.
"""

import argparse
from pathlib import Path
import re
import zipfile

import numpy as np
from PIL import Image, ImageEnhance


def build_terrain(archive: Path) -> None:
    """Project Natural Earth land cover, relief, and bathymetry into PNGs."""
    static = Path(__file__).resolve().parents[1] / "src/gaiascapes_host/static"
    javascript = (static / "app.js").read_text()
    tables = {
        axis: np.array([float(value) for value in re.search(
            rf"const ROBINSON_{axis} = \[(.*?)\]", javascript
        ).group(1).split(",")])
        for axis in ("X", "Y")
    }
    with zipfile.ZipFile(archive) as source:
        name = next(name for name in source.namelist() if name.endswith(".tif"))
        with Image.open(source.open(name)) as original:
            image = original.convert("RGB").resize((3600, 1800), Image.Resampling.LANCZOS)
    image = ImageEnhance.Color(image).enhance(1.25)
    pixels = np.asarray(image)
    # Pixel centers in SVG coordinates; both images cover x=69..955, y=222..802.
    x, y = np.meshgrid(69 + (np.arange(1772) + .5) / 2,
                       222 + (np.arange(1160) + .5) / 2)
    for model in ("robinson", "eckert_iv"):
        if model == "robinson":
            vertical = (512 - y) / 290
            latitude = np.sign(vertical) * np.interp(
                np.abs(vertical), tables["Y"], np.arange(0, 91, 5)
            )
            half_width = 443 * np.interp(np.abs(latitude), np.arange(0, 91, 5), tables["X"])
        else:
            vertical = (512 - y) / 221.5
            theta = np.arcsin(np.clip(vertical, -1, 1))
            latitude = np.degrees(np.arcsin(np.clip(
                (theta + np.sin(theta) * (np.cos(theta) + 2)) / (2 + np.pi / 2), -1, 1
            )))
            half_width = 443 * (1 + np.cos(theta)) / 2
        longitude = (x - 512) / half_width * 180
        visible = (np.abs(vertical) <= 1) & (np.abs(longitude) <= 180)
        source_x = np.clip((longitude + 180) / 360 * 3600 - .5, 0, 3599)
        source_y = np.clip((90 - latitude) / 180 * 1800 - .5, 0, 1799)
        left, top = source_x.astype(int), source_y.astype(int)
        right, bottom = np.minimum(left + 1, 3599), np.minimum(top + 1, 1799)
        dx, dy = (source_x - left)[..., None], (source_y - top)[..., None]
        colors = ((pixels[top, left] * (1 - dx) + pixels[top, right] * dx) * (1 - dy)
                  + (pixels[bottom, left] * (1 - dx) + pixels[bottom, right] * dx) * dy)
        result = np.zeros((*visible.shape, 4), dtype=np.uint8)
        result[..., :3] = np.where(visible[..., None], colors, 0).astype(np.uint8)
        result[..., 3] = visible * 255
        Image.fromarray(result).save(static / f"world-terrain-{model}.png", optimize=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    build_terrain(parser.parse_args().archive)
