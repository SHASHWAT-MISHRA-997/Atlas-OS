# Project audit — baseline (2026-10-23)

This records what was actually inspected and run. Nothing here was inferred from the UI or README alone.

## Sources inspected

| Source | What it contained |
|---|---|
| GitHub `SHASHWAT-MISHRA-997/Atlas-OS`, branch `main` (2 commits: `c4a3b15` Initial commit, `9edc3c0` Add files via upload) | Only `README.md` (`# Atlas-OS`) and `ATLAS_OS_Research_Starter_v4.zip`. No source code is committed outside the zip. |
| `ATLAS_OS_Research_Starter_v4.zip` (in repo) | Older copy of the same tree. v7 is a superset (README, `.env.example`, `main.py`, tests and `index.html` differ). |
| `ATLAS_OS_Research_Starter_v7.zip` (uploaded to the project) | The working source: 15 files under `atlas_work/`. Imported to the repo root on branch `atlas/v7-foundation` as commit "Import ATLAS OS Research Starter v7 source tree". |

Every file in v7 was read in full. No Git history exists for the source itself, only for the zip uploads.

## Architecture found

- **Entry point:** `backend/app/main.py`, run with `uvicorn app.main:app` from `backend/`. Serves `frontend/index.html` at `/`.
- **Frontend:** one 33.7 KB `index.html` with inline CSS and an inline minified script. No framework or build step.
- **Backend:** FastAPI + Pydantic v2 + httpx. No database. No authentication.
- **AI:** a BYOK chat endpoint for 8 fixed OpenAI-compatible cloud presets plus Ollama at a hard-coded `127.0.0.1:11434`. One-shot only, with no streaming or cancellation. Model discovery existed for Ollama only and was not used by the UI.
- **Automation:** `/api/desktop/launch` opens Notepad, Calculator or the file manager. It is opt-in via env, needs `confirm: true` and uses no shell.
- **Tasks:** `/api/tasks/plan` returns 4 fixed strings (simulation). The UI did **not** call it; it generated the same strings client-side.
- **Memory / chat history:** browser `localStorage` only.
- **CI:** `.github/workflows/tests.yml` runs pytest on Python 3.11. It has never run, because the workflow file is not committed to the repo; it is inside the zip.
- **Deployment:** two Dockerfiles. No hosting config, and no deployment exists.

## Baseline run (before any change)

Environment: Linux container, Python 3.13.16, fastapi 0.161.1, starlette 1.9.0, pydantic 2.14.1, httpx 0.28.1, pytest 8.4.2. Not Windows.

| Command (from `backend/`) | Exit | Result |
|---|---|---|
| `PYTHONPATH=. python -m pytest -q` | 0 | **18 passed**, 1 warning (Starlette deprecation for `httpx` in TestClient) |
| `python -m compileall -q backend/app` | 0 | OK |
| `uvicorn app.main:app` + curl | — | `/` 200, `/health` 200, `/api/docs` 200, `/docs` **404**, `/api/llm/ollama/status` 200 (unreachable), `/api/desktop/status` 200 |
| `docker build` | — | Not run: Docker is not available in this environment |

## Defects found

| # | Severity | Finding |
|---|---|---|
| 1 | High | **No source is committed**: the repo holds only a zip, so CI, review and history do not exist for the code. |
| 2 | Medium | `backend/Dockerfile` does `COPY ../frontend`, which is outside the build context, so that image cannot build. |
| 3 | Medium | No security headers or CSP, and an inline script, so a CSP could not be added without refactoring. |
| 4 | Medium | No request-body size limit beyond per-field lengths, and no rate limiting on the paid-provider proxy endpoint. |
| 5 | Medium | Pydantic 422 responses echo the offending input, so an over-long `api_key` would be returned in the error body. |
| 6 | Medium | Interactive API docs are always public (`/api/docs`), including in a hosted deployment. |
| 7 | Low | The README says "12 tests" (actual: 18) and "docs at /docs" (actual: `/api/docs`). |
| 8 | Low | The activity log printed a literal `\n` instead of a newline (double-escaped in the inline script). |
| 9 | Low | The UI showed fixed indicators ("Local demo ready", agent "READY" badges, "0 External connections") that did not reflect real state. |
| 10 | Low | The chat squashed memories and history into one `prompt` string, so long histories hit the 12,000-char limit and returned 422. |
| 11 | Low | The mobile layout (390 px) scrolled horizontally: the page was 747 px wide. |
| 12 | Info | Browser dictation (`webkitSpeechRecognition`) sends audio to the browser vendor's servers. The UI did not say so. |

Secret scan (`detect-secrets scan --all-files`) of v7 and of the v4 zip contents: **no real secrets**. The only hits were test placeholders such as `fake-key` and `test-secret`. Dependency audit (`pip-audit -r backend/requirements.txt`): **no known vulnerabilities** on 2026-10-23.

## Priorities chosen

1. Get the source into Git with working CI (Milestone A/B). See `docs/HANDOFF.md`: this session cannot push.
2. Milestone C, genuine AI integration: provider abstraction, streaming, cancellation, discovery, honest status. This was the first feature that turns the UI from a demo into a working assistant, and it is fully testable here.
3. Hardening that Milestone C needs to be safe: rate limits, size limits, CSP and redaction.

Everything else (voice, wake word, Windows agent, persistent memory, tasks, remote access) is listed in `FEATURE_MATRIX.md` with its status.
