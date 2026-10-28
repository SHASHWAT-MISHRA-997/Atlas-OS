# ATLAS on Netlify

ATLAS is a web app that runs in any modern browser, on a phone, tablet or computer. It lives at
**https://atlas-os-sm.netlify.app**. It is the app in `frontend/` plus one small Netlify Function.

**Bring your own free key.** There is no sign-in. Each person adds their own free AI key using the
"Get your free AI key" card in AI Chat (Home shows a "Start here" banner until a key is added). The site owner's keys, Netlify environment variables and Netlify AI
Gateway credits are never used, so visitors cannot spend the owner's quota.

## What works

| Feature | Online | Notes |
|---|---|---|
| AI Chat (streaming, Stop, memories sent with each message) | Yes | Free cloud providers by default: Groq, Google Gemini, OpenRouter (free models only), with your own key; optional paid OpenAI; auto-switch between free providers on limits |
| Memory, chat history | Yes | Stored **in this browser only**. Another device starts empty. Memory → Export moves them |
| Tasks: plan a goal, summarize long text | Yes | Run while the page is open; saved in this browser. The key is held in memory for the task only |
| Home quick plan | Yes | Uses your key and the chat's model |
| Dictation and read-aloud | Yes | Chrome, Edge, Safari: the browser's speech service (in Chrome the audio goes to Google). Brave, Firefox: a short recording goes through `/cloud/transcribe` to your Groq or Gemini key. Read aloud: Gemini's natural voice through `/cloud/speak` with a Gemini key, otherwise the browser's voice |
| Live (real-time voice, turn by turn, camera, screen) | Yes | Real-time: straight from the browser to Google (Gemini key) or OpenAI (paid, after a tick). "Test my voice setup" checks each part |
| CSV workbench | Yes | In the browser |
| Install as an app | Yes | Android and desktop Chrome/Edge: "Install app". iPhone/iPad: Safari → Share → Add to Home Screen |
| Google Calendar and Gmail, read-only | Yes, once the owner sets a client ID | Today's and tomorrow's events, 10 latest unread emails (sender, subject). Straight from the browser to Google; token in memory only |
| Acting on a computer (apps, files), local models | **No** | A web page cannot do this safely. The PC version that could was removed in 0.15.0 (D-025) |

## Getting a free key

ATLAS offers providers with a free tier first, plus one optional paid provider (OpenAI, for models such as GPT-6 Astra), clearly marked "(paid)". There is no local model.

| Provider | Key page | Free part |
|---|---|---|
| Groq | https://console.groq.com/keys | Free tier with rate limits |
| Google Gemini | https://aistudio.google.com/apikey | Free tier with rate limits |
| OpenRouter | https://openrouter.ai/settings/keys | Only models whose ID ends in `:free` are listed |

Free limits are set by each provider and change. ATLAS cannot promise a provider stays free.

**Auto-switch:** when the chosen free provider answers "rate limit" (429) or is down (5xx), ATLAS sends the same message to the next free provider you saved a key for, and the reply names who answered. Each key still goes only to its own provider. It never switches into the paid provider. Turn it off in AI Chat → Model settings.

**Paid (optional):** OpenAI ([key page](https://platform.openai.com/api-keys)) has no free tier; every message is billed to your own OpenAI account. A paid Google key works with the Gemini provider and lists paid models such as Gemini 4 Argon.

1. Open AI Chat (or tap "Set up my free key" on Home).
2. In "Get your free AI key", choose a provider and tap "Open … key page".
3. Sign in (Google sign-in works), tap "Create API key" and copy it.
4. Come back, paste it and tap "Save key". ATLAS checks the key with the provider first; a rejected
   key is not saved and the provider's error is shown.

"Remember my key on this device" (ticked by default on the card) keeps the key in this browser
(localStorage); otherwise it is kept only until the page closes. To change or remove it later, open
AI Chat → Model settings, edit the key or untick "Remember".

## Where the key goes

The browser sends the key with each request to `/cloud/chat`, `/cloud/models`, `/cloud/speak` or
`/cloud/transcribe` over HTTPS. The function uses it for that one call to the provider's official address (fixed in
code; it cannot be pointed elsewhere) and does not store or log it. If a provider's error message
repeats the key, ATLAS replaces it with "[your key]" before showing it. Real-time voice is the
exception: the browser opens the WebSocket to Google or OpenAI itself, with the key in the URL
(Google) or as a WebSocket subprotocol (OpenAI), so the key does not pass through Netlify.

## Google Calendar and Gmail (read-only)

The browser signs in with Google Identity Services' token client (`https://accounts.google.com/gsi/client`,
loaded only on the Integrations screen) asking for `calendar.readonly` and `gmail.readonly`, then calls
the Calendar and Gmail APIs itself. The function is not involved. The token is kept in memory; Sign out
revokes it.

One-time setup by the site owner in Google Cloud Console:

1. Create a project, then **APIs & Services → Library**: turn on **Google Calendar API** and **Gmail API**.
2. **OAuth consent screen**: External, publishing status **Testing**; add your own Google account under
   **Test users**; add the scopes `.../auth/calendar.readonly` and `.../auth/gmail.readonly`.
3. **Credentials → Create credentials → OAuth client ID → Web application**; under **Authorised
   JavaScript origins** add `https://atlas-os-sm.netlify.app` (and `http://localhost:8888` for the local
   preview). No redirect URI is needed.
4. Copy the client ID (it ends in `.apps.googleusercontent.com`; it is public, not a secret) and either
   set it as the Netlify build variable `ATLAS_GOOGLE_CLIENT_ID` and redeploy, or paste it on the
   Integrations screen (saved in that browser only).

Set up for the live site on 2026-10-28 (project `atlas-os-513012`; the owner is the test user).

While the consent screen is in Testing mode only the listed test users can sign in, Google shows an
"unverified app" warning, and Google may ask to sign in again after 7 days.

## How it is built and deployed

- `netlify.toml`: build command `node scripts/netlify/build.mjs`, publish `dist/`, function in
  `netlify/functions/atlas.mjs` at `/cloud/*` (Netlify rate limit: 60 requests a minute per visitor).
- `scripts/netlify/build.mjs` copies `frontend/` into `dist/`, adds version numbers and writes
  `config.json` (the Google client ID from `ATLAS_GOOGLE_CLIENT_ID`, or null).
  `frontend/static/cloud.js` loads before `app.js` and answers the app's `/api/*` calls in the browser.
- `netlify/lib/cloud.mjs` is the whole server side: status, chat streaming, model lists (including
  real-time voice models), speech (`/speak`) and transcription (`/transcribe`).
- The GitHub repository is linked to the Netlify project, so every merge to `main` deploys.

Local preview: `npm install && npm run build && npm run dev`, then open http://localhost:8888 and
paste your key as on the live site.

## Limits

- No sync between devices.
- A reply must finish within Netlify's function time limit (about 60 seconds once streaming starts).
  Output is capped at 2,048 tokens per reply, input at 100,000 characters.
- A remembered key can be read by anyone using the unlocked device, and by any script running on the
  page (the strict CSP allows only this site's own scripts and Google's sign-in script).
