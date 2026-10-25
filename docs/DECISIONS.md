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

**D-014 Desktop actions are tasks that always need approval.** Reusing the task engine gives states, cancel, audit events and approval hashes for free. Until there is evidence that a risk policy can safely auto-approve anything, every action (even read-only) waits for a person. File access starts read-only; writes and deletes need their own design (undo, trash, dry run).

**D-013 Per-device tokens in a JSON file, not the database.** Device records must work even when server storage is off (production default), and there are at most 20 of them. Only SHA-256 hashes are stored; pairing codes live in memory only, so a restart simply invalidates them. Paired devices can use every feature but cannot pair or remove other devices.

**D-015 File writes create new files only; removal goes to ATLAS's own trash.** This is the write design D-014 asked for. Overwriting and permanent deletion are the actions a mistaken or injected approval would hurt most, so neither exists. A "delete" moves the file to `<data dir>/trash/<id>/` with a record of where it came from, and restore refuses to overwrite. Every write is still an approved task. Excel output stores every cell as text so no formula runs. A dry run was not added, because the approval card already shows the exact name, folder and size.

**D-016 Document search uses SQLite FTS5 keyword search, not embeddings.** It needs no model download, works offline on any PC, reuses the storage layer, and its results are explainable (snippets with highlighted words). It misses synonyms and other languages' spellings; an embedding index can be added later as an option without changing the indexing task. Indexing is an approved task per folder, and excerpts reach a model only when the user turns on "Use my documents".

**D-017 Local speech-to-text is faster-whisper, opt-in, with a download the owner starts.** It runs on CPU with int8 models (tiny ~75 MB to small ~484 MB) and supports Hindi and English. It is an optional install so the base app stays small, and the model download is a button on the PC with a size and a confirmation, never automatic. The browser's speech service remains the default.

**D-018 "Hey ATLAS" uses voice-activity detection plus local Whisper, not a trained wake-word model.** Trained engines (openWakeWord, Porcupine) need a custom "Hey ATLAS" model that could not be trained or downloaded here, and Porcupine needs an account key. Detecting speech in the page and transcribing short clips on the PC reuses the speech engine the user already chose, keeps audio local, and works in Hindi and English. It costs more CPU and is limited to while the page is open; a trained model can replace the detector later behind the same switch.

**D-019 Browser control opens pages; it does not drive them.** Opening a vetted http(s) address or a search in the user's own browser covers the common asks. Clicking, typing and reading pages (Playwright or an extension) would act with the user's logged-in sessions and needs its own approval design first.

**D-020 Fallback needs two opt-ins.** The owner configures it on the server, so no paid inference appears without them, and each user ticks it, so a local chat never leaves the PC without that person's choice.

**D-021 Automations create tasks; they never approve them.** Scheduled runs reuse the task engine, so every existing rule (approval for PC actions and cloud models, limits, audit events) applies unchanged.

**D-022 The online version is a browser layer plus one small function, not a hosted copy of the backend.** The FastAPI backend assumes one trusted PC (PC actions, files, SQLite, Ollama), and hosting it publicly is unsafe (README). For a phone-only owner, the useful part online is chat with a cloud model. So the Netlify build reuses the same `app.js`, and `frontend/cloud/cloud.js` answers its `/api/*` calls in the browser: chat goes to one function that holds the key, data stays in the browser, and PC-only features return a clear "needs your PC" error. One UI, no second app to maintain, and nothing on a server can touch a computer.

**D-023 Online sign-in is "first device claims, others pair", not passwords.** The owner must never paste secrets into a chat, and a password set by Claude would have to be shared somehow. Claiming from the owner's own phone needs no shared secret, and pairing reuses ATLAS's existing one-time-link model. The gap (a stranger claiming a fresh site first) is closed by an optional `ATLAS_ACCESS_CODE` the owner sets in Netlify, and recoverable by deleting the claim in Netlify Blobs.

**D-024 The online version is bring-your-own-key, with no sign-in (replaces D-023).** The owner asked that visitors use their own keys, not the owner's. With no server-side key there is nothing to protect behind a sign-in, so the claim and pairing flow was removed. The function reads no environment variables at all, which also keeps Netlify AI Gateway credentials, injected automatically on some plans, from being spent. Provider URLs are fixed in code so the function cannot relay keys or traffic to other hosts.

**D-025 Web app only (2026-10-25).** The owner works from a phone and an iPad, wants one app that runs everywhere, and chose "PC version poora delete karo" (delete the PC version completely). The FastAPI backend, Windows installer, Docker image, PC actions, local models, document search, local voice and device pairing were removed in 0.15.0; they remain in the Git history (last on `main` at 45298f7). The screens still call `/api/*`, answered in the browser by `cloud.js`, so the screens stay simple and tests stub one place. Automations and Devices come back as browser versions in the redesign.
