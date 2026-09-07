# Security policy

Security fixes target the latest source revision. Update before reporting an
issue and reproduce it with a temporary data directory and synthetic credentials.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/mot-yelraf/Gaiascapes/security/advisories/new)
when it is available. If that route is unavailable, contact the maintainer
privately using the email listed in [Code of Conduct](CODE_OF_CONDUCT.md#enforcement).
Do not open a public issue containing credentials, private configuration, or an
unfixed exploit. Include the version, platform, impact, and reproduction steps
with fake keys. No response-time guarantee is offered.

## Intended deployment

The app is designed for a trusted host and LAN. HTTP port 8768 intentionally
allows unauthenticated browsing, listening, and settings changes from LAN
devices. This is not an internet-facing or multi-user access-control service.
See [Privacy](PRIVACY.md) for credential storage, geolocation, and network behavior.

CI checks for known dependency advisories and committed secrets. These checks
cannot guarantee that the software or its history is free of vulnerabilities.
If a real credential is committed, revoke or rotate it before discussing any
history cleanup; deleting the latest copy does not remove earlier commits.
