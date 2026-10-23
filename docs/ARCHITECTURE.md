# Architecture (as built, v0.3.0)

ATLAS OS is currently one Python process that serves a static web UI and a JSON/SSE API. It is local-first: by default it talks only to Ollama on the same machine.

```mermaid
flowchart LR
  subgraph Browser
    UI[index.html + static/app.js]
    LS[(localStorage: memories, chat history, last provider/model)]
    UI <--> LS
  end
  subgraph "ATLAS backend (FastAPI, one process)"
    MW[Middleware: security headers / CSP, body-size limit, CORS]
    RL[Rate limiter: /api/llm/*]
    LLM[routers/llm.py]
    REG[providers/registry.py: fixed catalogue, policy, keys]
    ADP[providers/openai_compat.py: chat, stream, list_models]
    DESK[routers/desktop.py: allowlisted app launch, opt-in]
    TASK[routers/tasks.py + task_engine.py: background tasks]
    MEM[routers/memory.py]
    DB[(SQLite: memories + FTS5, chat, settings, tasks, task_events)]
    MEM --> DB
    TASK --> DB
    TASK --> REG
  end
  OLL[(Ollama on configured host)]
  CLOUD[(Cloud providers: Groq, OpenRouter, ...)]
  UI -- same-origin fetch / SSE --> MW --> RL --> LLM --> REG --> ADP
  ADP -- HTTP --> OLL
  ADP -- HTTPS, only if allowed + key --> CLOUD
  MW --> DESK
  MW --> TASK
  MW --> MEM
```

## Components

| Component | Responsibility | Notes |
|---|---|---|
| `app/main.py` | App factory, middleware, error handlers, `/health`, `/api/system/status`, static files | `create_app()` reads settings once for docs exposure |
| `app/config.py` | Typed settings from env | Read per call so tests and operators can change env |
| `app/security.py` | Headers/CSP, body limit, rate limiter | Rate limiter is in-memory, so it is only correct for one process |
| `app/providers/base.py` | `ChatMessage`, `Capabilities`, `ProviderSpec`, `ProviderError` | The provider-independent contract |
| `app/providers/openai_compat.py` | One adapter for every OpenAI-compatible API | Ollama uses its `/v1` compatibility endpoint for chat and `/api/tags` for discovery |
| `app/providers/registry.py` | Catalogue, policy checks, server keys, Ollama probe | Clients pick an **ID**, never a URL |
| `app/routers/llm.py` | `/api/llm/providers`, `/ollama/status`, `/models`, `/chat`, `/chat/stream` | |
| `app/routers/desktop.py` | `/api/desktop/status`, `/launch` | Disabled unless `ATLAS_ENABLE_DESKTOP_AGENT=true` |
| `app/routers/tasks.py` | `/api/tasks/plan` (simulation) and `/api/tasks` (engine) | |
| `app/task_engine.py` | State machine, scheduler, handlers (`plan`, `summarize_text`) | Runs on the API's event loop and starts/stops with the app lifespan. One worker pool (`ATLAS_TASK_CONCURRENCY`, default 2); local-model tasks are exclusive |
| `app/storage.py` | SQLite schema/migrations, memory, chat, export, backup/restore | One connection per request; WAL; `secure_delete` |
| `app/routers/memory.py` | `/api/memory*`, `/api/chat/history*`, `/api/storage/*` | Off in production unless `ATLAS_SERVER_STORAGE=true` |
| `frontend/` | UI, no build step | All JS is in `static/app.js`, so a strict `script-src 'self'` CSP works |

## Data flows

**Local chat (default).** The browser builds `messages`: a system note with the saved memories, then up to 12 recent turns, trimmed to under 46,000 characters. It POSTs them to `/api/llm/chat/stream`. The backend validates, rate-limits and resolves `ollama`, then streams from `ATLAS_OLLAMA_BASE_URL/v1/chat/completions` and re-emits `start`, `delta` and `done`/`error` SSE events.

**Cloud chat (opt-in).** The same flow, but the user must pick a cloud provider and tick the billing/data-routing notice. A key is supplied per request or by `ATLAS_<PROVIDER>_API_KEY`. Messages, memories and turns leave the machine.

**Cancel.** Stop calls `AbortController.abort()`. Starlette sees the disconnect and cancels the response generator. That exits the `httpx` stream context, which closes the provider connection. The e2e test checks this on the fake provider side.

## Trust and network boundaries

1. **Browser ↔ backend.** Same-origin only (CORS denies other origins). Every `/api/` call needs the install token (this computer) or a device token (paired devices, `app/devices.py`). Plain HTTP: bind to `127.0.0.1` unless you trust the LAN.
2. **Backend ↔ providers.** Outbound only, to the fixed URLs plus the operator-set Ollama URL. Redirects are not followed. Provider bodies are never forwarded to the browser.
3. **Backend ↔ OS.** Only `desktop.py`, only when enabled, and only allowlisted argv lists with `shell=False`.

## Failure handling

Provider failures become a `ProviderError(status, code, message)` with a safe message. Before streaming starts, they are returned as HTTP errors; after it starts, as an SSE `error` event. The UI shows errors in a red bubble and never stores them as model answers.

## Local vs cloud processing

| Data | Where it lives | Leaves the machine when |
|---|---|---|
| Memories, chat history, tasks | SQLite in the user data dir (browser localStorage only in production mode) | Memories and turns are sent with chat requests; task inputs are sent to the task's provider |
| CSV files | Browser memory only | Never |
| API keys | Request body only, or server env | Sent to that provider only |
| Dictation audio | Browser speech service | Chrome/Edge send it to their vendor |

## Retention and deletion

SQLite holds memories (until deleted, max 1,000), chat history (newest 500 per conversation) and task records (kept until a future cleanup feature exists). Deleting a memory removes it from the table and the FTS index, and `secure_delete` overwrites it in the file. Backups made with `app.storage backup` keep their own copy until you delete them. Data already sent to a cloud provider follows that provider's retention policy.

## Not yet designed in code

The local Windows agent process, auth and pairing are planned in `DECISIONS.md`. The cloud backend must never run the desktop agent (spec §4).
