# Changelog

## 0.5.0 — 2026-10-23 (branch `atlas/v7-foundation`, not yet released)

### Added
- Per-device logins (`backend/app/devices.py`). The Devices screen on the computer running ATLAS creates one-time pairing links (10 minutes, single use). Each paired device gets its own random token; only its SHA-256 hash is stored, in `devices.json` (0600).
- `/api/devices` (list), `/api/devices/pairing` (create code), `/api/devices/{id}` (remove), `/api/devices/current` (who am I / forget this device). Managing devices is owner-only.
- CLI: `python -m app.auth devices | revoke <id> | revoke-all`. `rotate` now also revokes every device.
- `ATLAS_PUBLIC_URL` (optional) so the Devices screen can show a complete link.

### Changed
- Pairing with the install token (`/?pair=<install token>`) now registers a device and gives it its own token; the install token is no longer stored on other devices.
- A browser on the same computer keeps an existing device session instead of being switched to the owner session.

## 0.4.0 — 2026-10-23 (branch `atlas/v7-foundation`, not yet released)

### Added
- API login (`backend/app/auth.py`): every `/api/` route needs the per-install token. A browser on the same computer gets it as an HttpOnly, SameSite=Strict cookie; other devices pair once with `/?pair=<token>` (shown by `python -m app.auth token`); scripts use `Authorization: Bearer`. `python -m app.auth rotate` signs every device out.
- Host-header allowlist (DNS-rebinding protection) and Origin check on writes (CSRF protection).
- UI banner explaining how to pair when a device is not signed in.
- CI: dependency audit, secret scan, and a Windows job that runs the test suite on a real Windows runner, including an actual Notepad launch.

## 0.3.0 — 2026-10-23 (branch `atlas/v7-foundation`, not yet released)

### Added
- SQLite storage (`backend/app/storage.py`) for memories, chat history and settings: versioned migrations, FTS5 search, `secure_delete`, export, import with dedupe, backup and restore (`python -m app.storage backup|restore|export|path`). Data lives in `%LOCALAPPDATA%\AtlasOS` on Windows or `~/.local/share/atlas-os` elsewhere (`ATLAS_DATA_DIR` overrides).
- `/api/memory`, `/api/memory/{id}`, `/api/memory/clear`, `/api/memory/settings`, `/api/memory/import`, `/api/chat/history`, `/api/storage/export`, `/api/storage/backup`.
- Background task engine (`backend/app/task_engine.py`) with real states, progress, cancel, pause/resume, priority, approval for cloud tasks, idempotency keys, timeouts and restart recovery. `/api/tasks` (create, list, get, approve, cancel, pause, resume, retry).
- Task types `plan` (model-written steps, never executed) and `summarize_text` (chunked).
- UI: Tasks screen; memory search and on/off switch; one-click move of old browser data into storage.

### Changed
- Memory and chat history default to server storage locally. In production mode server storage is off unless `ATLAS_SERVER_STORAGE=true`, because there is no authentication yet.
- The sidebar shows memory storage and task engine state.

## 0.2.0 — 2026-10-23 (branch `atlas/v7-foundation`, not yet released)

### Added
- Provider abstraction (`backend/app/providers/`) with per-provider capability flags, billing class and docs links.
- `POST /api/llm/chat/stream`: streaming replies as server-sent events (`start`, `delta`, `done`, `error`).
- Cancellation: the Stop button aborts generation, and the backend closes the provider connection.
- `POST /api/llm/models`: model discovery for Ollama (installed models only, never downloads) and cloud providers.
- `messages` (system/user/assistant) on chat endpoints, plus `temperature` and `max_tokens`. `prompt` still works.
- Latency, first-token time and token usage in responses when the provider reports them.
- Error classification: auth, rate limit, model not found, context too long, out of memory, timeout, unreachable.
- Bounded retries for connection failures only.
- `ATLAS_OLLAMA_BASE_URL`, `ATLAS_ALLOW_EXTERNAL_PROVIDERS`, `ATLAS_<PROVIDER>_API_KEY`, `ATLAS_ENV`, `ATLAS_ENABLE_API_DOCS`, rate/size/retry limits (see `backend/.env.example`).
- Security headers and a strict CSP; request-body size limit; per-IP rate limit on model endpoints.
- `GET /api/system/status` and a live status panel in the UI.
- Chat UI: provider dropdown, model list, streaming, Stop, data-routing and billing notice, answer provenance line.
- Memory export to JSON.
- Browser end-to-end tests (Playwright + Chromium + fake Ollama), ruff lint with security rules, and CI jobs for e2e and the Docker build.
- Docs: audit, feature matrix, architecture, threat model, test plan, decisions, handoff.

### Changed
- `backend/app/main.py` split into `config`, `security`, `providers/` and `routers/`. All 18 original tests pass; their only change is blank lines between import groups added by ruff.
- Frontend JS/CSS moved to `frontend/static/` with no inline script.
- The task plan now comes from the backend `/api/tasks/plan` and is labelled simulation.
- Status labels now come from real data. "Local demo ready", agent "READY" and "0 External connections" were removed.
- Validation errors return a readable `detail` string and never echo input values.
- API docs are off when `ATLAS_ENV=production`.
- Docker image runs as a non-root user with a healthcheck and production mode.
- Runtime and dev requirements split (`requirements-dev.txt`).

### Fixed
- `backend/Dockerfile` could not build (`COPY ../frontend`); removed in favour of the root `Dockerfile`.
- Activity log showed a literal `\n`.
- The mobile layout overflowed to 747 px at a 390 px viewport.
- README test count and API docs path.

## 0.1.0 — v7 research starter (imported as-is)
