"""Check browser map projection geometry independently of the DOM.

Round trips protect map picking, and numerical area checks protect Eckert IV's
relative-area behavior across latitudes without adding a mapping dependency.
"""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_projection_round_trips_boundaries_and_equal_area():
    """Keep map picking accurate and Eckert IV equal-area at its native aspect."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to check browser projection geometry")
    source = Path(__file__).parents[1] / "src/gaiascapes_host/static/app.js"
    script = r'''
const fs = require("fs");
const vm = require("vm");
const assert = require("assert/strict");
const source = fs.readFileSync(process.argv[1], "utf8");
const context = vm.createContext({byId: () => ({value: "robinson"}), assert});
vm.runInContext(source.slice(source.indexOf("let mapProjection ="), source.indexOf("function mapMarkerTitle")), context);
vm.runInContext(`
  for (const model of ["robinson", "eckert_iv"]) {
    mapProjection = model;
    for (const latitude of [-90, -89.99, -80, -60, -30, 0, 30, 60, 80, 89.99, 90]) {
      for (const longitude of [-180, -120, -45, 0, 45, 120, 180]) {
        const point = projectCoordinates(longitude, latitude);
        const inverse = inverseProjectCoordinates(point.x, point.y);
        assert(Math.abs(inverse.latitude - latitude) < 1e-5);
        assert(Math.abs(inverse.longitude - longitude) < 1e-5);
      }
    }
    assert(mapContainsPoint(512, 512));
    assert(!mapContainsPoint(956, 512));
    assert(!mapContainsPoint(512, 200));
    assert.equal(projectCoordinates(180, 0).x, 955);
  }
  assert.equal(projectCoordinates(180, 90).x, 733.5);
  assert.equal(projectCoordinates(0, 90).y, 290.5);
  const areaScale = (latitude) => {
    const delta = 0.0001;
    const west = projectCoordinates(-delta, latitude);
    const east = projectCoordinates(delta, latitude);
    const north = projectCoordinates(0, latitude + delta);
    const south = projectCoordinates(0, latitude - delta);
    return (east.x - west.x) * (south.y - north.y) / Math.cos(latitude * Math.PI / 180);
  };
  const equatorialArea = areaScale(0);
  for (const latitude of [-80, -60, -30, 30, 60, 80]) {
    assert(Math.abs(areaScale(latitude) / equatorialArea - 1) < 1e-6);
  }
`, context);
'''
    subprocess.run([node, "-e", script, str(source)], check=True)
