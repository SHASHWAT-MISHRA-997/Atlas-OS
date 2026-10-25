# ATLAS online (Netlify)

The online version lets anyone use ATLAS from a phone without running anything on a PC. It lives at
**https://atlas-os-sm.netlify.app**. It is the normal ATLAS app plus one small Netlify Function.

**Bring your own free key.** There is no sign-in. Each person adds their own free AI key using the
"Get your free AI key" card in AI Chat (Home shows a "Start here" banner until a key is added). The site owner's keys, Netlify environment variables and Netlify AI
Gateway credits are never used, so visitors cannot spend the owner's quota.

## What works online

| Feature | Online | Notes |
|---|---|---|
| AI Chat (streaming, Stop, memories sent with each message) | Yes | Free cloud providers only: Groq, Google Gemini, OpenRouter (free models only), with your own key |
| Memory, chat history | Yes | Stored **in this browser only**. Another phone starts empty. Memory → Export moves them |
| Tasks: plan a goal, summarize long text | Yes | Run while the page is open; saved in this browser. The key is held in memory for the task only |
| Home quick plan | Yes | Uses your key and the chat's model |
| Dictation and read-aloud | Yes | Browser speech service (in Chrome the audio goes to Google) |
| CSV workbench | Yes | In the browser |
| PC actions (apps, files, media keys, websites), document search, local Whisper/Piper, hands-free "Hey ATLAS", automations, device pairing | **No** | Need ATLAS installed on your Windows PC. The app says so instead of pretending |

## Getting a free key

The online version offers only providers with a free tier. There is no Ollama or local model online.

| Provider | Key page | Free part |
|---|---|---|
| Groq | https://console.groq.com/keys | Free tier with rate limits |
| Google Gemini | https://aistudio.google.com/apikey | Free tier with rate limits |
| OpenRouter | https://openrouter.ai/settings/keys | Only models whose ID ends in `:free` are listed |

Free limits are set by each provider and change. ATLAS cannot promise a provider stays free.

1. Open AI Chat (or tap "Set up my free key" on Home).
2. In "Get your free AI key", choose a provider and tap "Open … key page".
3. Sign in (Google sign-in works), tap "Create API key" and copy it.
4. Come back, paste it and tap "Save key". ATLAS checks the key with the provider first; a rejected
   key is not saved and the provider's error is shown.

"Remember my key on this phone" (ticked by default on the card) keeps the key in this browser
(localStorage); otherwise it is kept only until the page closes. To change or remove it later, open
AI Chat → Model settings, edit the key or untick "Remember".

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
