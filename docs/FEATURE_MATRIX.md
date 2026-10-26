# Feature matrix

States: **Not implemented** · **Partially implemented** · **Implemented** (code exists, but its acceptance tests have not passed in the target environment) · **Verified** (acceptance tests passed in the environment named).

"Verified (Chromium, FAKE model)" means the browser tests passed in Chromium on Linux with the model provider replaced by a labelled fake. It is **not** evidence that a real provider, Safari or a real phone works.

Last updated: 2026-10-26 (v0.18.1). The PC version (backend, Windows installer, PC actions, local models, document search, local voice, device pairing) was removed in 0.15.0; its rows are in the Git history of this file.

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
| Live: voice loop, camera, screen share | `app.js` (`renderLive`) | Verified (Chromium, fake camera, FAKE model) for camera + typed question | Listening and speaking use browser speech APIs, which cannot run headless; screen sharing only exists in desktop browsers. Not tested on a real phone or iPad. Not streaming audio like Gemini Live |
| About the developer | `app.js` (`renderAbout`) | Verified (Chromium) | e2e checks the links |
| Key remembered after closing | `app.js` | Verified (Chromium) | e2e: card key and a key typed in Model settings survive closing the page |
| Auto-switch between free providers | `cloud.js` | Verified (Chromium, FAKE model) | e2e auto-switch test, including never into paid |
| Memory (browser), export | `app.js` | Verified (Chromium) | e2e; data stays in that browser |
| Tasks: plan, summarize | `cloud.js` | Verified (Chromium, FAKE model) | e2e Home plan; tasks run while the page is open |
| CSV analyzer | `app.js` | Implemented | In-browser parsing; no automated test |
| Dictation and read-aloud | `app.js` | Implemented | Browser speech APIs; not testable headless |
| Update banner and Check for update (System screen) | `app.js`, `version.json` | Verified (Chromium) | e2e update test |
| Rate limit, cross-site and content-type checks, key redaction | `netlify.toml`, `cloud.mjs` | Verified (Node) | `attack.test.mjs`, `cloud.test.mjs`; rate limit confirmed in the live deploy config |
| Size budget (first load under 80 KB gzipped) | `budget.test.mjs` | Verified (Node) | about 50 KB |
| Real provider end to end | — | Not verified | Needs the owner's own key on the live site |
| Automations (plans and reminders, in the browser) | `app.js` | Verified (Chromium) | e2e: create, Run now, missed run on reopen, delete. Runs only while ATLAS is open; notifications not tested on a real device |
| Devices: device info, export, import, erase | `app.js` | Verified (Chromium) | e2e: keys left out of export by default, import only takes `atlas.*` text items, erase |
| Dark and light theme | `theme.js`, `app.css` | Verified (Chromium) | e2e: switch, remembered after reload, Auto follows the device |
| Neon design, per-screen colours, transitions | `app.css` | Implemented | Checked by screenshots at 390, 1180 and 1440 px in both themes; motion off with "reduce motion" |
| Calendar, email, messaging, acting on a computer | — | Not implemented | Out of scope for a web page |
