# ATLAS OS

ATLAS OS is an AI assistant that runs as a web app in the browser. Open
**https://atlas-os-sm.netlify.app** on any device with a modern browser: Android, iPhone, iPad,
Windows, Mac, Linux or ChromeOS. There is nothing to install. It can also be added to the home
screen as an app. It is **not** an operating system and **not** production-ready. This README
describes only what exists today; see [docs/FEATURE_MATRIX.md](docs/FEATURE_MATRIX.md) for the
status of every feature.

## What it does today (v0.18.1)

- **AI Chat** with your own key. Free providers come first: Groq, Google Gemini and OpenRouter
  (free models only). Paid OpenAI is optional and clearly marked. Replies stream, can be stopped,
  and can be copied, edited or deleted.
- **Chat extras:** a thinking level (Auto, Low, Medium, High); images and PDFs (PDFs with Gemini,
  OpenRouter or OpenAI); steer a reply by sending a new message while it is still coming; long chats
  are compressed into a model-written summary so they keep their context.
- **Live:** talk hands-free; ATLAS answers aloud and can look through your camera (or a shared
  screen on a computer).
- **About:** who builds ATLAS OS.
- **Auto-switch:** when the free provider you picked hits its limit or is down, the message goes to
  another free provider you added a key for. It never switches into a paid provider.
- **Memory:** notes you save are sent with chats so answers fit you. Export them as JSON.
- **Tasks:** plan a goal or summarize long text with the model you choose.
- **Home:** a quick step-by-step plan for a goal, and a CSV analyzer that works in the browser.
- **Voice:** dictation and read-aloud with your browser's speech service.
- **Automations:** plans and reminders on a schedule, while ATLAS is open in the browser.
- **Devices:** see what is stored on this device, export it, import it on another device, or erase it.
- **System:** status, updates, install, theme (dark, light or auto) and the activity log.
- **Updates:** a banner tells you when a new version is out; "Check for update" is on the System screen.

Everything you save (key if you tick "Remember", memories, chat history, tasks) stays in that
browser on that device. Nothing is synced. There is no sign-in.

## Not supported

Acting on your computer (opening apps, files), local models, calendar, email and messaging. A web
page cannot safely do these. ATLAS says so instead of pretending.

## How it works

The page (`frontend/`) talks to one small Netlify Function (`netlify/`). The function forwards each
chat to the provider you picked, with your key, and stores nothing. The site owner's keys are never
used. See [docs/CLOUD.md](docs/CLOUD.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Develop

Needs Node.js 20 or newer.

```bash
npm install
npm run build                 # writes dist/
ATLAS_FAKE_MODEL=1 npm run dev  # http://localhost:8888 with a labelled FAKE model
npm test                      # function, attack and size tests
npm run test:e2e              # browser tests (Chromium via Playwright)
```

Without `ATLAS_FAKE_MODEL=1` the preview talks to real providers with the key you paste.

## Deployment

The GitHub repository is linked to the Netlify project `atlas-os-sm`; every merge to `main`
deploys. Configuration is in `netlify.toml`.

## Data and privacy

Chats, saved memories and recent turns are sent to the provider you pick, under its terms.
Memories, history and a remembered key are kept in the browser's localStorage, readable by anyone
using the unlocked device. Do not enter passwords or sensitive data in chats.

## Project docs

[FEATURE_MATRIX](docs/FEATURE_MATRIX.md) · [CLOUD](docs/CLOUD.md) ·
[ARCHITECTURE](docs/ARCHITECTURE.md) · [THREAT_MODEL](docs/THREAT_MODEL.md) ·
[TEST_PLAN](docs/TEST_PLAN.md) · [DECISIONS](docs/DECISIONS.md) · [HANDOFF](docs/HANDOFF.md) ·
[CHANGELOG](CHANGELOG.md)

Versions up to 0.14.0 also had a PC version (FastAPI backend, Windows installer, PC actions, local
models). It was removed in 0.15.0 at the owner's request; it is still in the Git history.
