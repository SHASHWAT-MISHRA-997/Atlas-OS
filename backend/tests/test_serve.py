"""The `python -m app.serve` launcher, including a real HTTPS start-up."""
import os
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from app.serve import ServeError, build_config, warnings_for

BACKEND = Path(__file__).resolve().parents[1]


def test_defaults_listen_on_this_computer_only():
    assert build_config({}) == {"host": "127.0.0.1", "port": 8000}
    assert warnings_for(build_config({})) == []


def test_tls_needs_both_files(tmp_path):
    cert = tmp_path / "c.pem"
    cert.write_text("x")
    with pytest.raises(ServeError, match="both"):
        build_config({"ATLAS_TLS_CERT": str(cert)})
    with pytest.raises(ServeError, match="not found"):
        build_config({"ATLAS_TLS_CERT": str(cert), "ATLAS_TLS_KEY": str(tmp_path / "missing.pem")})


def test_bad_port_is_rejected():
    for value in ("abc", "0", "70000"):
        with pytest.raises(ServeError):
            build_config({"ATLAS_PORT": value})


def test_network_listening_without_tls_warns():
    assert warnings_for(build_config({"ATLAS_HOST": "192.168.1.5"}))


def _self_signed(tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    result = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
                             "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1", "-keyout", str(key), "-out", str(cert)],
                            capture_output=True)
    if result.returncode != 0:
        pytest.skip("openssl is not available")
    return cert, key


def test_serves_https_with_the_given_certificate(tmp_path):
    cert, key = _self_signed(tmp_path)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "ATLAS_PORT": str(port), "ATLAS_TLS_CERT": str(cert), "ATLAS_TLS_KEY": str(key),
           "ATLAS_DATA_DIR": str(tmp_path / "data"), "PYTHONPATH": str(BACKEND)}
    proc = subprocess.Popen([sys.executable, "-m", "app.serve"], cwd=BACKEND, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        context = ssl.create_default_context(cafile=str(cert))
        for _ in range(100):
            try:
                r = httpx.get(f"https://localhost:{port}/health", verify=context)
                break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            pytest.fail("ATLAS did not start over HTTPS")
        assert r.status_code == 200
        with pytest.raises(httpx.HTTPError):
            httpx.get(f"http://localhost:{port}/health")  # plain HTTP is not served on the TLS port
    finally:
        proc.terminate()
        proc.wait(10)
