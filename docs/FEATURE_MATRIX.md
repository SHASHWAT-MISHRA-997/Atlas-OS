# Feature matrix

States: **Not implemented** · **Partially implemented** · **Implemented** (code exists, but its acceptance tests have not passed in the target environment) · **Verified** (acceptance tests passed in the environment named).

"Verified (Chromium, FAKE model)" means the browser tests passed in Chromium on Linux with the model provider replaced by a labelled fake. It is **not** evidence that a real provider, Safari or a real phone works.

Last updated: 2026-10-28 (v0.25.0). The PC version (backend, Windows installer, PC actions, local models, document search, local voice, device pairing) was removed in 0.15.0; its rows are in the Git history of this file.

| Feature | Location | Status | Evidence / gap |
|---|---|---|---|
| Web app on any modern browser | `frontend/` | Verified (Chromium, FAKE model) | e2e at phone width; iPad sizes (744–1366 px) checked for overflow in Chromium with an iPad user agent. Not run in real Safari or on a real iPad |
| Install as an app (Android, desktop Chrome/Edge) | `sw.js`, `manifest.webmanifest` | Implemented | Install button appears on `beforeinstallprompt`; not tested on a real device |
| Install on iPhone and iPad | `app.js` | Implemented | Safari has no install prompt; the button shows "Share → Add to Home Screen". Not tested on a real device |
| Bring-your-own key, free providers first | `cloud.mjs`, key card in `app.js` | Verified (Chromium, FAKE model) | `cloud.test.mjs`; e2e key card, paste cleaning, wrong key rejected |
| Optional paid OpenAI | `cloud.mjs` | Verified (FAKE provider) | `paid OpenAI (optional) …`; never auto-selected |
| Streaming chat, Stop, Copy/Edit/Delete, Clear all | `app.js` | Verified (Chromium, FAKE model) | e2e chat test |
| Thinking level | `cloud.mjs`, `app.js` | Verified (FAKE provider, Chromium) | `cloud.test.mjs` checks each provider's request and the retry without thinking; e2e checks the setting reaches the request. Which real models accept it is up to the provider |
| Images and PDFs in chat | `cloud.mjs`, `app.js` | Verified (FAKE provider, Chromium) | Request shapes per provider, validation, and e2e attach/scale/send. Not tested with a real vision model or on iPad Safari's photo picker |
| Steering mid-reply | `app.js`, `cloud.js` | Verified (Chromium, FAKE model) | e2e: a held reply is redirected; Stop now cancels the request |
| Chat compression | `app.js` | Verified (Chromium, FAKE model) | e2e: a 20-message chat is summarized, only recent turns sent, Clear all removes the summary. Summary quality depends on the real model |
| Live, turn by turn: voice loop, camera, screen share | `app.js` (`renderLive`) | Verified (Chromium, fake camera, FAKE model) for camera + typed question | Listening and speaking use browser speech APIs, which cannot run headless; screen sharing only exists in desktop browsers. Not tested on a real phone or iPad |
| Live, real-time voice (Gemini Live API): mic streaming, spoken answers, interrupt, mute, 8 voices, camera/screen pictures, typed questions, reconnect | `realtime.js`, `live-worklet.js`, `app.js` (`renderLive`), `cloud.mjs` (live model list) | Verified (Chromium, fake mic and camera, FAKE Gemini Live server in the browser) for the message format, audio chunks, playback path, interrupt, mute, reconnect, text-only history and a bad-key message | **Not yet tested against Google's real Live API or on a real phone/iPad.** Needs the owner's Gemini key. Free keys have daily Live limits. On iPhone/iPad the voice may play quietly from the earpiece while the mic is on (a Safari behaviour) |
| Speech to text without a browser speech service (Brave, Firefox): Dictate and Live record a WAV and the user's Groq (Whisper) or Gemini key writes it down | `app.js` (`recordUtterance`, `transcribeSpeech`), `cloud.mjs` (`/transcribe`) | Verified (Chromium posing as Brave, fake microphone, FAKE transcription) and function tests for Groq and Gemini requests | Not yet tried with the owner's real key in Brave. OpenAI is used only when it is the chosen chat provider |
| Natural voice for spoken answers (Live turn by turn, Read aloud): Gemini speech models with the user's Gemini key, OpenAI only when chosen; otherwise the browser's most natural installed voice | `app.js` (`speakAloud`, `bestBrowserVoice`), `cloud.mjs` (`/speak`) | Verified with FAKE speech audio (e2e) and function tests for the Gemini and OpenAI requests | Not yet tried with the owner's real Gemini key; the browser voice choice depends on which voices the device has |
| Live, ChatGPT voice (OpenAI Realtime API, paid): same features; picture with each thing said; needs a tick that it is billed | `realtime.js`, `app.js`, `cloud.mjs` | Verified (Chromium, FAKE OpenAI Realtime server in the browser) for the paid tick, session settings, 24 kHz audio, key as WebSocket subprotocol, pictures, typed text, text-only history | **Not yet tested against OpenAI's real service.** Paid: billed per minute to the owner's OpenAI account |
| Test my voice setup (Live): real-time models, Gemini Live setupComplete, `/cloud/speak`, 1-second `/cloud/transcribe`, each PASS/FAIL/WARN/SKIPPED with the provider's words; Live errors name the failed step and what to do | `app.js` (`runVoiceCheck`, `failed`), `realtime.js` (`probe`, `ended` step) | Verified (Chromium, fake mic, FAKE Gemini Live server, FAKE speech and transcription) | e2e: all pass, all fail with exact provider text, a key Google refuses on the socket; cloud test: 1-second WAV accepted, provider words returned. **Not yet run against Google's or Groq's real services** |
| About the developer | `app.js` (`renderAbout`) | Verified (Chromium) | e2e checks the links |
| Key remembered after closing | `app.js` | Verified (Chromium) | e2e: card key and a key typed in Model settings survive closing the page |
| Auto-switch between free providers | `cloud.js` | Verified (Chromium, FAKE model) | e2e auto-switch test, including never into paid |
| Memory (browser), export | `app.js` | Verified (Chromium) | e2e; data stays in that browser |
| Tasks: plan, summarize | `cloud.js` | Verified (Chromium, FAKE model) | e2e Home plan; tasks run while the page is open |
| CSV analyzer | `app.js` | Implemented | In-browser parsing; no automated test |
| Dictation and read-aloud | `app.js` | Implemented | Browser speech APIs; not testable headless |
| Update banner and Check for update (System screen) | `app.js`, `version.json` | Verified (Chromium) | e2e update test |
| Rate limit, cross-site and content-type checks, key redaction | `netlify.toml`, `cloud.mjs` | Verified (Node) | `attack.test.mjs`, `cloud.test.mjs`; rate limit confirmed in the live deploy config |
| Size budget (first load under 80 KB gzipped) | `budget.test.mjs` | Verified (Node) | 69.6 KB at v0.24.0; Live (`realtime.js`) and Google (`google.js`) code loads only on their screens |
| Real provider end to end | — | Not verified | Needs the owner's own key on the live site |
| Automations (plans and reminders, in the browser) | `app.js` | Verified (Chromium) | e2e: create, Run now, missed run on reopen, delete. Runs only while ATLAS is open; notifications not tested on a real device |
| Devices: device info, export, import, erase | `app.js` | Verified (Chromium) | e2e: keys left out of export by default, import only takes `atlas.*` text items, erase |
| Dark and light theme | `theme.js`, `app.css` | Verified (Chromium) | e2e: switch, remembered after reload, Auto follows the device |
| Neon design, per-screen colours, transitions | `app.css` | Implemented | Checked by screenshots at 390, 1180 and 1440 px in both themes; motion off with "reduce motion" |
| Google Calendar and Gmail, read-only: today's and tomorrow's events, 10 latest unread (sender, subject), Sign out revokes | `google.js`, `app.js` (`googlePanel`), `build.mjs` (`config.json`), `netlify.toml` (CSP, COOP) | Verified (Chromium, FAKE Google sign-in script and FAKE Calendar/Gmail APIs) | e2e: client ID check, read-only scopes, only GETs with the token, metadata only, refused sign-in, expired token, revoke, nothing stored; cloud test: CSP hosts, no client ID in code, function is no proxy. **Not yet tried with Google's real sign-in or APIs**; needs the owner's OAuth client ID. Main calendar only |
| Sending email or messages, changing calendar events, acting on a computer | — | Not implemented | ATLAS only reads Google data |
