# Third-Party and Data Notices

Gaiascapes source code is distributed under the BSD 2-Clause License in
`LICENSE`. Third-party software, platform components, services, and data remain
subject to their own licenses and terms. The Gaiascapes license does not replace
those terms.

## Python dependencies

Gaiascapes declares its direct runtime dependencies in `pyproject.toml` and
mirrors them in `requirements.txt`:

| Package | Purpose | License |
| --- | --- | --- |
| EUMDAC | EUMETSAT Data Store access | MIT |
| FastAPI | HTTP application and API routing | MIT |
| Uvicorn | ASGI server | BSD-3-Clause |
| Jinja2 | HTML template rendering | BSD-3-Clause |
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

Gaiascapes can send OSC cues to SuperCollider for audio synthesis. SuperCollider
is optional, is not bundled in this repository, and is licensed separately under
GPL-3.0-or-later. See:

<https://github.com/supercollider/supercollider>

The Gaiascapes service, event history, and web UI continue to operate without
SuperCollider. A system package, application bundle, or other redistributed
SuperCollider binary must retain the notices and corresponding source offer
required by its distributor and license.

## Desktop platform components

pywebview uses web-view components supplied by the host platform. On Linux and
Raspberry Pi OS these commonly include GTK 3, WebKitGTK, and PyGObject; macOS
uses the operating system's web-view framework. Gaiascapes does not relicense
these components. System packages and operating-system frameworks remain under
their respective distribution terms.

## USGS earthquake data

Gaiascapes retrieves the U.S. Geological Survey Earthquake Hazards Program's
GeoJSON summary feed and adapts selected event fields into normalized Gaia
events. USGS earthquake data and products are public-domain U.S. government
material unless a particular item says otherwise.

- Feed information: <https://earthquake.usgs.gov/earthquakes/feed/>
- ANSS data and products policy:
  <https://www.usgs.gov/media/files/anss-data-and-products-policy>

Credit: U.S. Geological Survey, Earthquake Hazards Program. Use of USGS names
or data does not imply USGS endorsement of Gaiascapes.

## NOAA GOES GLM lightning data

Gaiascapes retrieves NOAA GOES-East and GOES-West Geostationary Lightning
Mapper Level 2 LCFA products from NOAA's public object-storage buckets. It
normalizes quality-accepted flashes and may store or sonify a sampled subset.

NOAA-produced data are public-domain U.S. government material unless marked
otherwise. NOAA requests acknowledgement as the source and prohibits use that
implies endorsement or presents modified material as an official NOAA product.

- GOES data access: <https://www.noaa.gov/information-technology/open-data-dissemination>
- NOAA copyright guidance: <https://sos.noaa.gov/copyright/>

Credit: NOAA/NESDIS GOES-R Series Geostationary Lightning Mapper. Gaiascapes's
normalization, filtering, sampling, visualization, and sonification are not
official NOAA products.

## EUMETSAT MTG Lightning Imager data

Gaiascapes can retrieve the EUMETSAT Meteosat Third Generation Lightning
Imager Level 2 Lightning Flashes collection through the user-authenticated Data
Store. The source normalizes and samples the observations for local display,
storage, and sonification.

The collection is offered as free and unrestricted data under Creative Commons
Attribution 4.0 (CC BY 4.0):

- Collection: <https://user.eumetsat.int/catalogue/EO%3AEUM%3ADAT%3A0691>
- EUMETSAT data access: <https://user.eumetsat.int/data-access/data-store>
- CC BY 4.0: <https://creativecommons.org/licenses/by/4.0/>

Credit: Contains modified EUMETSAT Meteosat Third Generation Lightning Imager
data. Gaiascapes is not an official EUMETSAT product and is not endorsed by
EUMETSAT.

## Open-Meteo forecast and marine data

Gaiascapes retrieves modeled weather and marine data from the Open-Meteo
Forecast and Marine APIs. Open-Meteo API data are offered under the Creative
Commons Attribution 4.0 International license (CC BY 4.0):

- Open-Meteo license and model-source details: <https://open-meteo.com/en/license>
- CC BY 4.0: <https://creativecommons.org/licenses/by/4.0/>

Attribution: Contains adapted data from Open-Meteo and its contributing
national weather services. Gaiascapes selects locations and variables, derives
normalized swell, tide-turn, and storm-potential events, and transforms those
events into visual and musical output. These adaptations are not endorsed by
Open-Meteo or its contributing model providers.

Open-Meteo marine and forecast values are model output. They are not observed
lightning strikes and are not suitable for navigation. Individual upstream
datasets named on the Open-Meteo license page may carry additional attribution
or source terms that remain applicable.

## Wikimedia Commons birdsong

Gaiascapes can resolve and locally cache birdsong recordings from Wikimedia
Commons through its keyless public API. The recordings are downloaded at runtime
and are not bundled with Gaiascapes. Each recording remains under the license shown
on its Commons file page; Gaiascapes accepts only public-domain, CC0, CC BY, and
CC BY-SA files and displays the creator, license, and source link in the interface.

Xeno-canto Birdsong and Frog Calls accept CC BY, CC BY-SA, and CC BY-NC-SA
recordings. Each recording retains its creator credit, license link, and
Xeno-canto source link in the existing attribution display. CC BY-NC-SA audio
is for noncommercial use; shared adaptations must meet its ShareAlike terms.
These recording licenses are separate from the application's BSD-2-Clause license.
See <https://creativecommons.org/licenses/by-nc-sa/4.0/>.

Redistributors remain responsible for preserving each recording's attribution and
license information and for satisfying any share-alike terms that apply to the
recording itself.

- Commons reuse guidance: <https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia>
- MediaWiki API etiquette: <https://www.mediawiki.org/wiki/API:Etiquette>

## Approximate system location

Gaiascapes requests an approximate location for the host's public IP from
`ipapi.co`, with `ipwho.is` as an HTTPS fallback. The normalized city,
coordinates, and timezone are held only in process memory; Gaiascapes does not
store the IP address returned by either provider. Their respective terms and
privacy policies apply to these requests.

## Natural Earth map data

The world coastline geometry embedded in `assets/gaia-scape-icon.svg` and
`src/gaiascapes_host/static/gaia-scape-icon.svg` is adapted from Natural Earth
1:110m vector data and projected to Robinson coordinates. Natural Earth states
that all of its raster and vector map data are in the public domain:

<https://www.naturalearthdata.com/about/terms-of-use/>

Credit: Made with Natural Earth. The geometry has been transformed and styled
for Gaiascapes; Natural Earth does not warrant its accuracy or endorse this
project.

## Gaiascapes visual and audio assets

Except for the Natural Earth geometry identified above, Gaiascapes's icons,
styles, templates, and SuperCollider synth definitions are project assets
distributed under the repository's `LICENSE`. The PNG and ICO desktop icons are
derived from the Gaiascapes SVG artwork.

No remote data provider, dependency author, model contributor, or platform
vendor endorses Gaiascapes. Provider data can be delayed, incomplete, revised,
or unavailable and should not be relied upon for emergency response, safety,
marine navigation, or other high-stakes decisions.
