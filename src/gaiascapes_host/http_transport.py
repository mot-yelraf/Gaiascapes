"""HTTP connections that prefer IPv4 and bound individual connection attempts.

Provider requests retain urllib proxy handling, HTTPS certificate verification,
redirects, and response timeouts. Address selection is scoped to these connections
so a broken IPv6 route cannot delay a reachable IPv4 provider.
"""

from __future__ import annotations

import http.client
import socket
import urllib.request


def _connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    addresses = socket.getaddrinfo(*address, type=socket.SOCK_STREAM)
    addresses.sort(key=lambda item: item[0] != socket.AF_INET)
    error = None
    for family, kind, protocol, _name, endpoint in addresses:
        connection = socket.socket(family, kind, protocol)
        try:
            connection.settimeout(min(timeout, 5) if isinstance(timeout, (int, float)) else 5)
            if source_address:
                connection.bind(source_address)
            connection.connect(endpoint)
            connection.settimeout(timeout if isinstance(timeout, (int, float)) else None)
            return connection
        except OSError as exc:
            error = exc
            connection.close()
    raise error or OSError("No addresses found for HTTP connection")


class _HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        return self.do_open(_HTTPSConnection, request, context=self._context)


class _HTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, request):
        return self.do_open(_HTTPConnection, request)


def build_opener():
    """Build a standard urllib opener with bounded IPv4-first connections."""
    return urllib.request.build_opener(_HTTPHandler(), _HTTPSHandler())


def open_url(request, timeout=20):
    """Open a URL without allowing stalled IPv6 to delay working IPv4."""
    return build_opener().open(request, timeout=timeout)
