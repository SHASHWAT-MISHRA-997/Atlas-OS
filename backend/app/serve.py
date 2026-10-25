"""Start ATLAS: `python -m app.serve` from the backend directory.

Same as `uvicorn app.main:app`, plus optional HTTPS. Settings come from the environment:

  ATLAS_HOST       address to listen on (default 127.0.0.1: this computer only)
  ATLAS_PORT       port (default 8000)
  ATLAS_TLS_CERT   certificate file (PEM) } both or neither; with them ATLAS speaks HTTPS
  ATLAS_TLS_KEY    private key file (PEM)  }

For phones outside your home network, prefer a private network such as Tailscale over
opening a port on your router; see docs/REMOTE_ACCESS.md.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


class ServeError(Exception):
    pass


def build_config(env: dict[str, str] | None = None) -> dict:
    env = os.environ if env is None else env
    host = (env.get("ATLAS_HOST") or "127.0.0.1").strip()
    try:
        port = int(env.get("ATLAS_PORT") or 8000)
    except ValueError:
        raise ServeError("ATLAS_PORT must be a number.") from None
    if not 1 <= port <= 65535:
        raise ServeError("ATLAS_PORT must be between 1 and 65535.")
    cert, key = (env.get("ATLAS_TLS_CERT") or "").strip(), (env.get("ATLAS_TLS_KEY") or "").strip()
    config = {"host": host, "port": port}
    if cert or key:
        if not (cert and key):
            raise ServeError("Set both ATLAS_TLS_CERT and ATLAS_TLS_KEY, or neither.")
        for name, path in (("ATLAS_TLS_CERT", cert), ("ATLAS_TLS_KEY", key)):
            if not Path(path).is_file():
                raise ServeError(f"{name} file not found: {path}")
        config.update(ssl_certfile=cert, ssl_keyfile=key)
    return config


def warnings_for(config: dict) -> list[str]:
    notes = []
    if config["host"] not in ("127.0.0.1", "::1", "localhost") and "ssl_certfile" not in config:
        notes.append("Listening on the network without HTTPS: traffic (including login cookies) is readable "
                     "by others on the same Wi-Fi. Use only on a network you trust.")
    return notes


def main() -> int:
    try:
        config = build_config()
    except ServeError as exc:
        print(f"ATLAS: {exc}", file=sys.stderr)
        return 2
    for note in warnings_for(config):
        print(f"ATLAS warning: {note}", file=sys.stderr)
    import uvicorn

    scheme = "https" if "ssl_certfile" in config else "http"
    print(f"ATLAS: starting on {scheme}://{config['host']}:{config['port']}", file=sys.stderr)
    uvicorn.run("app.main:app", **config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
