# Changelog

## 0.13.3 — 2026-10-25 (branch `atlas/security-pass`)

Security pass: I attacked the app myself, then fixed what got through. Every attack is now a test.
- Online function, four gaps fixed:
  - Requests from other websites (browser `Sec-Fetch-Site` cross-site, or a foreign `Origin`) now get 403.
  - Only `application/json` is accepted (415), so HTML forms on other sites cannot post.
  - A provider sent as an array (`["groq"]`) was accepted; it now must be a string.
  - JSON and stream replies now carry `X-Content-Type-Options: nosniff`.
  - Oversized bodies are also refused from `Content-Length` before reading.
- New `netlify/tests/attack.test.mjs` (9 tests) tries:
  - header injection through the key;
  - proxying to other hosts and paths through model IDs;
  - prototype tricks;
  - smuggling tools, roles or base URLs;
  - cross-site calls and form posts;
  - huge and deeply nested bodies;
  - leaking the key in errors.
  It runs in CI.
- New browser test: HTML/script in a memory and in a chat reply never runs, and a prompt-injection message cannot get the key, because the key is never put into the prompt.
- New `backend/tests/test_attack_sqli.py`: 11 SQL injection payloads against 10 storage endpoints on the PC app. No errors, no leaked rows, no changed tables.
- Rate limit unchanged and confirmed in the live deploy: 60 requests a minute per visitor (Netlify), output capped at 2,048 tokens. The PC API keeps its own LLM rate limit (`test_llm_rate_limit_returns_429_with_retry_after`).
- Threat model: T36 corrected (3 provider hosts), T38 (cross-site) and T39 (injection) added.

## 0.13.2 — 2026-10-25 (branch `atlas/update-notify`)

- Update notice (PC app and online): when a newer version is deployed, a "New version available" banner appears with "Update now" (reloads into the new version) and "Later". The app checks on open, when it comes back on screen (at most every 5 minutes) and every 30 minutes. It only works while the app is open; there are no push notifications.
- "Check for update" button in the menu (under system status) says either that a version is available or "You have the latest version (x.y.z)".
- Online the version comes from a new `/version.json` written by the Netlify build (served with `Cache-Control: no-cache`); on the PC it comes from `/health`.
- Model choice: once models are loaded they are shown as a dropdown with every model the key can use (OpenRouter: free ones only), plus "Other: type a model ID". Before, a text box with suggestions showed only the one pre-filled model on phones.
- Tests: cloud e2e covers the update banner, Check for update and the model dropdown; local UI tests type custom model IDs through "Other".

## 0.13.1 — 2026-10-25 (branch `atlas/key-paste`)

Chat messages can now be managed (PC app and online):
- Every saved message has Copy and Delete; your own messages also have Edit, which puts the text back in the message box and removes the replies after it, so you can change it and send again. Each asks before deleting.
- The "Clear" button is now "Clear all".
- New backend route `DELETE /api/chat/history/{id}` (`?following=true` also removes later messages). Browser-stored messages get ids; older ones are given ids on first load.

Online version: easier to add your key on a phone.
- The key box is now a plain text box (phone keyboards hide clipboard suggestions in password boxes) with a "Paste" button. If the browser blocks clipboard reading, it says to press and hold the box and tap Paste.
- Pasted keys are cleaned: spaces, line breaks, quotes and invisible characters are removed.
- If the provider rejects a key that looks like another provider's (for example a `gsk_` Groq key under Gemini), the card says which provider to pick.
- Friendlier error texts; the Tasks screen no longer asks for models online before a key exists.
- Browser test pastes a messy key and checks it is cleaned and saved, then deletes, edits and clears messages. A backend test covers the new delete route.

## 0.13.0 — 2026-10-25 (branch `atlas/redesign`)

