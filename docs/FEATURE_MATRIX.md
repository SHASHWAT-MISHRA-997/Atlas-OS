# Feature matrix

States: **Not implemented** · **Partially implemented** · **Implemented** (code exists, but its acceptance tests have not passed in the target environment) · **Verified** (acceptance tests passed in the environment named).

"Verified (Linux, mocked provider)" means automated tests passed on Linux with the model provider replaced by `httpx.MockTransport` or a fake Ollama server. It is **not** evidence that a real provider, a real Ollama install, or Windows works.

Last updated: 2026-10-23 (v0.3.0), branch `atlas/v7-foundation`.

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
| Authentication / sessions | — | Not implemented | Required before any hosted or remote use (Milestone H) |
| CI workflow | `.github/workflows/tests.yml` | Implemented | Never run on GitHub: the source is not pushed yet |
| Docker image | `Dockerfile` | Implemented | Not built here (no Docker). CI has a build + health smoke job |
| Lint + security lint | `backend/ruff.toml` | Verified (Linux) | `ruff check .` clean, including the bandit `S` rules |
| Secret scan | — | Verified (manual run) | `detect-secrets` found only test placeholders; not yet in CI |
| Dependency audit | — | Verified (manual run) | `pip-audit`: no known vulnerabilities on 2026-10-23; not yet in CI |

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
| Real Ollama end-to-end | — | **Blocked** | Ollama and models not installed in this container. See `TEST_PLAN.md` §Manual |
| Real cloud provider end-to-end | — | **Blocked** | Needs the user's own key; never requested in chat |
| Provider fallback | — | Not implemented | Only if explicitly configured (spec 5.5) |
| Usage/latency metadata | chat + stream responses | Verified (Linux, mocked provider) | `latency_ms`, `first_token_ms`, `usage` when the provider sends it |

## Voice (Milestone D)

| Feature | Status | Notes |
|---|---|---|
| Dictation | Partially implemented | Browser Web Speech API. Not local: Chrome/Edge send audio to the vendor. UI now says so |
| Text-to-speech + Stop interrupts speech | Partially implemented | Browser `speechSynthesis`. Not tested on hardware |
| Local STT (Whisper-family) | Not implemented | |
| Wake word "Hey ATLAS" | Not implemented | |
| Microphone selection, VAD, language selection | Not implemented | |

## Windows agent (Milestone E)

| Feature | Status | Notes |
|---|---|---|
| Allowlisted app launch (Notepad/Calculator/File manager) | Implemented | Unit tests cover the policy only. **Not tested on Windows.** No UI |
| Typed action schemas, risk classes, audit log | Not implemented | |
| Scoped file access | Not implemented | |
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
| Retention rules (auto-expiry) | Not implemented | Only a size cap today |
| Inspect which memory influenced an answer | Not implemented | All enabled memories (max 30) are sent; no attribution |
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
| Device pairing / remote access | Not implemented | Milestone H |
| Live system status panel | Verified (Linux, Chromium) | `/api/system/status`; e2e |
| Tasks screen (live progress, approve/cancel/pause/resume/retry) | Verified (Chromium, fake Ollama) | e2e `test_plan_task_*`, `test_task_can_be_cancelled_*`, `test_cloud_task_needs_approval_*` |
| Responsive layout at 390 px | Verified (Chromium) | Was 747 px wide before the fix |
| Keyboard skip link + focus styles | Verified (Chromium) | Partial: a full accessibility audit has not been done |
| Reduced motion | Implemented | `prefers-reduced-motion` CSS (from v7) |

## Research (Milestone K)

Not started. There is no evidence to report yet. Candidate questions are in `DECISIONS.md` D-008.
