# Decisions

**D-001 Keep the existing stack (FastAPI + plain JS, no build step).** The v7 code is small and sound. A React/Vite/Tauri rewrite now would replace working code without adding verified capability. Revisit when the UI needs components or tests that justify a build step, or when the Windows agent needs a desktop shell (Tauri is the leading candidate).

**D-002 One OpenAI-compatible adapter for all current providers.** Every v7 provider, including Ollama's `/v1` endpoint, speaks chat-completions. A second adapter (for example, Google's native API) is added only when it is needed. Capabilities are declared per provider, and vision, tools and structured output are `false` until they are wired and tested.

**D-003 Local-first defaults.** Ollama is the default provider. Cloud providers are opt-in per message (billing/data-routing acknowledgement) and can be disabled server-wide with `ATLAS_ALLOW_EXTERNAL_PROVIDERS=false`. Server-side keys (`ATLAS_<PROVIDER>_API_KEY`) are preferred over browser-typed keys.

**D-004 Retry only connection failures.** Retrying a POST that reached the provider could double-bill or duplicate output, so only `httpx.ConnectError` is retried (2 times by default, backoff 0.25 s → 0.5 s). Timeouts and HTTP errors are surfaced immediately.

**D-005 SSE over fetch for streaming.** This is simpler than WebSockets, works through proxies, and the browser's `AbortController` gives cancellation for free. Errors that happen after the stream has started arrive as an `error` event, because the HTTP status has already been sent.

**D-006 Move JS/CSS out of `index.html`.** This is required for a strict `script-src 'self'` CSP, which is the main XSS mitigation for rendering model output.

**D-007 Tests mock the transport, not the code.** `httpx.MockTransport` and a fake Ollama HTTP server keep production code free of test hooks. Every mocked test is labelled as such in `FEATURE_MATRIX.md`.

**D-008 Research questions to evaluate once there is evidence** (not started):
1. Time-to-first-token and full latency: local Ollama models vs one cloud provider, on stated hardware, with a fixed prompt set.
2. Cancellation latency: time from Stop until the upstream connection closes and generation stops.
3. Permission-policy effectiveness, once the action engine exists: the share of unauthorized action attempts blocked, on a red-team prompt set.

**D-010 Tasks fail on restart instead of resuming.** A model call can be half done when the process stops, and replaying it could double-bill or duplicate output. Unfinished tasks become `Failed` (`interrupted`), and the user can Retry them explicitly.

**D-011 Scheduler owns resource exclusivity.** Workers pick the highest-priority task whose resource is free, rather than taking the next queue item and blocking on a lock. This keeps urgent tasks ahead and stops one queued local-model task from tying up a worker.

**D-012 Server storage is off in production mode.** Without authentication, a hosted ATLAS would share one memory store with everyone who can reach it.

**D-009 Planned next milestones, in order (superseded in part by v0.3.0; see HANDOFF.md):**
1. Push the source (blocked on access) and get a green CI run.
2. Milestone F-lite: SQLite storage for memories and chat with export/delete, because it unblocks memory surviving across devices, tasks and audit logs.
3. Milestone G: a real task engine with states and cancellation.
4. Milestone E: a Windows agent with typed actions, which needs a Windows machine to verify.

Voice (D) waits on local STT/TTS engine selection and real hardware.

**D-013 Per-device tokens in a JSON file, not the database.** Device records must work even when server storage is off (production default), and there are at most 20 of them. Only SHA-256 hashes are stored; pairing codes live in memory only, so a restart simply invalidates them. Paired devices can use every feature but cannot pair or remove other devices.
