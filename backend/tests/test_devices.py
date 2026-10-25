"""Per-device pairing, listing and revocation, with authentication ON."""
import json
import os
import stat

import pytest
from fastapi.testclient import TestClient

from app import auth, devices
from app.main import create_app

LOCAL = ("127.0.0.1", 50000)
PHONE = ("192.168.1.50", 50000)


@pytest.fixture(autouse=True)
def auth_on(monkeypatch):
    monkeypatch.setenv("ATLAS_AUTH_REQUIRED", "true")
    monkeypatch.delenv("ATLAS_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("ATLAS_PUBLIC_URL", raising=False)
    devices._pending.clear()
    yield
    devices._pending.clear()


def client(addr):
    return TestClient(create_app(), base_url="http://127.0.0.1:8000", client=addr)


def owner():
    c = client(LOCAL)
    c.get("/")  # loopback browser gets the owner cookie
    return c


def pair_phone(name="Phone"):
    code = owner().post("/api/devices/pairing", json={"name": name}).json()["code"]
    phone = client(PHONE)
    r = phone.get(f"/?pair={code}", follow_redirects=False)
    assert r.status_code == 303
    return phone, code, r.headers["set-cookie"]


def test_owner_creates_one_time_code_and_device_gets_its_own_cookie():
    phone, code, cookie = pair_phone()
    assert code not in cookie and auth.get_token() not in cookie
    assert phone.get("/api/memory").status_code == 200
    me = phone.get("/api/devices/current").json()
    assert me["kind"] == "device" and me["name"] == "Phone"


def test_pairing_code_works_only_once():
    _, code, _ = pair_phone()
    r = client(PHONE).get(f"/?pair={code}", follow_redirects=False)
    assert r.status_code == 401 and r.json()["code"] == "bad_pairing"


def test_pairing_code_expires(monkeypatch):
    code = owner().post("/api/devices/pairing", json={}).json()["code"]
    real = devices.time.monotonic
    monkeypatch.setattr(devices.time, "monotonic", lambda: real() + devices.PAIRING_TTL_SECONDS + 1)
    assert client(PHONE).get(f"/?pair={code}", follow_redirects=False).status_code == 401


def test_pending_codes_are_capped():
    o = owner()
    for _ in range(devices.MAX_PENDING_CODES):
        assert o.post("/api/devices/pairing", json={}).status_code == 201
    r = o.post("/api/devices/pairing", json={})
    assert r.status_code == 429 and r.json()["code"] == "too_many_codes"


def test_full_link_only_when_public_url_configured(monkeypatch):
    body = owner().post("/api/devices/pairing", json={}).json()
    assert body["url"] is None and body["path"].startswith("/?pair=")
    monkeypatch.setenv("ATLAS_PUBLIC_URL", "http://192.168.1.20:8000/")
    body = owner().post("/api/devices/pairing", json={}).json()
    assert body["url"] == "http://192.168.1.20:8000" + body["path"]


def test_owner_lists_and_revokes_device_and_device_loses_access_immediately():
    phone, _, _ = pair_phone("Old phone")
    assert phone.get("/api/memory").status_code == 200
    o = owner()
    listed = o.get("/api/devices").json()["devices"]
    assert [d["name"] for d in listed] == ["Old phone"]
    assert "token_sha256" not in listed[0]
    assert listed[0]["last_seen_at"]  # recorded by the phone's API call
    assert o.delete(f"/api/devices/{listed[0]['id']}").status_code == 200
    assert phone.get("/api/memory").status_code == 401
    assert o.get("/api/devices").json()["devices"] == []
    assert o.delete(f"/api/devices/{listed[0]['id']}").status_code == 404


def test_devices_cannot_manage_devices():
    phone, _, _ = pair_phone()
    for method, path in (("GET", "/api/devices"), ("POST", "/api/devices/pairing"), ("DELETE", "/api/devices/abc")):
        r = phone.request(method, path, json={})
        assert r.status_code == 403 and r.json()["code"] == "owner_only", path


def test_device_can_forget_itself():
    phone, _, _ = pair_phone()
    r = phone.delete("/api/devices/current")
    assert r.status_code == 200 and "Max-Age=0" in r.headers["set-cookie"]
    assert phone.get("/api/memory").status_code == 401
    assert owner().delete("/api/devices/current").json()["code"] == "not_a_device"


def test_bearer_device_token_works_for_scripts():
    _, token = devices.register("script")
    c = client(PHONE)
    assert c.get("/api/memory", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_only_hashes_are_stored_and_file_is_private():
    _, token = devices.register("Tablet")
    raw = devices.devices_path().read_text()
    assert token not in raw and json.loads(raw)["devices"][0]["token_sha256"]
    if os.name != "nt":
        assert stat.S_IMODE(devices.devices_path().stat().st_mode) == 0o600


def test_device_limit(monkeypatch):
    monkeypatch.setattr(devices, "MAX_DEVICES", 2)
    devices.register("a")
    devices.register("b")
    with pytest.raises(devices.DeviceError) as err:
        devices.register("c")
    assert err.value.code == "too_many_devices"


def test_corrupt_device_file_fails_closed():
    _, token = devices.register("x")
    devices.devices_path().write_text("{not json")
    assert client(PHONE).get("/api/memory", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_names_are_cleaned():
    record, _ = devices.register("  My \n  phone  ")
    assert record["name"] == "My phone"
    assert devices.register("")[0]["name"] == "Paired device"


def test_cli_lists_and_revokes(capsys):
    record, token = devices.register("Laptop")
    assert auth._main(["devices"]) == 0
    assert "Laptop" in capsys.readouterr().out
    assert auth._main(["revoke", record["id"]]) == 0
    assert auth.identify(token) is None
    assert auth._main(["revoke", "missing"]) == 1


def test_pairing_requests_are_validated():
    r = owner().post("/api/devices/pairing", json={"name": "x" * 41})
    assert r.status_code == 422


def test_pairing_has_no_link_or_qr_when_the_address_is_unknown():
    r = owner().post("/api/devices/pairing", json={}).json()
    assert r["url"] is None and r["qr_svg"] is None
    assert r["path"] == f"/?pair={r['code']}"


def test_pairing_link_and_qr_use_the_configured_public_url(monkeypatch):
    monkeypatch.setenv("ATLAS_PUBLIC_URL", "https://atlas.example.test/")
    r = owner().post("/api/devices/pairing", json={}).json()
    assert r["url"] == f"https://atlas.example.test/?pair={r['code']}"
    assert r["qr_svg"].startswith("data:image/svg+xml")
    # The QR encodes exactly the link (segno is deterministic for the same input).
    import segno
    assert r["qr_svg"] == segno.make(r["url"], error="m").svg_data_uri(scale=6, border=3)


def test_pairing_link_uses_the_network_address_the_owner_opened(monkeypatch):
    monkeypatch.setenv("ATLAS_ALLOWED_HOSTS", "192.168.1.5")
    c = owner()
    r = c.post("/api/devices/pairing", json={}, headers={"host": "192.168.1.5:8000"}).json()
    assert r["url"] == f"http://192.168.1.5:8000/?pair={r['code']}" and r["qr_svg"]


@pytest.mark.parametrize("headers", [
    {"x-forwarded-for": "100.64.0.7"},                      # nginx / generic reverse proxy
    {"tailscale-user-login": "someone@example.com"},        # Tailscale Serve
    {"cf-connecting-ip": "203.0.113.9"},                     # Cloudflare tunnel
    {"forwarded": "for=203.0.113.9;proto=https"},
], ids=["x-forwarded-for", "tailscale", "cloudflare", "forwarded"])
def test_a_proxy_on_this_computer_does_not_make_visitors_the_owner(headers):
    r = client(LOCAL).get("/", headers=headers)
    assert "set-cookie" not in r.headers
    assert client(LOCAL).get("/api/devices", headers=headers).status_code == 401


def test_loopback_connection_with_a_network_host_name_is_not_the_owner(monkeypatch):
    # e.g. a tunnel that rewrites nothing but connects from 127.0.0.1 with the public name
    monkeypatch.setenv("ATLAS_ALLOWED_HOSTS", "atlas.tailnet.ts.net")
    r = client(LOCAL).get("/", headers={"host": "atlas.tailnet.ts.net"})
    assert "set-cookie" not in r.headers


def test_device_cookie_is_secure_when_atlas_is_served_over_https(monkeypatch):
    monkeypatch.setenv("ATLAS_PUBLIC_URL", "https://atlas.tailnet.ts.net")
    code = owner().post("/api/devices/pairing", json={}).json()["code"]
    r = client(PHONE).get(f"/?pair={code}", follow_redirects=False)
    assert r.headers["set-cookie"].endswith("; Secure")
