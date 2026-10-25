"""Browser end-to-end tests: real frontend + real backend process + real Chromium.

MOCK NOTICE: the model provider is a small fake Ollama server started by this
file (``FakeOllama``). It proves that the UI, backend, streaming and Stop button
work together; it does not prove that a real Ollama install or model works.

Requires `pip install -r requirements-dev.txt` and a Chromium for Playwright
(`python -m playwright install chromium`, or set ATLAS_E2E_CHROMIUM to an
existing Chromium binary). Skipped when Playwright is unavailable.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.e2e

BACKEND = Path(__file__).resolve().parents[2]
E2E_TOKEN = "e2e-token-0123456789abcdef0123456789abcdef"
AUTH = {"Authorization": f"Bearer {E2E_TOKEN}"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeOllama:
    """Minimal stand-in for Ollama's /api/tags and OpenAI-compatible chat endpoint."""

    def __init__(self):
        self.chat_requests: list[dict] = []
        self.disconnected = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/api/tags":
                    body = json.dumps({"models": [{"name": "fake-small:1b", "size": 1, "details": {"parameter_size": "1B"}},
                                                  {"name": "fake-slow:1b", "size": 1, "details": {}}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                outer.chat_requests.append(payload)
                if payload["model"] == "fake-missing":
                    body = b'{"error":"model \\"fake-missing\\" not found, try pulling it first"}'
                    self.send_response(404)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                last = payload["messages"][-1]["content"]
                if not payload.get("stream"):
                    if payload["model"] == "fake-slow:1b":
                        time.sleep(3)
                    system = payload["messages"][0]["content"] if payload["messages"][0]["role"] == "system" else ""
                    if "planner" in system:
                        answer = json.dumps({"steps": [{"title": "Book train", "detail": "Compare fares."},
                                                       {"title": "Pick hostel", "detail": "Near the old city."}]})
                    else:
                        answer = "Summary: " + last[:40]
                    body = json.dumps({"choices": [{"message": {"content": answer}, "finish_reason": "stop"}]}).encode()
                    try:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    except (BrokenPipeError, ConnectionResetError):
                        outer.disconnected.set()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    if payload["model"] == "fake-slow:1b":
                        for i in range(200):
                            self._chunk(f"word{i} ")
                            time.sleep(0.05)
                    else:
                        for piece in ["Echo: ", last]:
                            self._chunk(piece)
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    outer.disconnected.set()

            def _chunk(self, text):
                data = json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": None}]})
                self.wfile.write(f"data: {data}\n\n".encode())
                self.wfile.flush()

        self.port = free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()


@pytest.fixture(scope="module")
def fake_ollama():
    with FakeOllama() as fake:
        yield fake


@pytest.fixture(scope="module")
def server(fake_ollama, tmp_path_factory):
    port = free_port()
    docs = tmp_path_factory.mktemp("agent-docs")
    (docs / "college").mkdir()
    (docs / "college" / "dbms-notes.pdf").write_bytes(b"x")
    env = {**os.environ, "ATLAS_OLLAMA_BASE_URL": f"http://127.0.0.1:{fake_ollama.port}",
           "ATLAS_ENABLE_DESKTOP_AGENT": "true", "ATLAS_AGENT_FOLDERS": f"docs={docs}",
           "ATLAS_DATA_DIR": str(tmp_path_factory.mktemp("atlas-data")),
           "ATLAS_API_TOKEN": E2E_TOKEN, "ATLAS_AUTH_REQUIRED": "true",
           "ATLAS_LLM_RATE_LIMIT_PER_MINUTE": "1000", "PYTHONPATH": str(BACKEND)}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/health", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("backend did not start")
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as p:
        kwargs = {}
        if os.getenv("ATLAS_E2E_CHROMIUM"):
            kwargs["executable_path"] = os.environ["ATLAS_E2E_CHROMIUM"]
        try:
            b = p.chromium.launch(**kwargs)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium not available for Playwright: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser, server):
    context = browser.new_context()
    pg = context.new_page()
    pg.errors = []
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(server + "/")
    yield pg
    context.close()


def open_chat(page):
    page.get_by_role("button", name="AI Chat").click()
    playwright_sync.expect(page.locator("#atlasmodel")).not_to_have_value("", timeout=10000)


def open_model_settings(page):
    if page.locator("#chatsettings[open]").count() == 0:
        page.locator("#chatsettings > summary").click()


def test_status_panel_shows_real_backend_and_ollama_state(page):
    page.wait_for_selector("text=API online")
    assert page.locator("#sysstatus").inner_text().count("2 local model(s)") == 1
    assert page.locator("#ollamastat").inner_text() == "02"
    assert "Task engine: running" in page.locator("#sysstatus").inner_text()
    assert page.errors == []


def test_task_plan_comes_from_backend(page):
    page.fill("#command", "Plan a test")
    page.click("#run")
    page.wait_for_selector("text=PLAN READY · SIMULATION")
    assert "Request captured: Plan a test" in page.locator("#tasksteps").inner_text()


def test_local_chat_streams_answer_and_labels_provider(page, fake_ollama):
    open_chat(page)
    assert page.locator("#atlasprovider").input_value() == "ollama"
    assert page.locator("#atlasmodel").input_value() == "fake-small:1b"
    assert page.locator("text=Data routing: messages go to Ollama").count() == 1
    page.fill("textarea[aria-label=Message]", "namaste ATLAS")
    page.click("button:has-text('Send')")
    page.wait_for_selector("text=Echo: namaste ATLAS")
    page.wait_for_selector("text=Answered by Ollama (local) (on this machine)")
    # The reply is saved before the status says so; reloading earlier could race the save.
    playwright_sync.expect(page.locator(".chatstatus")).to_have_text("Reply received from Ollama (local).")
    sent = fake_ollama.chat_requests[-1]
    assert sent["stream"] is True
    assert sent["messages"][0]["role"] == "system" and sent["messages"][-1] == {"role": "user", "content": "namaste ATLAS"}
    # History survives a reload (browser-local storage).
    page.reload()
    open_chat(page)
    page.wait_for_selector("text=Echo: namaste ATLAS")
    assert page.errors == []


def test_stop_button_cancels_generation_and_upstream(page, fake_ollama):
    open_chat(page)
    open_model_settings(page)
    page.fill("#atlasmodel", "fake-slow:1b")
    page.fill("textarea[aria-label=Message]", "long answer please")
    page.click("button:has-text('Send')")
    page.wait_for_selector("text=word3")
    page.click("button[aria-label='Stop generating and speaking']")
    page.wait_for_selector("text=Stopped by you")
    shown = page.locator(".transcript").inner_text()
    assert "word199" not in shown
    assert fake_ollama.disconnected.wait(timeout=10), "backend kept reading from the provider after Stop"


def test_provider_errors_are_shown_as_errors_not_answers(page):
    open_chat(page)
    open_model_settings(page)
    page.fill("#atlasmodel", "fake-missing")
    page.fill("textarea[aria-label=Message]", "hello")
    page.click("button:has-text('Send')")
    page.wait_for_selector(".bubble.error")
    assert "does not recognise this model" in page.locator(".bubble.error").inner_text()


def test_cloud_provider_requires_key_and_billing_acknowledgement(page, fake_ollama):
    open_chat(page)
    before = len(fake_ollama.chat_requests)
    open_model_settings(page)
    page.select_option("#atlasprovider", "groq")
    page.fill("#atlasmodel", "some-model")
    page.fill("textarea[aria-label=Message]", "hello")
    page.click("button:has-text('Send')")
    page.wait_for_selector("text=Paste your Groq API key")
    page.fill("#atlaskey", "gsk_dummy_not_real")
    page.click("button:has-text('Send')")
    page.wait_for_selector("text=Confirm the data-routing and billing notice")
    assert len(fake_ollama.chat_requests) == before
    # The key is never persisted in browser storage.
    stored = page.evaluate("JSON.stringify(Object.assign({}, localStorage))")
    assert "gsk_dummy_not_real" not in stored


def test_mobile_layout_has_no_horizontal_scroll(browser, server):
    context = browser.new_context(viewport={"width": 390, "height": 844})
    pg = context.new_page()
    pg.goto(server + "/")
    pg.wait_for_selector("#topstatus:has-text('Online')")
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    # Every screen, reached the way a phone user would: bottom tabs, then the More sheet.
    for name in ("AI Chat", "Tasks", "Memory", "Home"):
        pg.locator(".tabbar").get_by_role("button", name=name).click()
        pg.wait_for_timeout(300)
        assert pg.evaluate(OVERFLOW_JS) == [], name
    for name in ("Agents", "Integrations", "Devices"):
        pg.locator("#morebtn").click()
        playwright_sync.expect(pg.locator("#sidebar")).to_be_visible()
        pg.locator("#sidebar").get_by_role("button", name=name).click()
        playwright_sync.expect(pg.locator("#sidebar")).to_be_hidden()
        pg.wait_for_timeout(300)
        assert pg.evaluate(OVERFLOW_JS) == [], name
    assert pg.locator(".search").is_hidden()  # the desktop quick-plan bar is not squeezed onto phones
    context.close()


# Lists visible controls and text blocks that stick out past the right edge of the screen.
OVERFLOW_JS = """() => {
  const w = document.documentElement.clientWidth;
  const out = [];
  if (document.documentElement.scrollWidth > w + 1) out.push('page scrolls sideways');
  for (const n of document.querySelectorAll('button, input, select, textarea, .panel, .task, h1, h2, p')) {
    const r = n.getBoundingClientRect();
    if (!r.width || n.closest('.cards, .chips-row, #sidebar:not(.open)')) continue;
    if (r.right > w + 1 || r.left < -1) out.push((n.id || n.className || n.tagName) + ' ' + Math.round(r.left) + '-' + Math.round(r.right));
  }
  return out;
}"""


def test_keyboard_users_can_reach_navigation(page):
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.textContent") == "Skip to content"
    page.keyboard.press("Tab")
    assert "Home" in page.evaluate("document.activeElement.textContent")


def open_memory(page):
    page.get_by_role("button", name="Memory").click()
    page.wait_for_selector("#memorytext")


def test_memory_is_saved_server_side_searchable_and_deletable(page, server):
    page.wait_for_selector("text=Memory: ATLAS storage (SQLite)")
    open_memory(page)
    page.fill("#memorytext", "Mera favourite colour neela hai")
    page.click("button:has-text('Save memory')")
    page.wait_for_selector("text=Mera favourite colour neela hai")
    page.fill("#memorytext", "Deadline is Friday")
    page.click("button:has-text('Save memory')")
    page.wait_for_selector("text=Deadline is Friday")
    stored = httpx.get(server + "/api/memory", headers=AUTH).json()
    assert {m["text"] for m in stored["memories"]} >= {"Mera favourite colour neela hai", "Deadline is Friday"}
    # Survives a reload because it lives in SQLite, not the page.
    page.reload()
    open_memory(page)
    page.fill("#memorysearch", "deadl")
    playwright_sync.expect(page.locator("#subview .tasklist .task")).to_have_count(1)
    page.click("button[aria-label='Delete memory']")
    page.wait_for_selector("text=No memories match that search.")
    assert "Deadline is Friday" not in {m["text"] for m in httpx.get(server + "/api/memory", headers=AUTH).json()["memories"]}
    assert page.errors == []


def test_memories_are_sent_to_the_model_only_when_enabled(page, server, fake_ollama):
    httpx.post(server + "/api/memory", json={"text": "User name is Asha"}, headers=AUTH)
    open_chat(page)
    page.fill("textarea[aria-label=Message]", "who am i")
    page.click("button:has-text('Send')")
    page.wait_for_selector("text=Echo: who am i")
    assert "User name is Asha" in fake_ollama.chat_requests[-1]["messages"][0]["content"]
    httpx.put(server + "/api/memory/settings", json={"enabled": False}, headers=AUTH)
    page.fill("textarea[aria-label=Message]", "again")
    page.click("button:has-text('Send')")
    page.wait_for_selector("text=Echo: again")
    assert "User name is Asha" not in fake_ollama.chat_requests[-1]["messages"][0]["content"]
    httpx.put(server + "/api/memory/settings", json={"enabled": True}, headers=AUTH)
    history = httpx.get(server + "/api/chat/history", headers=AUTH).json()["messages"]
    assert [m["content"] for m in history][-2:] == ["again", "Echo: again"]


def test_browser_memories_from_older_versions_can_be_moved_to_storage(page, server):
    page.evaluate("""localStorage.setItem('atlas.os.memories.v1', JSON.stringify([
        {id: 'x1', text: 'Legacy browser memory', createdAt: '2026-09-01T00:00:00.000Z'}]))""")
    page.reload()
    open_memory(page)
    page.click("button:has-text('Move to ATLAS storage')")
    page.wait_for_selector("text=Moved 1 memories")
    assert "Legacy browser memory" in {m["text"] for m in httpx.get(server + "/api/memory", headers=AUTH).json()["memories"]}
    assert page.evaluate("localStorage.getItem('atlas.os.memories.v1')") is None


def open_tasks(page):
    page.get_by_role("button", name="Tasks").click()
    page.wait_for_selector("#taskinput")
    playwright_sync.expect(page.locator("#taskmodel")).not_to_have_value("", timeout=10000)


def test_plan_task_runs_in_background_and_shows_real_steps(page):
    open_tasks(page)
    page.fill("#taskinput", "Plan a weekend trip to Jaipur on a student budget")
    page.click("button:has-text('Start task')")
    card = page.locator("[data-task-id]").first
    playwright_sync.expect(card.locator(".task-state")).to_have_text("SUCCEEDED", timeout=10000)
    assert "Book train" in card.inner_text() and "did not execute" in card.inner_text()
    assert page.errors == []


def test_task_can_be_cancelled_from_the_ui(page):
    open_tasks(page)
    page.select_option("#taskkind", "summarize_text")
    page.fill("#taskmodel", "fake-slow:1b")
    page.fill("#taskinput", "A long text that takes a while. " * 50)
    page.click("button:has-text('Start task')")
    card = page.locator("[data-task-id]").first
    playwright_sync.expect(card.locator(".task-state")).to_have_text("RUNNING", timeout=10000)
    card.locator("button[aria-label='Cancel task']").click()
    playwright_sync.expect(card.locator(".task-state")).to_have_text("CANCELLED", timeout=5000)
    playwright_sync.expect(card.locator("button:has-text('Retry')")).to_be_visible()


def test_cloud_task_needs_approval_in_the_ui(page, fake_ollama):
    open_tasks(page)
    before = len(fake_ollama.chat_requests)
    page.select_option("#taskprovider", "groq")
    page.fill("#taskmodel", "some-model")
    page.fill("#taskkey", "gsk_dummy_not_real")
    page.fill("#taskinput", "Plan something")
    page.click("button:has-text('Start task')")
    card = page.locator("[data-task-id]").first
    playwright_sync.expect(card.locator(".task-state")).to_have_text("AWAITING APPROVAL", timeout=5000)
    assert "Approve: send to Groq (may bill)" in card.inner_text()
    card.locator("button[aria-label='Cancel task']").click()
    playwright_sync.expect(card.locator(".task-state")).to_have_text("CANCELLED", timeout=5000)
    assert len(fake_ollama.chat_requests) == before


def test_unpaired_browser_sees_pairing_help_and_pairing_link_signs_in(browser, server):
    context = browser.new_context()
    pg = context.new_page()
    pg.goto(server + "/")
    context.clear_cookies()  # simulate a device that never received the loopback cookie
    pg.reload()
    context.clear_cookies()
    pg.get_by_role("button", name="Refresh status").click()
    pg.wait_for_selector("#pairbanner")
    assert "not signed in" in pg.locator("#pairbanner").inner_text()
    pg.goto(server + "/?pair=" + E2E_TOKEN)
    assert pg.url.rstrip("/") == server  # token removed from the address bar
    pg.wait_for_selector("text=API online")
    assert pg.locator("#pairbanner").count() == 0
    context.close()


def test_api_rejects_requests_without_token(server):
    r = httpx.get(server + "/api/memory")
    assert r.status_code == 401


def test_owner_pairs_a_second_device_from_the_ui_and_removes_it(page, browser, server):
    page.get_by_role("button", name="Devices").click()
    page.fill("#devicename", "Test phone")
    page.get_by_role("button", name="Create pairing link").click()
    link = page.locator("#pairlink").inner_text()
    path = link[link.index("/?pair="):]
    assert E2E_TOKEN not in link

    phone_ctx = browser.new_context()
    phone = phone_ctx.new_page()
    phone.goto(server + path)
    assert phone.url.rstrip("/") == server  # code removed from the address bar
    assert all(c["value"] != E2E_TOKEN for c in phone_ctx.cookies())
    phone.get_by_role("button", name="Devices").click()
    phone.wait_for_selector("text=This device is paired as “Test phone”")
    # The code is single-use.
    assert httpx.get(server + path, follow_redirects=False).status_code == 401

    page.get_by_role("button", name="Memory").click()
    page.get_by_role("button", name="Devices").click()
    row = page.locator("#devicelist .task", has_text="Test phone")
    playwright_sync.expect(row).to_have_count(1, timeout=5000)
    page.once("dialog", lambda d: d.accept())
    row.get_by_role("button", name="Remove Test phone").click()
    playwright_sync.expect(row).to_have_count(0, timeout=5000)

    phone.get_by_role("button", name="Refresh status").click()
    phone.wait_for_selector("#pairbanner")
    assert page.errors == []
    phone_ctx.close()


def test_pc_action_waits_for_approval_then_searches_files(page):
    page.get_by_role("button", name="Tasks").click()
    page.select_option("#actionkind", "search_files")
    page.select_option("#actionfolder", "docs")
    page.fill("#actionquery", "dbms")
    page.get_by_role("button", name="Ask for approval").click()
    card = page.locator(".task", has_text="Search 'dbms' in docs").first
    playwright_sync.expect(card.locator(".task-state")).to_have_text("AWAITING APPROVAL", timeout=5000)
    card.get_by_role("button", name="Approve: Search 'dbms' in docs").click()
    playwright_sync.expect(card.locator(".task-state")).to_have_text("SUCCEEDED", timeout=5000)
    playwright_sync.expect(card).to_contain_text("college/dbms-notes.pdf")
    assert page.errors == []


def test_app_shell_opens_offline_after_first_visit(browser, server):
    context = browser.new_context()
    pg = context.new_page()
    pg.goto(server + "/")
    pg.evaluate("() => navigator.serviceWorker.ready")
    pg.wait_for_function("() => navigator.serviceWorker.controller !== null", timeout=15000)
    context.set_offline(True)
    pg.reload()
    # The cached shell renders; live data shows as offline instead of pretending to work.
    playwright_sync.expect(pg.locator(".tabbar, .sidebar").first).to_be_attached()
    playwright_sync.expect(pg.locator("#topstatus")).to_contain_text("Offline", timeout=10000)
    context.set_offline(False)
    context.close()
