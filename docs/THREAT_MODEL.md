# Threat model (v0.4.0)

Scope: a single user running the backend on their own machine, reached from a browser on the same machine. Hosted, multi-user and remote use are **out of scope until authentication exists**. This build must not be exposed to the internet.

| # | Threat | Current mitigation | Residual risk | Test |
|---|---|---|---|---|
| T1 | **Unauthenticated access** to the API by another device, a malicious website or DNS rebinding | Every `/api/` route needs the per-install token (cookie for same-computer browser, pairing link otherwise, or Bearer); Host allowlist; Origin check on writes; binds to 127.0.0.1 by default | Any local process running as the user can read the token file; the token travels in clear over plain HTTP if you bind to the LAN (use TLS at a reverse proxy); one token for all devices, so revoking one device means rotating for all | `test_auth.py` (route sweep of all 29 API operations, pairing, Host, Origin), e2e pairing test |
| T2 | **Cost abuse** through the BYOK or server-key proxy | Rate limit (30/min per IP); external providers can be disabled; billing acknowledgement in the UI | The rate limiter is in-memory and per IP; server keys are usable by anyone who can reach the API (see T1) | `test_llm_rate_limit_*`, `test_external_providers_can_be_disabled` |
| T3 | **SSRF**: making the backend call arbitrary hosts | Provider is an enum; URLs are fixed; the Ollama URL comes from operator env with scheme validation; no redirects | An operator could point the Ollama URL at an internal host on purpose | `test_invalid_ollama_base_url_falls_back_*` |
| T4 | **Secret leakage** of API keys | Keys are never logged or returned; validation errors drop inputs; keys travel in bodies, not URLs; the UI never stores keys | A key typed in the browser is visible to browser extensions | `test_validation_errors_do_not_echo_api_keys`, `test_server_side_key_*`, e2e localStorage check |
| T5 | **Leaking provider/internal details** in errors | Bodies are classified, never forwarded | — | `test_provider_errors_are_classified_without_leaking_bodies` |
| T6 | **XSS** through model output or memories | All rendering uses `textContent`; CSP `script-src 'self'`, no inline scripts | `style-src 'unsafe-inline'` is still allowed (CSS injection only) | `test_frontend_has_no_inline_scripts_*` |
| T7 | **Clickjacking** | `X-Frame-Options: DENY`, `frame-ancestors 'none'` | — | `test_security_headers_*` |
| T8 | **Denial of service** with large bodies | 256 KB body limit, including chunked bodies; field length limits | Slow-loris and similar need a reverse proxy | `test_oversized_bodies_*` |
| T9 | **Prompt injection** through memories or chat | The system note labels memories as untrusted context; the chat cannot trigger any action | The model may still follow injected text in its *answer*. There are no tools, so no actions | — (relevant once tools exist) |
| T10 | **Arbitrary code execution** through the desktop endpoint | Off by default; enum allowlist; `confirm: true`; `shell=False`; no arguments from the client | If enabled with no auth (T1), anyone reachable can open those 3 apps | `test_desktop_*` |
| T11 | **Silent audio upload** | Dictation is user-initiated per click, and the UI states that the browser vendor's service is used | Vendor processing is outside ATLAS's control | — |
| T12 | **Dependency compromise** | Ranged pins; `pip-audit` run manually | No lockfile or hash pinning yet; audit not in CI | — |
| T13 | **Malicious documents / files** | Only CSV, parsed in the browser with size, row and column limits | — | — |
| T14 | **Lost/stolen device** | SQLite file in the user profile (OS account permissions; `0700` dir on Linux/macOS) | The DB and backups are not encrypted by ATLAS; rely on full-disk encryption (BitLocker/FileVault) | — |
| T15 | **Cross-user data leakage** | Single-user design | Any shared deployment would mix users | — |
| T17 | **Memory exposure** through the unauthenticated API | Server storage is off in production mode; data dir is created `0700` on Linux/macOS; `secure_delete` | Anyone who can reach the API locally can read memories (see T1); the DB is not encrypted | `test_storage_is_off_in_production_unless_enabled` |
| T18 | **Runaway or duplicated background work** | Bounded queue (50), per-task timeout (600 s), max 20 parts, idempotency keys, connect-only/one-step retries | — | `test_queue_is_bounded`, `test_task_timeout_is_enforced`, `test_idempotency_*` |
| T19 | **Silent cloud sends from tasks** | Cloud tasks start in AwaitingApproval; approval must match the SHA-256 of the task's parameters; keys are held in memory only and never written to SQLite | Approval is a click by whoever can reach the API (T1) | `test_cloud_tasks_wait_for_approval_bound_to_parameters` |
| T20 | **Prompt injection in text given to summarize** | Text is labelled as data in the system note; tasks have no tools or actions | The summary itself can be manipulated | — |
| T16 | **API docs exposure** | Docs are off when `ATLAS_ENV=production` | — | `test_api_docs_are_off_in_production` |

Before any hosted or remote use: add per-device credentials and TLS (T1), a persistent rate limiter (T2), TLS at a reverse proxy, a lockfile with CI audit (T12), and server-side storage with access control (T14/T15/T17).
