from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_plan_success_is_simulation_only():
    response = client.post("/api/tasks/plan", json={"command": "Analyze sales"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "simulation"
    assert len(body["steps"]) == 4
    assert "no files" in body["notice"]

def test_plan_rejects_empty_command():
    response = client.post("/api/tasks/plan", json={"command": ""})
    assert response.status_code == 422

def test_plan_rejects_too_long_command():
    response = client.post("/api/tasks/plan", json={"command": "x" * 2001})
    assert response.status_code == 422


def test_desktop_status_is_opt_in(monkeypatch):
    monkeypatch.delenv("ATLAS_ENABLE_DESKTOP_AGENT", raising=False)
    response = client.get("/api/desktop/status")
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert {item["id"] for item in response.json()["apps"]} == {"notepad", "calculator", "file_manager"}

def test_desktop_launch_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ATLAS_ENABLE_DESKTOP_AGENT", raising=False)
    response = client.post("/api/desktop/launch", json={"app_id": "notepad", "confirm": True})
    assert response.status_code == 403

def test_desktop_launch_requires_confirmation(monkeypatch):
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "true")
    response = client.post("/api/desktop/launch", json={"app_id": "notepad", "confirm": False})
    assert response.status_code == 400

def test_desktop_launch_uses_fixed_allowlist(monkeypatch):
    response = client.post("/api/desktop/launch", json={"app_id": "powershell", "confirm": True})
    assert response.status_code == 422
