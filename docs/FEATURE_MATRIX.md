# Feature matrix

States: **Not implemented** · **Partially implemented** · **Implemented** (code exists, but its acceptance tests have not passed in the target environment) · **Verified** (acceptance tests passed in the environment named).

"Verified (Linux, mocked provider)" means automated tests passed on Linux with the model provider replaced by `httpx.MockTransport` or a fake Ollama server. It is **not** evidence that a real provider, a real Ollama install, or Windows works.

Last updated: 2026-10-25 (v0.7.0), branch `atlas/v0.7`.

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
| Provider fallback | — | Not implemented | Only if explicitly configured (spec 5.5) |
| ATLAS's own latency before the first token | `app/providers/tls.py` | Verified (Linux, fake model) | 7.5 ms median through ATLAS vs 1.7 ms direct (was 50.6 ms); `docs/RESEARCH.md` |
| Usage/latency metadata | chat + stream responses | Verified (Linux, mocked provider) | `latency_ms`, `first_token_ms`, `usage` when the provider sends it |

## Voice (Milestone D)

| Feature | Status | Notes |
|---|---|---|
| Dictation | Partially implemented | Browser Web Speech API. Not local: Chrome/Edge send audio to the vendor. UI now says so |
| Text-to-speech + Stop interrupts speech | Partially implemented | Browser `speechSynthesis`. Not tested on hardware |
| Speech language (English India/US/UK, Hindi) and read-aloud voice choice; voices labelled on-device or online | Verified (Chromium, speech stubbed) | e2e `test_voice_language_and_voice_choice_*` uses a labelled stub of `speechSynthesis`; real voices depend on the phone or PC |
| Local STT (Whisper-family) | Not implemented | |
| Wake word "Hey ATLAS" | Not implemented | |
| Microphone selection, VAD | Not implemented | The browser speech API always uses the default microphone |

## Windows agent (Milestone E)

| Feature | Status | Notes |
|---|---|---|
| Allowlisted app launch (Notepad/Calculator/File manager) | Verified (Windows CI runner) | `test_windows.py` launched real Notepad on the GitHub `windows` runner (Python 3.11.9), [run 39955295769](https://github.com/SHASHWAT-MISHRA-997/Atlas-OS/actions/runs/39955295769). Not tested on a personal Windows 11 PC. An approved task (`open_app`) in the Tasks screen; the old direct `/api/desktop/launch` is owner-only since v0.7 |
| Typed actions with risk notes, per-action approval, audit log | Verified (Linux; Windows on CI pending) | `app/agent.py`: `open_app`, `list_folder`, `search_files` run as tasks that always start AwaitingApproval; approval is bound to a SHA-256 of the exact parameters; who approved (owner or which paired device) is in the task events. `test_agent.py`, e2e `test_pc_action_*` |
| Scoped, read-only file access | Verified (Linux; Windows on CI pending) | Approved folders only (default Documents/Downloads/Desktop, or `ATLAS_AGENT_FOLDERS`); paths resolved incl. symlinks and must stay inside; links are never followed; list/search limits (500 entries, 100 results, 20k names, depth 8, 10 s). No reading file contents, no writes, no deletes |
| Office document generation | Not implemented | |
| Browser/media control | Not implemented | |
| Startup on login | Not implemented | |

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
| Retention rules (auto-delete chat and memories after N days) | Verified (Linux, Chromium) | Off by default; `test_retention.py`, e2e `test_auto_delete_*`; applied on read and at start-up |
| Show which memories were sent with an answer | Verified (Chromium, fake Ollama) | Each answer lists the memories actually sent (relevance first, max 30 / 6000 chars). It shows what was sent, not what the model used |
| Document RAG | Not implemented | |
| Browser-local fallback storage | Implemented | Used only when server storage is off (e.g. production) |
| CSV workbench (browser-only) | Implemented | Unchanged logic; no automated test yet |
| Quick plan on Home | Partially implemented | Still the fixed 4-step simulation; points to Tasks for a real plan |
| Task engine: states, enforced transitions, audit events | Verified (Linux, mocked provider) | `test_tasks.py` (20 tests) |
| Cancel (running and queued), pause/resume between steps | Verified (Linux, mocked provider + Chromium) | `test_cancel_*`, `test_pause_*`, e2e cancel |
| Real progress (parts done / total) | Verified (Linux, mocked provider) | `test_summarize_reports_real_per_part_progress` |
| One local model at a time, urgent-first scheduling | Verified (Linux, mocked provider) | `test_local_tasks_share_one_model_at_a_time`, `test_urgent_tasks_jump_the_queue` |
| Approval bound to parameters for cloud tasks | Verified (Linux, Chromium) | `test_cloud_tasks_wait_for_approval_*`, e2e |
| Idempotency keys, bounded queue, timeouts, step retries | Verified (Linux, mocked provider) | |
| Restart recovery (unfinished → Failed "interrupted", explicit Retry) | Verified (Linux) | `test_restart_*`, `test_recovery_after_crash_*` |
| Task types | Implemented | Only `plan` (model writes steps; nothing executed) and `summarize_text`. No action-executing tasks exist |
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

## Research (Milestone K)

| Question | Status | Evidence |
|---|---|---|
| Q1 local vs cloud first-token latency | Not measured | Needs real Ollama and a real key on stated hardware |
| ATLAS's own overhead (part of Q1) | Measured (Linux, fake model) | `docs/RESEARCH.md`: 7.5 ms median after fixing a 49 ms per-request TLS cost |
| Q2 cancellation latency | Measured (Linux, fake model) | 3.5 ms median from Stop to the model server's connection closing, 0 of 100 missed |
| Q3 permission policy | Measured (Linux), author-written cases | 30 of 30 attack cases blocked; found and fixed two real holes. Not an independent red team |
