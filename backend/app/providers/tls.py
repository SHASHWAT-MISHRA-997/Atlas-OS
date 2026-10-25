"""One TLS context for all outbound calls.

Building an httpx client loads the CA bundle each time (about 50 ms on a 4-core Linux machine,
measured in docs/RESEARCH.md), which added that delay to every chat request. The context is
built once and reused; each request still gets its own client, so Stop closes only that call.
"""
from __future__ import annotations

import functools
import os
import ssl

import certifi


@functools.cache
def tls_context() -> ssl.SSLContext:
    # Honour SSL_CERT_FILE like httpx does by default (e.g. a corporate proxy's CA).
    return ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or certifi.where())
