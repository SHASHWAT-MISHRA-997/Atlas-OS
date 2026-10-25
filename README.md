# ATLAS OS — local-first AI assistant (early prototype)

[![ATLAS OS checks](https://github.com/SHASHWAT-MISHRA-997/Atlas-OS/actions/workflows/tests.yml/badge.svg)](https://github.com/SHASHWAT-MISHRA-997/Atlas-OS/actions/workflows/tests.yml)

ATLAS OS is an AI assistant you run on your own computer. It is **not** an operating system and **not** production-ready. This README describes only what exists today; see [docs/FEATURE_MATRIX.md](docs/FEATURE_MATRIX.md) for the status of every feature.

## What it does today (v0.8.0)

- **Chat with a local model through Ollama** (the default). Replies stream in, and the Stop button really cancels generation. Installed models are found automatically, and you get clear errors when Ollama or a model is missing.
- **Optional cloud models** with your own key: OpenAI, Groq, OpenRouter, NVIDIA NIM, Together, Cerebras, Fireworks and DeepSeek. Each reply says which provider and model answered. Cloud use needs an explicit billing and data-routing acknowledgement, and can be switched off for the whole server.
- **Memory you control**, stored in SQLite on your computer. You can add, edit, search, delete, export and import memories, back up and restore them, or switch memory off. Each answer shows which memories were sent with it. Auto-delete after N days is optional and off by default.
- **Background tasks** with live progress, cancel, pause and resume, and urgent priority. Tasks can write a plan (never executed) or summarize long text. Cloud tasks wait for your approval.
- **PC actions** (off by default, for your own PC only): open Notepad, Calculator or the file manager; list and search file names in approved folders; create notes, Word and Excel files; move a file to ATLAS trash and restore it; media keys on Windows. ATLAS never overwrites or permanently deletes a file. Every action waits for your approval of exactly what it will do. There is no shell.
- **Search your documents:** index .txt, .md, .csv, .pdf and .docx files in an approved folder, search them on the Memory screen, and turn on "Use my documents" in chat to answer from them with the source files listed.
- **Phone use:** a phone layout with a bottom tab bar, and per-device login with a pairing QR code. Each phone can be removed on its own. ATLAS can be installed as an app, which shows an offline screen when it is served over HTTPS. See [docs/REMOTE_ACCESS.md](docs/REMOTE_ACCESS.md).
- **Voice:** dictation and read-aloud through the browser, with a choice of language and voice (in Chrome and Edge, **browser dictation audio goes to the browser vendor**). Optional local dictation on your PC with Whisper: `pip install -r backend/requirements-voice.txt`, then download a model from AI Chat → Model settings. Not yet tried with a real model.
- **CSV workbench**: statistics are computed in your browser, and the file is never uploaded.
- **Quick plan on Home** is still a fixed 4-step simulation. Use Tasks for a real plan.

## Not supported yet

Wake word, local text-to-speech, choosing a microphone, browser control, OCR for scanned PDFs, meaning-based (embedding) search, vision and tool calling. Remote access through Tailscale is documented but has not been tested with real devices. ATLAS has **not been tested on a personal Windows 11 PC**; only the CI Windows runner has been used.

## Requirements

- Python 3.11+ (tested here on 3.13 on Linux; **Windows 11 is the target but has not been tested yet**)
- Optional: [Ollama](https://ollama.com/download). For 8 GB RAM, start with `llama3.2:3b` (~2 GB) or `qwen2.5:1.5b`. 7–8B models want ~8 GB of free RAM or VRAM.

## Install on Windows

Install Python 3.11+ from python.org (tick "Add python.exe to PATH"), download this repository, then in its folder run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -StartOnLogin
```

Double-click `start-atlas.cmd` and open http://localhost:8000. Edit `atlas-settings.cmd` to turn on PC actions and choose folders. `-RemoveStartOnLogin` undoes start-on-login.

## Run locally

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux:        source .venv/bin/activate
pip install -r requirements.txt
python -m app.serve                       # binds to 127.0.0.1:8000
# or: python -m uvicorn app.main:app --env-file .env
```

Open http://127.0.0.1:8000. API docs are at http://127.0.0.1:8000/api/docs (development only).

Local model: install Ollama, run `ollama pull llama3.2:3b`, then open **AI Chat**. The model fills in automatically.

To use ATLAS from your phone, follow [docs/REMOTE_ACCESS.md](docs/REMOTE_ACCESS.md): same Wi-Fi, Tailscale (HTTPS, works anywhere), or your own certificate.

## Configuration

All settings are environment variables; see [backend/.env.example](backend/.env.example). Key ones:

| Variable | Default | Purpose |
|---|---|---|
| `ATLAS_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Where Ollama runs (operator-set only) |
| `ATLAS_ALLOW_EXTERNAL_PROVIDERS` | `true` | `false` = local-only mode |
| `ATLAS_<PROVIDER>_API_KEY` | unset | Server-side key, e.g. `ATLAS_GROQ_API_KEY`, so the browser never handles it |
| `ATLAS_ENV` | `development` | `production` turns off API docs |
| `ATLAS_LLM_RATE_LIMIT_PER_MINUTE` | `30` | Per-IP limit on model calls |
| `ATLAS_ENABLE_DESKTOP_AGENT` | `false` | Enable PC actions on your own PC only |
| `ATLAS_HOST` / `ATLAS_PORT` | `127.0.0.1` / `8000` | Where `python -m app.serve` listens |
| `ATLAS_TLS_CERT` / `ATLAS_TLS_KEY` | unset | Serve HTTPS with your certificate |
| `ATLAS_PUBLIC_URL` | unset | Address phones use; turns on the pairing QR code |

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

The image runs in production mode as a non-root user. Your browser reaches the container through Docker's network, so pair it once: `docker exec <container> python -m app.auth token`. It has not been built in the development environment yet; CI builds it.

## Deployment

There is no deployment. Hosting this build publicly is **not safe**: it has only a single shared token, no TLS of its own and no per-user separation. A hosted Ollama URL cannot reach the user's PC. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Data and privacy

Memories, chat history and task records are stored in SQLite at `%LOCALAPPDATA%\AtlasOS\atlas.db` (Windows) or `~/.local/share/atlas-os/atlas.db` (set `ATLAS_DATA_DIR` to change it). The file is not encrypted. Deleted memories are overwritten in the file. Back up with `python -m app.storage backup` and restore with `python -m app.storage restore <file>` from `backend/`. In production mode, server storage is off and the browser's localStorage is used instead. Chat requests to a cloud provider include your memories and recent turns. CSV files never leave the browser.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Ollama is not reachable" | Start Ollama; check `curl http://127.0.0.1:11434/api/tags`; set `ATLAS_OLLAMA_BASE_URL` if it runs elsewhere |
| "Ollama is running but has no models" | `ollama pull llama3.2:3b` |
| "model ran out of memory" | Use a smaller model or close GPU-heavy apps |
| "does not recognise this model ID" | Press **Load models** and pick from the list |
| 429 "ATLAS rate limit" | Wait a minute or raise `ATLAS_LLM_RATE_LIMIT_PER_MINUTE` |

## Uninstall

Stop the server, delete the folder and the `.venv`, delete the data folder above, and clear the site data for `127.0.0.1:8000` in your browser. Remove Ollama models with `ollama rm <model>`.

## Project docs

[Audit](docs/PROJECT_AUDIT.md) · [Feature matrix](docs/FEATURE_MATRIX.md) · [Phone and remote access](docs/REMOTE_ACCESS.md) · [Research](docs/RESEARCH.md) · [Architecture](docs/ARCHITECTURE.md) · [Threat model](docs/THREAT_MODEL.md) · [Test plan](docs/TEST_PLAN.md) · [Decisions](docs/DECISIONS.md) · [Handoff](docs/HANDOFF.md) · [Changelog](CHANGELOG.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)
