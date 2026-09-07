# Privacy

Gaiascapes runs on your host and stores its settings and history locally. It
has no application analytics or advertising telemetry. It contacts external
services to fetch the environmental observations and recordings you enable.

## Network access

LAN access is enabled on HTTP port 8768. Other devices that can reach this port
can browse, listen, read non-secret settings and history, and change settings.
There is no login or HTTPS in the application. Credential entry from a LAN
browser travels over HTTP. Use a trusted network; do not forward this port to
the public internet. For host-only use, set `GAIA_SCAPE_HTTP_HOST=127.0.0.1`
for the launching process.

IP-based host location is enabled by default. Starting the application or opening the UI can contact
`ipapi.co`, with `ipwho.is` as a fallback. These providers see the host’s public
IP address. The approximate location is cached in memory and shown to connected
browsers. At startup, its name and coordinates become the first sampling center
for Xeno-canto Birdsong, Frog Calls, and Storm Outlook. These three locations
are saved in `data/config.json` and sent to enabled sound/forecast providers
as sampling coordinates. They refresh when the application restarts and a new
lookup succeeds. Commons Birdsong retains its fixed recording catalog.
Turn off **Show this host’s approximate location on the map** under
**Settings → Sound Choices** to stop future lookups. Already-started requests
may finish; no new location result is returned while the option is disabled.
A browser that already displayed the marker may need to refresh. Disabling
lookups leaves previously saved sampling centers in place; edit them in Sound
locations if you want to replace them.

Enabled data sources contact USGS, NOAA/Amazon S3, Open-Meteo, EUMETSAT,
Wikimedia Commons, Xeno-canto, and NOAA recording storage as applicable.
Providers see the requesting host’s IP and requested products or locations.
EUMETSAT and Xeno-canto receive their respective credentials over HTTPS.
Downloaded recordings may use provider-supplied storage/CDN hosts. Links to
recording attribution pages contact those sites when opened.
[Third-party notices](THIRD_PARTY_NOTICES.md) describe the sources and their terms.

## Local storage

The installation’s `data/config.json` stores settings and provider credentials
as plaintext JSON with owner-only permissions when saved by the app. Credentials
are omitted from normal configuration API responses and credential input fields.
Protect this file and its backups; do not attach it to public bug reports.

The `data/` directory also contains SQLite event history, cached recordings and
catalogs, audio-device selections, and installation source/mode records. Logs
may be stored in the installation or its data directory. Configured sampling
locations and provider observations are not a log of a listener’s movements.
Browsers retain interface preferences in local browser storage.

Uninstalling preserves `data/` by default. `GAIA_SCAPE_REMOVE_DATA=yes` removes
that installation’s application data during uninstall. Backups, browser storage,
and data already received by external services are not deleted by uninstalling.
