# ATLAS OS — local-first AI assistant (early prototype)

[![ATLAS OS checks](https://github.com/SHASHWAT-MISHRA-997/Atlas-OS/actions/workflows/tests.yml/badge.svg)](https://github.com/SHASHWAT-MISHRA-997/Atlas-OS/actions/workflows/tests.yml)

ATLAS OS is an AI assistant you run on your own computer. It is **not** an operating system and **not** production-ready. This README describes only what exists today; see [docs/FEATURE_MATRIX.md](docs/FEATURE_MATRIX.md) for the status of every feature.

## What it does today (v0.2.0)

- **Chat with a local model through Ollama** (the default), with streamed replies, a Stop button that really cancels generation, automatic discovery of installed models, and clear errors when Ollama or a model is missing.
- **Optional cloud models** (OpenAI, Groq, OpenRouter, NVIDIA NIM, Together, Cerebras, Fireworks, DeepSeek) with your own key. Each reply says which provider and model answered. Cloud use needs an explicit billing/data-routing acknowledgement and can be switched off server-wide.
- **Browser-local memory** (add, edit, delete, export) and chat history. Memories are included as context in chat.
- **CSV workbench**: statistics computed in your browser; the file is never uploaded.
- **Live status** of the API, Ollama, cloud policy and desktop agent.
- **Task planner**: simulation only, returning fixed planning steps. Nothing is executed.
- **Desktop launcher** (off by default): opens Notepad, Calculator or the file manager. Not yet tested on Windows; API only.

## Not supported yet

Wake word, local speech recognition, Windows automation beyond the 3-app launcher, file operations, a real task engine, server-side memory, authentication, remote/mobile access, vision and tool calling. Browser dictation exists, but in Chrome/Edge **it sends audio to the browser vendor**.

## Requirements

- Python 3.11+ (tested here on 3.13 on Linux; **Windows 11 is the target but has not been tested yet**)
- Optional: [Ollama](https://ollama.com/download). For 8 GB RAM, start with `llama3.2:3b` (~2 GB) or `qwen2.5:1.5b`. 7–8B models want ~8 GB of free RAM or VRAM.

## Run locally

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux:        source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app            # binds to 127.0.0.1:8000
# with a config file:  python -m uvicorn app.main:app --env-file .env
```

Open http://127.0.0.1:8000. API docs are at http://127.0.0.1:8000/api/docs (development only).

Local model: install Ollama, run `ollama pull llama3.2:3b`, then open **AI Chat**. The model fills in automatically.

**Do not run with `--host 0.0.0.0` on a shared network.** There is no authentication yet (see [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md)).

## Configuration

All settings are environment variables; see [backend/.env.example](backend/.env.example). Key ones:

| Variable | Default | Purpose |
|---|---|---|
| `ATLAS_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Where Ollama runs (operator-set only) |
| `ATLAS_ALLOW_EXTERNAL_PROVIDERS` | `true` | `false` = local-only mode |
| `ATLAS_<PROVIDER>_API_KEY` | unset | Server-side key, e.g. `ATLAS_GROQ_API_KEY`, so the browser never handles it |
| `ATLAS_ENV` | `development` | `production` turns off API docs |
| `ATLAS_LLM_RATE_LIMIT_PER_MINUTE` | `30` | Per-IP limit on model calls |
| `ATLAS_ENABLE_DESKTOP_AGENT` | `false` | Enable the 3-app launcher on your own PC only |

Never commit `.env`, keys or private data. A key typed into the chat screen is sent with that request only, and is not stored or logged.

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -q -m "not e2e"     # API/unit tests (provider mocked)
python -m playwright install chromium
python -m pytest -q -m e2e           # browser tests (real Chromium + backend, fake Ollama)
python -m ruff check .
```

The latest results and the manual checks still needed (real Ollama, Windows) are in [docs/TEST_PLAN.md](docs/TEST_PLAN.md). Passing tests are not a guarantee of zero bugs or vulnerabilities.

## Docker

```bash
docker build -t atlas-os .
docker run -p 127.0.0.1:8000:8000 -e ATLAS_OLLAMA_BASE_URL=http://host.docker.internal:11434 atlas-os
```

The image runs in production mode as a non-root user. It has not been built in the development environment yet; CI builds it.

## Deployment

There is no deployment. Hosting this build publicly is **not safe**, because it has no authentication. A hosted Ollama URL cannot reach the user's PC. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Data and privacy

The server stores nothing (no database). Memories and chat history live in your browser's localStorage, unencrypted, and can be deleted from the UI. Chat requests to a cloud provider include your memories and recent turns. CSV files never leave the browser.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Ollama is not reachable" | Start Ollama; check `curl http://127.0.0.1:11434/api/tags`; set `ATLAS_OLLAMA_BASE_URL` if it runs elsewhere |
| "Ollama is running but has no models" | `ollama pull llama3.2:3b` |
| "model ran out of memory" | Use a smaller model or close GPU-heavy apps |
| "does not recognise this model ID" | Press **Load models** and pick from the list |
| 429 "ATLAS rate limit" | Wait a minute or raise `ATLAS_LLM_RATE_LIMIT_PER_MINUTE` |

## Uninstall

Stop the server, delete the folder and the `.venv`, and clear the site data for `127.0.0.1:8000` in your browser. Remove Ollama models with `ollama rm <model>`.

## Project docs

[Audit](docs/PROJECT_AUDIT.md) · [Feature matrix](docs/FEATURE_MATRIX.md) · [Architecture](docs/ARCHITECTURE.md) · [Threat model](docs/THREAT_MODEL.md) · [Test plan](docs/TEST_PLAN.md) · [Decisions](docs/DECISIONS.md) · [Handoff](docs/HANDOFF.md) · [Changelog](CHANGELOG.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)
