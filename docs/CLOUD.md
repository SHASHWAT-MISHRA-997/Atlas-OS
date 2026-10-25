# ATLAS online (Netlify)

The online version lets you use ATLAS from your phone without running anything on a PC. It is the
normal ATLAS app plus one Netlify Function. It lives at **https://atlas-os-sm.netlify.app**, which
belongs to the owner's Netlify account.

## What works online

| Feature | Online | Notes |
|---|---|---|
| AI Chat (streaming, Stop, memories sent with each message) | Yes | Real cloud model: Groq, Google Gemini, OpenAI or Anthropic Claude, whichever has a key |
| Memory, chat history | Yes | Stored **in this browser only** (localStorage). Another phone does not see them. Export from Memory |
| Tasks: plan a goal, summarize long text | Yes | Run while the page is open; saved in this browser |
| Home quick plan | Yes | Written by the cloud model |
| Dictation and read-aloud | Yes | Browser speech service (in Chrome the audio goes to Google) |
| CSV workbench | Yes | In the browser |
| Devices: pair another phone or laptop, remove it | Yes | One-time links that expire in 10 minutes |
| PC actions (apps, files, media keys, websites), document search, local Whisper/Piper, hands-free "Hey ATLAS", automations, Ollama | **No** | Need ATLAS installed on your Windows PC. The app says so instead of pretending |

## First use

1. Open the site on your phone. Press **Claim as owner**. The first device to claim becomes the
   owner; anyone else sees "This ATLAS is private".
2. Add one AI key (below). Until then the Home screen shows **Set up AI**.
3. To use another device, open **Devices** on the owner's phone, create a pairing link, and open it
   on the other device.

To stop strangers from claiming a fresh site first, the owner can also set `ATLAS_ACCESS_CODE` in
Netlify. The claim screen then asks for it.

## Adding an AI key

Keys are Netlify environment variables. They never go into the repository, the app or a chat.

1. Get a key. **Groq** (console.groq.com/keys) and **Google Gemini** (aistudio.google.com/apikey)
   both have free tiers. Free limits are set by the provider and change.
2. Netlify → project **atlas-os-sm** → Project configuration → Environment variables → Add a
   variable: `GROQ_API_KEY` (or `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`). Tick
   "Contains secret values", scope must include Functions.
3. Deploys → Trigger deploy. Reload ATLAS; the provider appears in AI Chat.

**Netlify AI Gateway.** On Netlify's credit-based plans, Netlify can inject OpenAI, Anthropic and
Gemini credentials itself. ATLAS then lists those providers as "(via Netlify AI Gateway)" and the
chat notice says the cost comes from the Netlify team's credits. A key you set yourself always wins.

## How it is built and deployed

- `netlify.toml`: build command `node scripts/netlify/build.mjs`, publish `dist/`, function in
  `netlify/functions/atlas.mjs` at `/cloud/*` (rate limit: 60 requests per minute per visitor).
- `scripts/netlify/build.mjs` copies `frontend/` into `dist/` and loads `frontend/cloud/cloud.js`
  before `app.js`. `cloud.js` answers the app's `/api/*` calls in the browser and sends chat to
  `/cloud/chat`.
- `netlify/lib/cloud.mjs` is the whole server side: owner claim, pairing, device list, chat
  streaming to the provider, model lists. Device records are one Netlify Blobs entry
  (`atlas-cloud` / `owner`) holding SHA-256 hashes of device tokens, never the tokens.
- Deploys happen when the repository is linked to the Netlify project (Netlify builds every push to
  `main`), or with `npx -y @netlify/mcp --site-id <id> --proxy-path <url>` from a machine that can
  reach Netlify.

Local preview without Netlify: `npm install && npm run build && GROQ_API_KEY=... npm run dev`, then
open http://localhost:8888.

## If you lose access

Clearing the browser removes the owner sign-in. To start over: Netlify → atlas-os-sm → Blobs →
store `atlas-cloud` → delete `owner`, then open the site and claim it again. This also signs out every
paired device.

## Limits

- Chat history and memories are per browser; there is no sync between devices yet.
- A chat reply must finish within Netlify's function time limit (about 60 seconds when streaming
  starts quickly). Output is capped at 2,048 tokens per reply.
- Not tested yet on a real Netlify deploy with a real key from this workspace; see
  `docs/FEATURE_MATRIX.md` for what is verified.
