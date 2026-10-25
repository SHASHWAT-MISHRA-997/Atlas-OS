# Changelog

## 0.8.0 — 2026-10-25 (branch `atlas/v0.8`)

### Added
- **Document search.** An approved "Index documents" PC action reads .txt, .md, .csv, .pdf and .docx files in an approved folder into a local full-text index. Memory → Documents searches or clears it. In chat, "Use my documents" sends matching excerpts with your message and lists the source files under the answer. A warning shows when the provider is a cloud one.
- **Writing files, safely.** New PC actions: create a note (.txt or .md), create a Word or Excel file, move a file to ATLAS trash, and restore it. ATLAS never overwrites a file and never deletes one permanently.
- **Media keys** (play/pause, next, previous, volume, mute) as an approved action on Windows.
- **Local speech-to-text (optional).** Pick "ATLAS on this PC" as the dictation engine. After `pip install -r requirements-voice.txt`, the owner can download a Whisper model (tiny, base or small) from the PC; audio is transcribed on the PC and not stored.
- **Windows installer:** `scripts/windows/install.ps1`, with `-StartOnLogin` and `-RemoveStartOnLogin`. CI runs it on Windows.
- 20 more red-team cases (50 in total) for writing, trash, indexing and search.

### Changed
- Approval cards for restore show the file's original place, not just an id.
- File names that Windows reserves for devices (`CON`, `NUL`, `COM1`…) are refused.


## 0.7.0 — 2026-10-25 (branch `atlas/v0.7`)

### Added
- Installable app (PWA): manifest, icons, and a service worker that shows the app shell when the PC is offline. It never caches `/api` data.
- Pairing QR code when the link's address is known, and a Wi-Fi address hint when it is not.
- Each chat answer lists exactly which saved memories were sent. Memories that share words with the message are sent first.
- Opt-in auto-delete for chat history and memories after 7, 30, 90 or 365 days (Memory screen, `/api/storage/retention`).
- Voice: choose the speech language (English India, US or UK, Hindi) and the read-aloud voice. Voices are labelled on-device or online, and microphone errors are clearer.
- `python -m app.serve`, with optional HTTPS (`ATLAS_TLS_CERT`, `ATLAS_TLS_KEY`), and `docs/REMOTE_ACCESS.md`.
- Research write-up (`docs/RESEARCH.md`), a latency benchmark (`backend/research/bench_latency.py`) and 30 red-team cases (`tests/test_redteam_actions.py`).
- Accessibility checks with axe-core on every screen, and contrast tests for gradient buttons.

### Fixed
- **Security:** a tunnel or reverse proxy on the PC (Tailscale Serve, cloudflared, nginx) made every visitor the owner. The owner login now needs direct same-computer access.
- **Security:** paired devices could open apps through `/api/desktop/launch` without an approval. It is now owner-only.
- Every chat message waited about 49 ms because a TLS context was rebuilt per request. ATLAS's overhead is now about 6 ms.
- Main buttons had 3.3:1 text contrast; they now meet WCAG AA (5.1:1 or better).
- The More sheet now moves keyboard focus inside and returns it on close, and the page behind is inert.
- The chat status line is visible on phones again, so microphone errors are not hidden.

## 0.6.1 — 2026-10-23 mobile polish (merged as PR #3)

### Fixed
- Symbols that showed as boxes on some Android phones are now inline SVG icons.
- Your own chat bubble was clipped by a header style (pill corners cut "YOU" and words); header styles are now scoped to the header.
- Chat box placeholder no longer wraps and gets cut at 320 px; composer buttons wrap instead of overflowing.
- PC action inputs stuck out of their card on narrow phones; they are now labelled fields.
- Home cards use a 2-column grid on phones instead of a sideways scroller; model name wraps instead of being cut.
- Verified with a scripted audit at 320/360/390/412 px for cut text, wrapped placeholders, round-corner clipping, elements outside their card, and tap targets in the More sheet (0 findings).

## 0.6.0 — 2026-10-23 (branch `atlas/windows-agent`)

### Added
- Desktop agent typed actions (`backend/app/agent.py`): `open_app` (allowlisted apps), `list_folder` and `search_files` (read-only, approved folders only). They run as tasks, always wait for approval of their exact parameters, and record who approved them.
- `ATLAS_AGENT_FOLDERS` to choose approved folders (default: Documents, Downloads, Desktop).
- Tasks screen: a PC actions form, approval cards that say exactly what will happen, and file results.

### Changed (mobile redesign)
- Phones get a bottom tab bar (Home, AI Chat, Tasks, Memory, More), a sticky top bar with live status, and a "More" sheet with every section and the system status. The squeezed quick-plan bar is hidden on phones.
- Chat: message bubbles, a collapsible model drawer with a route badge (local or cloud), an empty state with suggestions, and a composer that grows with the text and sticks above the tab bar.
- Bigger touch targets (44 px), 16 px inputs (no zoom on focus), horizontal agent cards, fixed oversized status dots.
- Browser test checks every screen at phone width for anything cut off past the screen edge.

### Changed
- `/api/desktop/status` also lists approved folders and actions. `/api/desktop/launch` uses the same launcher code.

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
