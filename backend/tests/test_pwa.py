"""Installable app (PWA): manifest, icons and the service worker."""
import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_manifest_is_valid_and_icons_exist():
    r = client.get("/static/manifest.webmanifest")
    assert r.status_code == 200
    manifest = json.loads(r.text)
    assert manifest["start_url"] == "/" and manifest["display"] == "standalone"
    sizes = {i["sizes"] for i in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i.get("purpose") == "maskable" for i in manifest["icons"])
    for icon in manifest["icons"]:
        got = client.get(icon["src"])
        assert got.status_code == 200, icon["src"]
        if icon["type"] == "image/png":
            assert got.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_page_links_the_manifest_and_icons():
    html = client.get("/").text
    assert 'rel="manifest" href="/static/manifest.webmanifest"' in html
    assert 'rel="apple-touch-icon"' in html


def test_service_worker_is_served_from_root_without_login():
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.headers["cache-control"] == "no-cache"


def test_service_worker_never_caches_api_or_pairing_links():
    js = client.get("/sw.js").text
    assert "url.pathname.startsWith('/api/')" in js and "pair=" in js
