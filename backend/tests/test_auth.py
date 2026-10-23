"""Local API authentication with auth switched ON (conftest turns it off for feature tests)."""
import os
import stat

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import create_app

LOCAL = ("127.0.0.1", 50000)
REMOTE = ("192.168.1.50", 50000)


@pytest.fixture(autouse=True)
def auth_on(monkeypatch):
    monkeypatch.setenv("ATLAS_AUTH_REQUIRED", "true")
    monkeypatch.delenv("ATLAS_ALLOWED_HOSTS", raising=False)


def make(client=LOCAL, host="127.0.0.1:8000"):
    return TestClient(create_app(), base_url=f"http://{host}", client=client)


def api_routes():
    # Built from the OpenAPI schema so a newly added route is covered automatically.
    for path, ops in create_app().openapi()["paths"].items():
        if path.startswith("/api/"):
            for method in ops:
                yield method.upper(), path.replace("{memory_id}", "x").replace("{task_id}", "x").replace("{device_id}", "x")


def test_route_sweep_is_not_empty():
    assert len(list(api_routes())) >= 25


@pytest.mark.parametrize("method,path", list(api_routes()))
def test_every_api_route_requires_the_token(method, path):
    r = make().request(method, path, json={})
    assert r.status_code == 401, (method, path, r.status_code)
    assert r.json()["code"] == "unauthorized"


def test_public_paths_stay_open():
    c = make(REMOTE)
    assert c.get("/health").status_code == 200
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/").status_code == 200


def test_browser_on_this_machine_gets_a_session_cookie_and_can_use_the_api():
    c = make(LOCAL)
    r = c.get("/")
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("atlas_session=") and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert c.get("/api/memory").status_code == 200  # TestClient keeps the cookie


def test_other_devices_get_no_cookie_without_pairing():
    c = make(REMOTE, host="127.0.0.1:8000")
    assert "set-cookie" not in c.get("/").headers
    assert c.get("/api/memory").status_code == 401


def test_install_token_pairing_link_gives_the_device_its_own_token():
    c = make(REMOTE)
    token = auth.get_token()
    r = c.get(f"/?pair={token}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert token not in cookie and "HttpOnly" in cookie  # the install token never lands on the device
    assert c.get("/api/memory").status_code == 200
    assert c.get("/api/devices/current").json()["kind"] == "device"


def test_wrong_pairing_token_is_rejected():
    r = make(REMOTE).get("/?pair=not-the-token", follow_redirects=False)
    assert r.status_code == 401 and "set-cookie" not in r.headers


def test_bearer_token_works_for_scripts_and_wrong_tokens_fail():
    c = make(REMOTE)
    assert c.get("/api/memory", headers={"Authorization": f"Bearer {auth.get_token()}"}).status_code == 200
    assert c.get("/api/memory", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/api/memory", headers={"Cookie": "atlas_session=nope"}).status_code == 401
    assert c.get("/api/memory", headers={"Cookie": "garbage;;=="}).status_code == 401


def test_token_file_is_private_and_stable_and_rotation_invalidates_sessions():
    first = auth.get_token()
    assert len(first) >= 40 and auth.get_token() == first
    if os.name != "nt":
        assert stat.S_IMODE(auth.token_path().stat().st_mode) == 0o600
    c = make(REMOTE)
    assert c.get("/api/memory", headers={"Authorization": f"Bearer {first}"}).status_code == 200
    auth.rotate_token()
    assert c.get("/api/memory", headers={"Authorization": f"Bearer {first}"}).status_code == 401


def test_env_token_overrides_file(monkeypatch):
    monkeypatch.setenv("ATLAS_API_TOKEN", "operator-supplied-token-0123456789abcdef")
    c = make(REMOTE)
    assert c.get("/api/memory", headers={"Authorization": "Bearer operator-supplied-token-0123456789abcdef"}).status_code == 200


def test_unknown_host_headers_are_rejected_to_stop_dns_rebinding():
    r = make(LOCAL, host="evil.example:8000").get("/health")
    assert r.status_code == 421 and r.json()["code"] == "unknown_host"


def test_extra_hosts_can_be_allowed(monkeypatch):
    monkeypatch.setenv("ATLAS_ALLOWED_HOSTS", "atlas.lan")
    assert make(LOCAL, host="atlas.lan:8000").get("/health").status_code == 200


def test_ipv6_loopback_host_is_accepted():
    assert make(("::1", 5000), host="[::1]:8000").get("/health").status_code == 200


def test_cross_origin_writes_are_blocked_even_with_a_cookie():
    c = make(LOCAL)
    c.get("/")
    r = c.post("/api/memory", json={"text": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["code"] == "cross_origin"
    assert c.post("/api/memory", json={"text": "x"}, headers={"Origin": "http://127.0.0.1:8000"}).status_code == 201
    assert c.post("/api/memory", json={"text": "y"}, headers={"Origin": "null"}).status_code == 403


def test_denials_still_carry_security_headers():
    r = make(REMOTE).get("/api/memory")
    assert r.headers["x-content-type-options"] == "nosniff"


def test_status_reports_auth_mode():
    c = make(LOCAL)
    c.get("/")
    assert c.get("/api/system/status").json()["auth"] == "token"


def test_cli_prints_token(capsys):
    assert auth._main(["token"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == auth.get_token() and "?pair=" in out.err


def test_cli_rotate_also_revokes_devices(capsys):
    c = make(REMOTE)
    c.get(f"/?pair={auth.get_token()}")
    assert c.get("/api/memory").status_code == 200
    assert auth._main(["rotate"]) == 0
    assert "1 paired device(s) revoked" in capsys.readouterr().err
    assert c.get("/api/memory").status_code == 401
