# Feature matrix

States: **Not implemented** · **Partially implemented** · **Implemented** (code exists, but its acceptance tests have not passed in the target environment) · **Verified** (acceptance tests passed in the environment named).

"Verified (Linux, mocked provider)" means automated tests passed on Linux with the model provider replaced by `httpx.MockTransport` or a fake Ollama server. It is **not** evidence that a real provider, a real Ollama install, or Windows works.

Last updated: 2026-10-25 (v0.9.0), branch `atlas/v0.9`.

## Foundation and security

| Feature | Location | Status | Evidence / gap |
|---|---|---|---|
| App starts and serves UI + API | `backend/app/main.py` | Verified (Linux) | `uvicorn app.main:app` + curl; e2e tests start a real uvicorn process |
| Config via env / `--env-file` | `app/config.py`, `backend/.env.example` | Verified (Linux) | `uvicorn --env-file` checked manually; tests use env |
| Security headers + CSP (no inline script) | `app/security.py` | Verified (Linux, Chromium) | `test_security.py`; e2e saw CSP block `eval` |
| Request-body size limit (incl. chunked) | `app/security.py` | Verified (Linux) | `test_oversized_bodies_*` |
| Rate limit on model endpoints | `app/security.py` | Verified (Linux) | `test_llm_rate_limit_returns_429_with_retry_after`. In-memory and single-process only |
| Validation errors redact inputs | `app/main.py` | Verified (Linux) | `test_validation_errors_do_not_echo_api_keys` |
| API docs off in production | `app/main.py` | Verified (Linux) | `test_api_docs_are_off_in_production` |
| CORS same-origin only | `app/main.py` | Verified (Linux) | `test_cors_does_not_allow_foreign_origins` |
| API login (per-install token, same-computer cookie, pairing link, Bearer) | `app/auth.py` | Verified (Linux, Chromium) | `test_auth.py` sweeps every API route; e2e pairing flow |
| Automatic owner login only for direct same-computer access (not through a tunnel or proxy on the PC) | `auth.is_same_computer` | Verified (Linux) | `test_devices.py::test_a_proxy_on_this_computer_*`; fails on the v0.6 code |
| Host allowlist + Origin check (DNS rebinding, CSRF) | `app/auth.py` | Verified (Linux) | `test_unknown_host_*`, `test_cross_origin_writes_*` |
| Per-device credentials, one-time pairing codes, revocation, device list | `app/devices.py`, `routers/devices.py`, Devices screen | Verified (Linux, Chromium) | `test_devices.py`; e2e `test_owner_pairs_a_second_device_*`. Only token hashes stored. QR code when the link's address is known (`ATLAS_PUBLIC_URL` or the network address the owner opened). Not tested on a real phone over Wi-Fi |
| CI workflow (lint, tests, e2e, Docker, pip-audit, secret scan, Windows runner) | `.github/workflows/tests.yml` | Verified | All 4 jobs green on PR #1, [run 39955295769](https://github.com/SHASHWAT-MISHRA-997/Atlas-OS/actions/runs/39955295769) (2026-10-23) |
| Docker image | `Dockerfile` | Verified (CI) | `docker-build` job built the image and `/health` answered from the container, [run 39955295769](https://github.com/SHASHWAT-MISHRA-997/Atlas-OS/actions/runs/39955295769) |
| Lint + security lint | `backend/ruff.toml` | Verified (Linux) | `ruff check .` clean, including the bandit `S` rules |
| Secret scan | — | Verified (CI) | `detect-secrets` in the `backend` job; fails on any finding outside tests |
| Dependency audit | — | Verified (CI) | `pip-audit` in the `backend` job: no known vulnerabilities on 2026-10-23 |

## AI providers (Milestone C)

| Feature | Location | Status | Evidence / gap |
|---|---|---|---|
| Provider abstraction + capability flags | `app/providers/` | Verified (Linux, mocked provider) | `test_catalogue_*`. Vision/tools/structured output are reported as `false` because they are not wired |
| Chat with structured messages | `/api/llm/chat` | Verified (Linux, mocked provider) | `test_chat_with_messages_*` |
| Streaming (SSE) | `/api/llm/chat/stream` | Verified (Linux, mocked provider + Chromium) | `test_stream_*`, e2e `test_local_chat_streams_*` |
| Cancellation (Stop) closes the upstream connection | provider `stream()`, UI Stop | Verified (Linux, fake Ollama + Chromium) | `test_cancelling_a_stream_*`, e2e `test_stop_button_*` |
| Timeouts, bounded connect retries + backoff | `openai_compat.py` | Verified (Linux, mocked provider) | Retries only before the request reaches the provider, so it cannot double-bill |
| Error classification (auth, 429, model-not-found, context, OOM) | `classify_http_error` | Verified (Linux, mocked provider) | Provider bodies are never forwarded |
| Ollama detection + installed-model discovery | `/api/llm/ollama/status`, `/api/llm/models` | Verified (Linux, mocked provider) | Never downloads models |
| Configurable Ollama URL (operator env only) | `ATLAS_OLLAMA_BASE_URL` | Verified (Linux) | Rejects non-http(s) schemes |
| Cloud model discovery | `/api/llm/models` | Verified (Linux, mocked provider) | Key goes in the POST body, never in the URL |
| Server-side provider keys | `ATLAS_<PROVIDER>_API_KEY` | Verified (Linux, mocked provider) | Never returned; the catalogue shows presence only |
| Local-only switch | `ATLAS_ALLOW_EXTERNAL_PROVIDERS=false` | Verified (Linux) | `test_external_providers_can_be_disabled` |
| Billing / data-routing acknowledgement in UI | `frontend/static/app.js` | Verified (Linux, Chromium) | e2e `test_cloud_provider_requires_key_and_billing_*` |
| Real Ollama end-to-end | — | **Not verified** | The workspace network blocks Ollama downloads, and the owner chose not to pursue it for now. See `TEST_PLAN.md` §Manual |
| Real cloud provider end-to-end | — | **Blocked** | Needs the user's own key; never requested in chat |
| Provider fallback (opt-in twice) | `routers/llm.py` | Verified (Linux, mocked provider + Chromium) | Owner sets `ATLAS_FALLBACK_PROVIDER/MODEL`; a cloud fallback needs the server's own key and cloud allowed; the user must also tick it in chat. Only on availability errors (unreachable, timeout, model missing, out of memory, rate limit), never on key or policy errors, and a stream falls back only before any text arrives. The answer is labelled. `test_fallback.py`, e2e `test_fallback_model_*` |
| ATLAS's own latency before the first token | `app/providers/tls.py` | Verified (Linux, fake model) | 7.5 ms median through ATLAS vs 1.7 ms direct (was 50.6 ms); `docs/RESEARCH.md` |
| Usage/latency metadata | chat + stream responses | Verified (Linux, mocked provider) | `latency_ms`, `first_token_ms`, `usage` when the provider sends it |

## Voice (Milestone D)

| Feature | Status | Notes |
|---|---|---|
| Dictation | Implemented | Browser Web Speech API (audio goes to the vendor in Chrome/Edge; the UI says so) or local Whisper on the PC (below) |
| Text-to-speech + Stop interrupts speech | Implemented | Browser `speechSynthesis`, or local Piper on the PC (below). Not tested on hardware |
| Local read-aloud (Piper), opt-in | Implemented (plumbing verified with a mock engine) | `app/tts.py`, `/api/voice/tts/*`, Model settings → Read-aloud engine. Voices (English US/UK, Hindi; ~63 MB each) download only when the owner presses Download on the PC; a broken download is never treated as installed. `test_tts.py` (labelled **mock**), e2e with network-level mocks. **Not verified with a real voice**: Hugging Face is blocked here, and the Hindi voice name was not checked against the live catalogue |
| Speech language (English India/US/UK, Hindi) and read-aloud voice choice; voices labelled on-device or online | Verified (Chromium, speech stubbed) | e2e `test_voice_language_and_voice_choice_*` uses a labelled stub of `speechSynthesis`; real voices depend on the phone or PC |
| Local STT (faster-whisper), opt-in | Implemented (plumbing verified with a mock engine) | `app/stt.py`, `/api/voice/*`, Model settings → Dictation engine. Optional install (`requirements-voice.txt`); the model (tiny ~75 MB, base ~145 MB, small ~484 MB) downloads only when the owner presses Download on the PC. `test_voice.py` checks limits, permissions and the flow with a labelled **mock** engine. **Not verified with a real model**: this workspace blocks Hugging Face downloads, so recognition quality and speed on Hindi/Hinglish are unmeasured |
| Hands-free "Hey ATLAS" | Implemented (verified in Chromium with a fake microphone and mocked transcription) | A voice-activity detector in the page cuts speech into clips (~150 ms to start, 0.8 s of quiet to end, 8 s max, adaptive to room noise); each clip is transcribed by local Whisper; only clips starting with "Hey ATLAS"/"ATLAS" (also एटलस) are used, or the next clip within 8 s after a bare "Hey ATLAS". Paused while ATLAS answers or speaks. Refuses to use the browser's online speech service. Works only while the page is open. e2e `test_hands_free_*`. Not a trained wake-word model: every clip goes through Whisper, so it uses more CPU than a real wake-word engine, and accuracy on real voices is unmeasured |
| Microphone selection, VAD | Implemented | Microphone choice applies to local dictation and hands-free; browser dictation still uses the default microphone (a browser limit). VAD as above |

## Windows agent (Milestone E)

| Feature | Status | Notes |
|---|---|---|
| Allowlisted app launch (Notepad/Calculator/File manager) | Verified (Windows CI runner) | `test_windows.py` launched real Notepad on the GitHub `windows` runner (Python 3.11.9), [run 39955295769](https://github.com/SHASHWAT-MISHRA-997/Atlas-OS/actions/runs/39955295769). Not tested on a personal Windows 11 PC. An approved task (`open_app`) in the Tasks screen; the old direct `/api/desktop/launch` is owner-only since v0.7 |
| Typed actions with risk notes, per-action approval, audit log | Verified (Linux; Windows on CI pending) | `app/agent.py`: `open_app`, `list_folder`, `search_files` run as tasks that always start AwaitingApproval; approval is bound to a SHA-256 of the exact parameters; who approved (owner or which paired device) is in the task events. `test_agent.py`, e2e `test_pc_action_*` |
| Scoped file access | Verified (Linux; Windows on CI pending) | Approved folders only (default Documents/Downloads/Desktop, or `ATLAS_AGENT_FOLDERS`); paths resolved incl. symlinks and must stay inside; links are never followed; list/search limits (500 entries, 100 results, 20k names, depth 8, 10 s). Writing is limited to the new-file and trash actions below; there is no overwrite and no permanent delete |
| Create notes, Word (.docx) and Excel (.xlsx) files | Verified (Linux, Chromium) | `create_note`, `create_document` approved actions. New files only: an existing name is refused (409), and the write is exclusive so a file appearing meanwhile is never replaced. Word: `#` headings and `-` bullets; Excel: CSV text, every cell stored as text (no formulas run). `test_file_actions.py`, e2e `test_note_is_written_*`, `test_file_goes_to_atlas_trash_*`. Not yet opened in real Microsoft Office |
| Move to ATLAS trash and restore | Verified (Linux, Chromium) | `move_to_trash` moves one regular file (not folders or links) into ATLAS's own trash folder; `restore_from_trash` puts it back and never overwrites. Nothing is permanently deleted by ATLAS. Trash is not emptied automatically |
| Media keys (play/pause, next, previous, volume, mute) | Implemented (Windows only) | `media_key` approved action via `keybd_event`. Refused with `unsupported_os` elsewhere (tested on Linux). Not tested on a real Windows PC |
| Browser control: open a website, web search | Verified (Linux, mocked browser + Chromium) | `open_url`, `web_search` approved actions open the default browser via Python `webbrowser`. Only public http(s) pages: `file:`, `javascript:`, `data:`, embedded logins, localhost, private, link-local and `.local` addresses are refused; internationalised names are shown in `xn--` form on the approval card. `test_browser_actions.py`, 17 red-team cases. No page automation (clicking, typing, reading pages) |
| Installer and start on login | Implemented (verified on Windows CI once the PR runs) | `scripts/windows/install.ps1`: checks Python 3.11+, makes `.venv`, installs `requirements.txt`, writes `start-atlas.cmd` and an editable `atlas-settings.cmd`; `-StartOnLogin` adds a Startup-folder shortcut, `-RemoveStartOnLogin` removes it. No admin rights, no model downloads. CI runs it, starts ATLAS and checks `/health` |

## Memory, tasks, remote, UI

| Feature | Status | Notes |
|---|---|---|
| Persistent memory in SQLite (add/edit/delete/clear) | Verified (Linux, real SQLite) | `test_memory.py`; survives app restart; e2e through UI |
| Memory full-text search (FTS5) kept in sync on edit/delete | Verified (Linux) | `test_search_uses_the_full_text_index_*` |
| Deletion removes text from the DB file (`secure_delete`) | Verified (Linux) | `test_deleted_text_is_removed_from_the_database_file`; test fails if the pragma is off |
| Memory on/off switch (excluded from prompts when off) | Verified (Linux, Chromium, fake Ollama) | e2e `test_memories_are_sent_to_the_model_only_when_enabled` |
| Export (JSON) / import with dedupe, all-or-nothing | Verified (Linux) | `test_export_*`, `test_import_*` |
| Backup and **tested** restore (SQLite backup API + CLI) | Verified (Linux) | `test_backup_and_restore_round_trip`; restore rejects foreign DBs |
| Move old browser-only memories/chat into storage | Verified (Chromium) | e2e `test_browser_memories_from_older_versions_*` |
| Chat history in SQLite, survives reload/restart | Verified (Linux, Chromium) | e2e + `test_chat_history_*`; capped at 500 per conversation |
| Delete one chat message, edit-and-resend, clear all | Verified (Chromium, FAKE model; API test on SQLite) | `test_chat_message_delete_*`, cloud e2e; each action asks first |
| Retention rules (auto-delete chat and memories after N days) | Verified (Linux, Chromium) | Off by default; `test_retention.py`, e2e `test_auto_delete_*`; applied on read and at start-up |
| Show which memories were sent with an answer | Verified (Chromium, fake Ollama) | Each answer lists the memories actually sent (relevance first, max 30 / 6000 chars). It shows what was sent, not what the model used |
| Document search (RAG) over approved folders | Verified (Linux, Chromium, fake Ollama) | `app/docsearch.py`. An approved `index_documents` task reads .txt, .md, .csv, .json, .log, .pdf (text layer) and .docx into a local FTS5 index (incremental by size and date; 10 MB per file, 5,000 files, 5 minutes). Memory → Documents searches and clears it. Chat → "Use my documents" sends up to 5 matching excerpts (5,000 chars) as untrusted data and lists the source files; a warning shows when the provider is cloud. Keyword search (bm25), not embeddings. Scanned PDFs are not read (no OCR). `test_docsearch.py`, e2e `test_note_is_written_indexed_searched_and_used_in_chat` |
| Browser-local fallback storage | Implemented | Used only when server storage is off (e.g. production) |
| CSV workbench (browser-only) | Implemented | Unchanged logic; no automated test yet |
| Quick plan on Home | Verified (Chromium, fake Ollama) | Uses the chat's local model, or the first model installed in Ollama, as a background plan task; falls back to the fixed example plan only when no local model exists. e2e `test_home_plan_*`, `test_task_plan_comes_from_backend` |
| Automations (scheduled tasks) | Verified (Linux, Chromium, fake Ollama) | `app/automations.py`, Automations screen. Daily, weekly or every N hours in the PC's local time; run now, pause, delete. Only creates tasks, so PC actions and cloud models still need approval each time; API keys are never stored. A run missed while ATLAS was off happens once at start-up. `test_automations.py`, e2e `test_automation_*`. Daylight-saving behaviour follows the OS; tested only in a fixed UTC+05:30 zone |
| Agents and Projects screens | Not implemented | Still placeholders |
| Task engine: states, enforced transitions, audit events | Verified (Linux, mocked provider) | `test_tasks.py` (20 tests) |
| Cancel (running and queued), pause/resume between steps | Verified (Linux, mocked provider + Chromium) | `test_cancel_*`, `test_pause_*`, e2e cancel |
| Real progress (parts done / total) | Verified (Linux, mocked provider) | `test_summarize_reports_real_per_part_progress` |
| One local model at a time, urgent-first scheduling | Verified (Linux, mocked provider) | `test_local_tasks_share_one_model_at_a_time`, `test_urgent_tasks_jump_the_queue` |
| Approval bound to parameters for cloud tasks | Verified (Linux, Chromium) | `test_cloud_tasks_wait_for_approval_*`, e2e |
| Idempotency keys, bounded queue, timeouts, step retries | Verified (Linux, mocked provider) | |
| Restart recovery (unfinished → Failed "interrupted", explicit Retry) | Verified (Linux) | `test_restart_*`, `test_recovery_after_crash_*` |
| Task types | Implemented | `plan` and `summarize_text` (model only), plus the approved PC actions in the Windows agent section |
| Device pairing (same LAN) | Verified (Linux, Chromium) | Plain HTTP on the LAN; no TLS, relay or internet access (rest of Milestone H) |
| HTTPS server option | Verified (Linux) | `python -m app.serve` with `ATLAS_TLS_CERT/KEY`; `test_serve.py` starts it and fetches over TLS |
| Remote access outside the home network | Partially implemented | `docs/REMOTE_ACCESS.md` (Tailscale Serve recommended). **Not verified**: needs a real Tailscale account and devices |
| Installable app (PWA): manifest, icons, offline screen | Verified (Chromium) | `test_pwa.py`; e2e `test_app_shell_opens_offline_*`. The offline screen needs HTTPS or localhost; over plain Wi-Fi HTTP the phone can only add a shortcut |
| Mobile layout (tab bar, More sheet, sticky chat composer, no cut-off content at 390 px) | Verified (Chromium, 390×844) | e2e `test_mobile_layout_*` walks every screen; not yet tried on a real phone |
| Live system status panel | Verified (Linux, Chromium) | `/api/system/status`; e2e |
| Tasks screen (live progress, approve/cancel/pause/resume/retry) | Verified (Chromium, fake Ollama) | e2e `test_plan_task_*`, `test_task_can_be_cancelled_*`, `test_cloud_task_needs_approval_*` |
| Responsive layout at 390 px | Verified (Chromium) | Was 747 px wide before the fix |
| Keyboard skip link + focus styles | Verified (Chromium) | |
| Automated accessibility audit (axe-core, WCAG 2.1 A/AA) | Verified (Chromium, 1280 and 390 px) | e2e `test_every_screen_passes_automated_accessibility_checks`: 0 serious or critical findings; `test_contrast.py` for gradient buttons. No manual screen-reader test |
| More sheet keeps focus inside and returns it | Verified (Chromium) | e2e `test_more_sheet_keeps_keyboard_focus_*` |
| Reduced motion | Implemented | `prefers-reduced-motion` CSS (from v7) |

## Online version on Netlify (v0.12, bring your own free key)

| Feature | Location | Status | Evidence / gap |
|---|---|---|---|
| Live site built by Netlify from `main` | https://atlas-os-sm.netlify.app | Verified (owner's phone) | The owner opened the v0.10 deploy on their phone on 2026-10-25 (screenshot in the project thread). This workspace cannot reach Netlify itself |
| Static build with the online layer | `scripts/netlify/build.mjs`, `netlify.toml` | Verified (Linux, CI, Netlify) | Built in CI, in the browser tests and on Netlify |
| Each visitor's own key: "Get your free AI key" card (provider picker, key page link, key checked before saving), "Start here" banner on Home, optional "Remember on this phone", removed when unticked | `app.js` (`cloudKey`, key card, `showKeyBanner`), `cloud.js` | Verified (Chromium, FAKE model) | `netlify/tests/e2e.test.mjs`, which also checks that no page shown online mentions Ollama. Key page links not opened from this workspace |
| Owner's environment keys and Netlify AI Gateway never used | `netlify/lib/cloud.mjs` | Verified (Node) | `the site owner's environment keys and AI Gateway are never used`: env keys set, request without key refused, request goes to the official URL with the visitor's key |
| Chat to the free providers only (Groq, Gemini, OpenRouter `:free` models), streamed, errors as messages, echoed key removed | `netlify/lib/cloud.mjs` | Verified (Node, **fake** provider responses) | Request and stream formats checked against stubs written from each provider's documented API. **No real provider call has been made from this workspace** |
| Model lists per provider; suggested default when listing fails; bad key reported | `/cloud/models` | Verified (fake responses) | Live lists not checked |
| Memory, chat history, tasks in the browser; plans and summaries | `cloud.js`, `app.js` | Verified (Chromium, FAKE model) | No sync between devices |
| PC-only features clearly refused online | `cloud.js`, `app.js` | Verified (Chromium) | Tasks, Automations, Devices and voice settings say so |
| Rate limit on the function | `netlify/functions/atlas.mjs` | Implemented | Netlify platform feature; not testable locally |

## Research (Milestone K)

| Question | Status | Evidence |
|---|---|---|
| Q1 local vs cloud first-token latency | Not measured | Needs real Ollama and a real key on stated hardware |
| ATLAS's own overhead (part of Q1) | Measured (Linux, fake model) | `docs/RESEARCH.md`: 7.5 ms median after fixing a 49 ms per-request TLS cost |
| Q2 cancellation latency | Measured (Linux, fake model) | 3.5 ms median from Stop to the model server's connection closing, 0 of 100 missed |
| Q3 permission policy | Measured (Linux), author-written cases | 67 of 67 attack cases blocked (20 added in v0.8, 17 in v0.9 for browser control); found and fixed two real holes in v0.7. Not an independent red team |
