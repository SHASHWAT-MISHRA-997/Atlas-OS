# Architecture (v0.15.0)

ATLAS OS is one web app. There is no backend of its own and no database.

```
browser                                         Netlify
┌──────────────────────────────┐   HTTPS        ┌────────────────────────┐      ┌──────────────┐
│ app.js   (screens)           │  /cloud/chat   │ functions/atlas.mjs    │ ───► │ Groq, Gemini,│
│   │ fetch('/api/…')          │  /cloud/models │   lib/cloud.mjs        │      │ OpenRouter,  │
│ cloud.js (answers /api/*)    │ ─────────────► │ validate, rate limit,  │ ◄─── │ OpenAI       │
│ localStorage: memories, chat,│  /cloud/status │ forward with the       │      └──────────────┘
│   tasks, remembered key      │                │ visitor's own key      │
└──────────────────────────────┘                └────────────────────────┘
```

- `frontend/index.html`, `frontend/static/app.js`, `app.css`: the screens (Home, AI Chat, Tasks,
  Automations, Memory, Integrations, Devices, System). `theme.js` applies the saved theme before
  the page paints. Automations run in `app.js` every 30 seconds while the page is open. Plain JavaScript, no framework, no build step besides copying.
- `frontend/static/cloud.js`: loaded before `app.js`. It answers the app's `/api/*` calls in the
  browser: chat and model lists go to the function; tasks run in the page and are saved in
  localStorage; auto-switch between free providers happens here, so each key only ever travels to
  its own provider.
- `frontend/static/google.js`: loaded only on the Integrations screen. Google sign-in (Google
  Identity Services token client, read-only scopes) and GET calls to the Calendar and Gmail APIs,
  straight from the browser; the token stays in memory. The client ID comes from `dist/config.json`
  (build variable `ATLAS_GOOGLE_CLIENT_ID`) or is typed by the owner.
- `frontend/static/sw.js` and `manifest.webmanifest`: installable app and an offline shell. The
  service worker never caches `/cloud` replies.
- `netlify/lib/cloud.mjs`: the whole server side. Fixed provider URLs, input validation, output
  cap (2,048 tokens), cross-site and content-type checks, key redaction in errors, streaming.
- `netlify.toml`: build, function, rate limit (60 requests a minute per visitor) and security
  headers (strict CSP, no framing, nosniff).
- `scripts/netlify/build.mjs`: copies `frontend/` to `dist/`, adds `?v=<version>` to the script and
  style URLs, and writes `dist/version.json` for the update banner.

Why the `/api` shim: the screens were written against an API, and keeping that boundary lets the
screens stay simple and lets tests stub one place. See D-025 in `DECISIONS.md`.