Redesign (both the PC app and the online version):
- New logo: an "A" with an orbit ring on a violet tile. New app icons (PWA, Apple touch, maskable) made from it.
- Calmer theme: flat dark surfaces, one violet accent, no grid background or glows, consistent spacing and type sizes.
- Simpler Home: goal box and plan first, then a short overview. The CSV analyzer and activity log fold away. The "agents" and "execution principles" blocks were removed from Home.
- Phones: no boxes inside boxes, opaque chat composer, one-row chat buttons without emoji (some Android fonts cut them off).
- Online: until a key is added, AI Chat shows only the key card; Agents and Projects (not built yet) are hidden from the menu.
- Tests: a browser-test fixture now blocks the service worker so faked endpoints are always used; one selector follows the new layout. All suites pass; the look was checked from phone and desktop screenshots in Chromium, not on a real phone.

## 0.12.0 — 2026-10-25 (branch `atlas/free-keys`)

Online version (Netlify):
- Only free cloud providers: Groq, Google Gemini and OpenRouter (free `:free` models only). OpenAI and Anthropic were removed online.
- New "Get your free AI key" card in AI Chat: pick a provider, open its key page, paste the key, Save. The key is checked with the provider before it is saved.
- Home shows a "Start here: get a free AI key" banner with direct links until a key is added.
- No Ollama or local-model text in the online app (Home stat is now "Your AI keys"; Integrations and Chat texts updated).
- A rejected key (401/403, or Gemini's "API key not valid") is now reported when listing models instead of falling back to a suggested model.
- Chat composer background is fully opaque so text behind it no longer shows through on phones.
- Tests: 13 function tests and the phone browser test updated (fake model, labelled FAKE). No real provider call has been made from this workspace.

## 0.11.0 — 2026-10-25 (branch `atlas/byok`)

### Changed
- **ATLAS online now uses each visitor's own API key.** There is no sign-in, owner claim or pairing any more. Each person pastes their key in AI Chat → Model settings, and can tick "Remember my key on this phone". The function never reads Netlify environment variables or Netlify AI Gateway credentials, so the site owner's keys and credits are never used.
- Providers online: Groq, Google Gemini, OpenRouter (new), OpenAI and Anthropic, always at their official addresses.
- Provider error messages that repeat the key show "[your key]" instead.
- Tasks keep the key in memory for that task only; it is never saved with the task.

### Removed
- Netlify Blobs device records, the claim screen, the "Set up AI" card and the `@netlify/blobs` dependency.

## 0.10.0 — 2026-10-25 (branch `atlas/cloud`)

### Added
- **ATLAS online on Netlify** (`netlify.toml`, `netlify/`, `frontend/cloud/`, `docs/CLOUD.md`). Use ATLAS from a phone with no PC: AI Chat with a real cloud model (Groq, Gemini, OpenAI or Claude; key set in Netlify, never in the app), memory and chat history in the browser, plan and summarize tasks, Home quick plan, and device pairing.
- Owner sign-in for the online version: the first device claims it (optionally with an access code), other devices join with one-time links, and the owner can remove them. Only token hashes are stored.
- A "Set up AI" card explains how to add a key in Netlify when none is set.
- Node tests for the function (17) and browser tests for the online version (2), with a labelled FAKE model. New `cloud` CI job.

### Changed
- In the online version, PC-only features (PC actions, document search, local voice, hands-free, automations) say they need ATLAS on the PC instead of showing PC settings.
- The service worker never caches `/cloud/` responses.

## 0.9.0 — 2026-10-25 (branch `atlas/v0.9`)

### Added
- **Hands-free "Hey ATLAS"** (opt-in): say "Hey ATLAS" and your request; ATLAS listens only while the chat is open and only with speech-to-text on your PC.
- **Read-aloud on your PC** with Piper voices (English US/UK, Hindi), downloaded only when you press Download.
- **Microphone choice** for dictation on the PC and hands-free.
- **Browser control:** "Open a website" and "Search the web" PC actions, with approval. Only public http(s) pages.
- **Automations:** run a plan, re-index, web search or website on a schedule (daily, weekly, every few hours).
- **Fallback model** (opt-in): if the chosen model fails, another one the owner set up can answer, and the answer says so.
- 17 more red-team cases (67 in total).

### Changed
- The Home quick plan now asks your local model for a real plan. The fixed example plan is used only when no model is installed.

### Fixed
- Voice recordings over 256 KB (about 30 seconds) were refused before they reached speech-to-text on the PC.


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
