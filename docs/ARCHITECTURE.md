# Architecture (v0.25.1)

ATLAS OS is one web app. There is no backend of its own and no database.

```
browser                                          Netlify
┌───────────────────────────────┐   HTTPS        ┌────────────────────────┐      ┌──────────────┐
│ app.js   (screens)            │  /cloud/chat   │ functions/atlas.mjs    │ ───► │ Groq, Gemini,│
│   │ fetch('/api/…')           │  /cloud/models │   lib/cloud.mjs        │      │ OpenRouter,  │
│ cloud.js (answers /api/*)     │  /cloud/speak  │ validate, rate limit,  │ ◄─── │ OpenAI       │
│ localStorage: memories, chat, │  /cloud/trans- │ forward with the       │      └──────────────┘
│   tasks, remembered keys      │    cribe       │ visitor's own key      │
│                               │  /cloud/status └────────────────────────┘
│ realtime.js ── WebSocket ─────┼──────────────► Gemini Live API / OpenAI Realtime API
│ google.js ─── HTTPS (token) ──┼──────────────► Google sign-in, Calendar API, Gmail API
└───────────────────────────────┘
```

- `frontend/index.html`, `frontend/static/app.js`, `app.css`: the screens (Home, AI Chat, Live,
  Tasks, Automations, Memory, Integrations, Devices, System, About). `theme.js` applies the saved
  theme before the page paints. Automations run in `app.js` every 30 seconds while the page is
  open. Plain JavaScript, no framework, no build step besides copying.
- `frontend/static/cloud.js`: loaded before `app.js`. It answers the app's `/api/*` calls in the
  browser: chat, model lists, speech (`/speak`) and transcription (`/transcribe`) go to the
  function; tasks run in the page and are saved in localStorage; auto-switch between free providers
  happens here, so each key only ever travels to its own provider.
- `frontend/static/realtime.js` and `live-worklet.js`: loaded only on the Live screen (and by
  "Test my voice setup"). Real-time voice over a WebSocket straight from the browser to Google's
  Gemini Live API or, when the user picks it and ticks that it is billed, OpenAI's Realtime API.
  The worklet captures the microphone as 16-bit PCM; Dictate and turn-by-turn Live use it too in
  browsers without a speech service (Brave, Firefox).
- `frontend/static/google.js`: loaded only on the Integrations screen. Google sign-in (Google
  Identity Services token client, read-only scopes) and GET calls to the Calendar and Gmail APIs,
  straight from the browser; the token stays in memory. The client ID comes from `dist/config.json`
  (build variable `ATLAS_GOOGLE_CLIENT_ID`) or is typed by the owner.
- `frontend/static/sw.js` and `manifest.webmanifest`: installable app and an offline shell. The
  service worker never caches `/cloud` replies, `version.json` or `config.json`.
- `netlify/lib/cloud.mjs`: the whole server side: status, chat (streaming), model lists (including
  real-time voice models), speech and transcription. Fixed provider URLs, input validation, output
  cap (2,048 tokens), cross-site and content-type checks, key redaction in errors.
- `netlify.toml`: build, function, rate limit (60 requests a minute per visitor) and security
  headers (CSP listing every outside host, no framing, nosniff, COOP `same-origin-allow-popups`).
  The local preview server (`scripts/netlify/dev-server.mjs`) reads the same CSP.
- `scripts/netlify/build.mjs`: copies `frontend/` to `dist/`, adds `?v=<version>` to the script and
  style URLs, and writes `dist/version.json` (update banner) and `dist/config.json` (Google client ID
  or null).

Why the `/api` shim: the screens were written against an API, and keeping that boundary lets the
screens stay simple and lets tests stub one place. See D-025 in `DECISIONS.md`.
