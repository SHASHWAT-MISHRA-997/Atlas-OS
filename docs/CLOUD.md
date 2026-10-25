# ATLAS online (Netlify)

The online version lets anyone use ATLAS from a phone without running anything on a PC. It lives at
**https://atlas-os-sm.netlify.app**. It is the normal ATLAS app plus one small Netlify Function.

**Bring your own key.** There is no sign-in. Each person pastes their own AI provider key in
AI Chat → Model settings. The site owner's keys, Netlify environment variables and Netlify AI
Gateway credits are never used, so visitors cannot spend the owner's quota.

## What works online

| Feature | Online | Notes |
|---|---|---|
| AI Chat (streaming, Stop, memories sent with each message) | Yes | Groq, Google Gemini, OpenRouter, OpenAI or Anthropic Claude, with your own key |
| Memory, chat history | Yes | Stored **in this browser only**. Another phone starts empty. Memory → Export moves them |
| Tasks: plan a goal, summarize long text | Yes | Run while the page is open; saved in this browser. The key is held in memory for the task only |
| Home quick plan | Yes | Uses your key and the chat's model |
| Dictation and read-aloud | Yes | Browser speech service (in Chrome the audio goes to Google) |
| CSV workbench | Yes | In the browser |
| PC actions (apps, files, media keys, websites), document search, local Whisper/Piper, hands-free "Hey ATLAS", automations, Ollama, device pairing | **No** | Need ATLAS installed on your Windows PC. The app says so instead of pretending |

## Getting a key

Groq (https://console.groq.com/keys), Google Gemini (https://aistudio.google.com/apikey) and some
OpenRouter models (IDs ending in `:free`) have free tiers. OpenAI and Anthropic are paid per use.
Free limits and prices are set by each provider and change.

In AI Chat → Model settings, pick the provider, paste the key, and press Load models. Tick
"Remember my key on this phone" to keep it in this browser (localStorage); otherwise it is kept only
until the page closes. Untick it to remove the saved key.

## Where the key goes

The browser sends the key with each chat or model-list request to `/cloud/chat` or `/cloud/models`
over HTTPS. The function uses it for that one call to the provider's official address (fixed in
code; it cannot be pointed elsewhere) and does not store or log it. If a provider's error message
repeats the key, ATLAS replaces it with "[your key]" before showing it.

## How it is built and deployed

- `netlify.toml`: build command `node scripts/netlify/build.mjs`, publish `dist/`, function in
  `netlify/functions/atlas.mjs` at `/cloud/*` (Netlify rate limit: 60 requests a minute per visitor).
- `scripts/netlify/build.mjs` copies `frontend/` into `dist/` and loads `frontend/cloud/cloud.js`
  before `app.js`. `cloud.js` answers the app's `/api/*` calls in the browser.
- `netlify/lib/cloud.mjs` is the whole server side: status, chat streaming and model lists.
- The GitHub repository is linked to the Netlify project, so every merge to `main` deploys.

Local preview: `npm install && npm run build && npm run dev`, then open http://localhost:8888 and
paste your key as on the live site.

## Limits

- No sync between devices.
- A reply must finish within Netlify's function time limit (about 60 seconds once streaming starts).
  Output is capped at 2,048 tokens per reply, input at 100,000 characters.
- A remembered key can be read by anyone using the unlocked phone, and by any script running on the
  page (the strict CSP allows only this site's own scripts).
