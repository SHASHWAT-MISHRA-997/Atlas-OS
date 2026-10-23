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
def server(fake_ollama):
    port = free_port()
    env = {**os.environ, "ATLAS_OLLAMA_BASE_URL": f"http://127.0.0.1:{fake_ollama.port}",
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


def test_status_panel_shows_real_backend_and_ollama_state(page):
    page.wait_for_selector("text=API online")
    assert page.locator("#sysstatus").inner_text().count("2 local model(s)") == 1
    assert page.locator("#ollamastat").inner_text() == "02"
    assert "Task runner: simulation only" in page.locator("#sysstatus").inner_text()
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
    page.fill("#atlasmodel", "fake-missing")
    page.fill("textarea[aria-label=Message]", "hello")
    page.click("button:has-text('Send')")
    page.wait_for_selector(".bubble.error")
    assert "does not recognise this model" in page.locator(".bubble.error").inner_text()


def test_cloud_provider_requires_key_and_billing_acknowledgement(page, fake_ollama):
    open_chat(page)
    before = len(fake_ollama.chat_requests)
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
    pg.wait_for_selector("#topstatus:has-text('API online')")
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    pg.get_by_role("button", name="AI Chat").click()
    pg.wait_for_selector("#atlasprovider")
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    context.close()


def test_keyboard_users_can_reach_navigation(page):
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.textContent") == "Skip to content"
    page.keyboard.press("Tab")
    assert "Home" in page.evaluate("document.activeElement.textContent")
