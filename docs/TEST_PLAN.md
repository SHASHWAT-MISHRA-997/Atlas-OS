# Test plan and latest report

## Suites

| Suite | Location | What it uses | Command (from `backend/`) |
|---|---|---|---|
| API / unit | `tests/test_api.py`, `test_llm.py`, `test_providers.py`, `test_security.py`, `test_memory.py` (real SQLite in temp dirs), `test_tasks.py` (real engine + SQLite) | FastAPI TestClient. **Mocked provider** via `httpx.MockTransport` (see `tests/conftest.py`) | `python -m pytest -q -m "not e2e"` |
| Browser e2e | `tests/e2e/test_ui.py` | Real uvicorn process, real Chromium via Playwright, **fake Ollama server** defined in the test | `python -m pytest -q -m e2e` |
| Lint + security lint | `ruff.toml` (includes bandit `S` rules) | ruff | `python -m ruff check .` |
| JS syntax | `frontend/static/app.js` | Node | `node --check ../frontend/static/app.js` |

Mocks live only under `tests/`. Production code has no mock paths or test flags. The e2e fake reaches the app only through `ATLAS_OLLAMA_BASE_URL`, which is the same setting a real user would use.

## Latest report

Date: 2026-10-23. Environment: Linux container, Python 3.13.16, Chromium 141 (Playwright 1.64.1), Node 22.22.0. **Not Windows.**

| Command | Exit | Passed | Failed | Skipped |
|---|---|---|---|---|
| `python -m pytest -q -m "not e2e"` (Python 3.13.16, run 3 times) | 0 | 103 | 0 | 0 |
| `python -m pytest -q -m "not e2e"` (Python 3.11.17, the CI version) | 0 | 103 | 0 | 0 |
| `ATLAS_E2E_CHROMIUM=/opt/pw-browsers/chromium python -m pytest -q -m e2e` | 0 | 14 | 0 | 0 |
| `python -m ruff check .` | 0 | clean | — | — |
| `node --check ../frontend/static/app.js` | 0 | OK | — | — |
| `detect-secrets scan --all-files` | 0 | Only test placeholders and cache tags | — | — |
| `pip-audit -r requirements.txt` | 0 | No known vulnerabilities | — | — |
| `docker build .` | — | **Not run** (no Docker here) | — | — |
| GitHub Actions | — | **Not run** (source not pushed) | — | — |

The 18 original tests pass on the refactored backend. Their only change is blank lines between import groups added by ruff.

## Manual verification still required

### Real Ollama (Windows 11 or any OS)
1. Install Ollama from https://ollama.com/download and run `ollama pull llama3.2:3b` (about 2 GB; choose a smaller model if you have under 8 GB RAM).
2. `cd backend && python -m uvicorn app.main:app`, then open http://127.0.0.1:8000.
3. Expect the sidebar to show "Ollama: 1 local model(s)". In AI Chat the model fills in automatically.
4. Send "Namaste, kaise ho?". Expect a streamed reply labelled "Answered by Ollama (local) (on this machine)".
5. Ask for a 500-word essay and press Stop after a few words. Expect "Stopped by you". In Ollama's log, the request should end early.
6. Run `ollama stop llama3.2:3b`, quit Ollama, and send again. Expect a red error: "Ollama is not reachable…".
7. Record the results in this file with the date and machine specs.

### Real cloud provider (optional, your own key)
Set `ATLAS_GROQ_API_KEY` (or another provider's key) in your shell or a `.env` file. **Never paste it into a chat with anyone.** Pick a model from Load models, tick the notice, and send. Expect the answer to be labelled "(cloud)" with the latency shown.

### Desktop launch on Windows
Set `ATLAS_ENABLE_DESKTOP_AGENT=true`, then `POST /api/desktop/launch {"app_id":"notepad","confirm":true}`. Expect Notepad to open and `launched: true`. With the variable unset, expect 403.

## Not yet covered

There are no automated tests for the CSV workbench, no accessibility audit (axe), no load tests, no Windows CI runner, and no real-provider contract tests.
