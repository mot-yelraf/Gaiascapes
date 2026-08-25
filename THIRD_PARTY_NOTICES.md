# Third-Party and Data Notices

Gaia Scape source code is distributed under the BSD 2-Clause License in
`LICENSE`. Third-party software, platform components, services, and data remain
subject to their own licenses and terms. The Gaia Scape license does not replace
those terms.

## Python dependencies

Gaia Scape declares its direct runtime dependencies in `pyproject.toml` and
mirrors them in `requirements.txt`:

| Package | Purpose | License |
| --- | --- | --- |
| FastAPI | HTTP application and API routing | MIT |
| Uvicorn | ASGI server | BSD-3-Clause |
| Jinja2 | HTML template rendering | BSD-3-Clause |
| Astral | Solar and lunar calculations | Apache-2.0 |
| netCDF4 | NOAA GLM NetCDF parsing | MIT |
| pywebview | Native desktop web-view window | BSD-3-Clause |

The optional development dependencies are HTTPX (BSD-3-Clause) and pytest
(MIT). These packages may install transitive Python packages and native
libraries, each governed by its own license. Preserve the license metadata and
notices supplied with installed packages when redistributing an assembled Gaia
Scape runtime.

Package versions and dependency relationships can change within the ranges in
`pyproject.toml`; the metadata installed with each distribution is the
authoritative notice for that version.

## SuperCollider

Gaia Scape can send OSC cues to SuperCollider for audio synthesis. SuperCollider
is optional, is not bundled in this repository, and is licensed separately under
GPL-3.0-or-later. See:

<https://github.com/supercollider/supercollider>

The Gaia Scape service, event history, and web UI continue to operate without
SuperCollider. A system package, application bundle, or other redistributed
SuperCollider binary must retain the notices and corresponding source offer
required by its distributor and license.

## Desktop platform components

pywebview uses web-view components supplied by the host platform. On Linux and
Raspberry Pi OS these commonly include GTK 3, WebKitGTK, and PyGObject; macOS
uses the operating system's web-view framework. Gaia Scape does not relicense
these components. System packages and operating-system frameworks remain under
their respective distribution terms.

## USGS earthquake data

Gaia Scape retrieves the U.S. Geological Survey Earthquake Hazards Program's
GeoJSON summary feed and adapts selected event fields into normalized Gaia
events. USGS earthquake data and products are public-domain U.S. government
material unless a particular item says otherwise.

- Feed information: <https://earthquake.usgs.gov/earthquakes/feed/>
- ANSS data and products policy:
  <https://www.usgs.gov/media/files/anss-data-and-products-policy>

Credit: U.S. Geological Survey, Earthquake Hazards Program. Use of USGS names
or data does not imply USGS endorsement of Gaia Scape.

## NOAA GOES GLM lightning data

Gaia Scape retrieves NOAA GOES-East and GOES-West Geostationary Lightning
Mapper Level 2 LCFA products from NOAA's public object-storage buckets. It
normalizes quality-accepted flashes and may store or sonify a sampled subset.

NOAA-produced data are public-domain U.S. government material unless marked
otherwise. NOAA requests acknowledgement as the source and prohibits use that
implies endorsement or presents modified material as an official NOAA product.

- GOES data access: <https://www.noaa.gov/information-technology/open-data-dissemination>
- NOAA copyright guidance: <https://sos.noaa.gov/copyright/>

Credit: NOAA/NESDIS GOES-R Series Geostationary Lightning Mapper. Gaia Scape's
normalization, filtering, sampling, visualization, and sonification are not
official NOAA products.

## Open-Meteo forecast and marine data

Gaia Scape retrieves modeled weather and marine data from the Open-Meteo
Forecast and Marine APIs. Open-Meteo API data are offered under the Creative
Commons Attribution 4.0 International license (CC BY 4.0):

- Open-Meteo license and model-source details: <https://open-meteo.com/en/license>
- CC BY 4.0: <https://creativecommons.org/licenses/by/4.0/>

Attribution: Contains adapted data from Open-Meteo and its contributing
national weather services. Gaia Scape selects locations and variables, derives
normalized swell, tide-turn, and storm-potential events, and transforms those
events into visual and musical output. These adaptations are not endorsed by
Open-Meteo or its contributing model providers.

Open-Meteo marine and forecast values are model output. They are not observed
lightning strikes and are not suitable for navigation. Individual upstream
datasets named on the Open-Meteo license page may carry additional attribution
or source terms that remain applicable.

## Natural Earth map data

The world coastline geometry embedded in `assets/gaia-scape-icon.svg` and
`src/gaia_scape_host/static/gaia-scape-icon.svg` is adapted from Natural Earth
1:110m vector data and projected to Robinson coordinates. Natural Earth states
that all of its raster and vector map data are in the public domain:

<https://www.naturalearthdata.com/about/terms-of-use/>

Credit: Made with Natural Earth. The geometry has been transformed and styled
for Gaia Scape; Natural Earth does not warrant its accuracy or endorse this
project.

## Gaia Scape visual and audio assets

Except for the Natural Earth geometry identified above, Gaia Scape's icons,
styles, templates, and SuperCollider synth definitions are project assets
distributed under the repository's `LICENSE`. The PNG and ICO desktop icons are
derived from the Gaia Scape SVG artwork.

No remote data provider, dependency author, model contributor, or platform
vendor endorses Gaia Scape. Provider data can be delayed, incomplete, revised,
or unavailable and should not be relied upon for emergency response, safety,
marine navigation, or other high-stakes decisions.
