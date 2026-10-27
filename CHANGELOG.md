# Changelog

## 0.25.1 — 2026-10-28

Task 3 of the owner's list: housekeeping.
- Removed `ATLAS_OS_Research_Starter_v4.zip` from `main` (a normal commit; it stays in the Git history).
- docs/HANDOFF.md brought up to date: the date, the owner now sometimes uses a Windows PC with Brave, the test counts (32 function and 15 browser tests at v0.22.1; 34 and 17 now), and how to run the secret scan on Windows.
- Stale claims fixed: ARCHITECTURE (was v0.15.0; now covers Live, real-time voice, the speech and transcription routes and Google), CLOUD (dictation in Brave/Firefox, Live, which routes carry the key), README (voice), SECURITY (sign-in), THREAT_MODEL (T11, T36), FEATURE_MATRIX (dictation row, size), PROJECT_AUDIT (zip). The Integrations "Voice and Live" tile no longer says everything uses the browser's speech service.

## 0.25.0 — 2026-10-28

Task 2 of the owner's list: Live voice hardening.
- **Test my voice setup** (Live screen). Runs each part of voice on its own and shows PASS, FAIL, WARN or SKIPPED with the provider's exact words and what to do: (1) list the real-time models your Gemini key can use, (2) open the Gemini Live connection and wait for Google's `setupComplete` (no microphone), (3) speak a test sentence through `/cloud/speak` and play it, (4) record one second from the microphone and write it down through `/cloud/transcribe`. A step without its key is skipped with the reason; one failing step does not stop the others.
- **Every Live error names the step that failed, the service's own words, and what to do**, for example "Connecting to Google Gemini (model) failed: API key not valid… What to do: check your Gemini key…". Covers finding a real-time model, the microphone, starting audio, connecting, a dropped conversation, listening, writing down speech, getting an answer, speaking, the camera and screen sharing.
- Fix: provider errors that already ended in a full stop showed two ("details..").
- **Not yet tried against Google's or Groq's real services**; the tests use a FAKE Gemini Live server and FAKE speech and transcription.

## 0.24.0 — 2026-10-28

Task 1 of the owner's list: Calendar and Gmail.
- **Google Calendar and Gmail, read-only** (Integrations). Sign in with Google and ATLAS shows today's and tomorrow's events on your main calendar and the sender and subject of your 10 latest unread emails. It asks Google only for `calendar.readonly` and `gmail.readonly`, reads only email headers (never the message text), and never sends, deletes or changes anything.
- The sign-in uses Google Identity Services' token client, loaded only when Integrations opens (`google.js`). The access token stays in the page's memory: it is never stored, never sent to ATLAS's server or an AI model, and closing the page forgets it. **Sign out** asks Google to revoke it.
- It needs a Google OAuth client ID that the site owner creates (see docs/CLOUD.md). It is never in the code: the owner sets the Netlify build variable `ATLAS_GOOGLE_CLIENT_ID` (written to `/config.json`) or pastes it on the Integrations screen.
- Clear messages when sign-in is refused (Testing mode allows only test users), the pop-up is blocked or closed, an API is not turned on, or the sign-in expires.
- Security headers: the CSP now allows Google's sign-in script and frame, `www.googleapis.com/calendar/v3/`, `gmail.googleapis.com/gmail/v1/` and `oauth2.googleapis.com/revoke`; `Cross-Origin-Opener-Policy` is `same-origin-allow-popups` so Google's sign-in pop-up can report back. The local preview server now reads the CSP from `netlify.toml`.
- Messaging stays "Not yet".
- Version 0.23.0 is left for the open PC-control pull request.
- **Not yet tried against Google's real sign-in or APIs**; the tests use a FAKE Google sign-in script and FAKE Calendar and Gmail answers.

## 0.22.1 — 2026-10-27

The owner said the Live mode did not work properly:
- **Fix: Live modes looked broken.** Modes without a key were greyed out and could not be picked, with no reason shown. Now every mode can be picked, and one that is not ready says what it needs ("· add key") and shows a key box right on the Live screen: paste a free Gemini key (or an OpenAI key for ChatGPT voice), press Save key, and the mode is ready. AI Chat keeps its provider (for example Groq).
- In Turn by turn without a Gemini key, the same box offers (optionally) a Gemini key for the natural voice.

## 0.22.0 — 2026-10-27

The owner said the spoken answers sounded robotic, not like ChatGPT or Gemini:
- **Natural voice for spoken answers.** With a Google Gemini key, Live turn by turn and Read aloud in AI Chat now speak in Gemini's own natural voices (the same 8 voices as real-time Live, picked on the Live screen), even when Groq writes the answer. Long answers are spoken in pieces, the next one prepared while the current one plays. OpenAI's voice is used instead only when OpenAI is your chosen provider (paid).
- The answer text goes to Google (or OpenAI) with your key to be spoken; nothing is stored. Markdown, code and links are not read out.
- **Without such a key**, ATLAS now picks the most natural voice your browser has (for example "Natural" or "Google" voices, Indian English for Hinglish, Hindi for Devanagari) instead of the default one. Browser voices can still sound robotic, Brave's especially; a free Gemini key is the real fix.
- If the natural voice fails (for example a used-up free quota), the browser voice reads the answer and the status line says why.
- **Not yet tried against Google's real speech models**; the tests use FAKE audio.

## 0.21.0 — 2026-10-27

From the owner's test on a Windows PC in Brave:
- **Fix: Dictate failed in Brave** ("speech service could not be reached"). Brave has the speech API but no service behind it, and Firefox has none. ATLAS now records what you say and your own key writes it down: Whisper on Groq (free) or Gemini (free); OpenAI only if it is your chosen chat provider. Chrome, Edge and Safari still use their own speech service, and switch over by themselves if it fails.
- **Fix: Live turn by turn kept listening without hearing anything in Brave.** It uses the same recording, with the orb following your voice.
- **Fix: Live talked about "attached images" when there was none.** The image note goes to the model only with a picture.
- **Compress** is greyed out until the chat is long enough, and shows how far along it is (for example "Compress (3/9)"), instead of looking broken.
- Calendar, email and messaging are still "Not yet": they need a Google sign-in app that the owner registers first.

## 0.20.0 — 2026-10-26

The owner asked for ChatGPT's voice too:
- **ChatGPT voice in Live (paid, optional).** With your own OpenAI key, Live has a third mode, "ChatGPT (paid)", using OpenAI's Realtime API (the voice technology behind ChatGPT): streaming speech both ways, talk over it to interrupt, 10 OpenAI voices, typed questions, and with the camera or screen on the current picture goes with each thing you say. Text of both sides is saved to AI Chat history.
- It is never chosen for you: it starts only after you tick that every minute is billed to your OpenAI account. The free Gemini real-time mode stays the default when you have a Gemini key.
- The browser connects straight to `wss://api.openai.com` with your key; the site's CSP allows that one address.
- **Not yet tried against OpenAI's real service**; the browser test uses a FAKE OpenAI Realtime server.

## 0.19.0 — 2026-10-26

From the owner's request for a voice experience "exact same" as Gemini and ChatGPT:
- **Live real-time voice (with a Google Gemini key).** Uses Google's Gemini Live API, the same streaming voice service behind the Gemini app's Live mode: the microphone streams continuously, Gemini answers in its own natural voice (8 voices to pick from, remembered), and you can talk over it to interrupt. The camera or a shared screen sends about one picture a second while Live is on. Typed questions are answered aloud. Mute keeps the session open. Google ends each connection after a few minutes; Live carries on in a new one with the same conversation. What you said and what Gemini said are written on screen and saved to AI Chat history as text (never the audio or pictures).
- The browser talks straight to Google (`wss://generativelanguage.googleapis.com`) with your own Gemini key; ATLAS's server only looks up which real-time models your key has. The site's CSP now allows that one address.
- Without a Gemini key, Live works turn by turn as before (any provider). A Mode switch picks between the two.
- ChatGPT's voice mode (OpenAI Realtime API) is not added: it needs a paid OpenAI key and ATLAS never turns on paid services by itself.
- Live's text box and menus now use the app's styling.
- **Not yet tried against Google's real service or on a real phone**; the browser test uses a FAKE Gemini Live server.

## 0.18.1 — 2026-10-26

From the owner's feedback ("Home page mai duplicates and copy dikh rahe hai"):
- **Fix: Home title showed copies of itself.** A decorative "glitch" effect drew two coloured copies of "What should we get done?" over the title; on phones the copies did not line up and looked like duplicated text. Removed, together with the blurred glow behind "get done?". The same effect is gone from the name on About.
- Repeated wording removed: the plan's model name was shown twice (badge and note), the badge now just says PLAN READY. The intro line no longer repeats the "never executed" note that the plan card already gives.
- Overview numbers show 0, 1, 2 instead of 00, 01, 02.

## 0.18.0 — 2026-10-26

From the owner's feedback on the phone:
- **Live** (new screen): a hands-free conversation like a phone assistant. Tap the orb: ATLAS listens, answers aloud, then listens again; tap while it speaks to interrupt. Turn on the camera (front or back) or, on a computer, share the screen, and the current picture goes with each question so the model can see it. A text box works where the browser cannot listen. It uses the AI Chat provider, model and key; turns also appear in AI Chat history (text only). It is turn by turn through the browser's speech service, not Gemini Live's streaming audio, so there is a short pause before each answer.
- **About the developer** (new screen): Shashwat Mishra, with portfolio, LinkedIn, GitHub and YouTube links and the SMARAN.AI projects.
- **Fix: key forgotten after closing the app.** A key typed into Model settings was kept for that visit only, because its "Remember my key" tick started off. New keys are now remembered unless the tick is cleared, and ATLAS asks the browser to keep its storage.
- **Fix: Auto-switch could not be turned off from Integrations.** The tile now has a Turn off / Turn on switch (the same setting as in AI Chat).
- Integrations explains why calendar and email are not connected yet.
- The site now allows the camera and screen capture for its own page only (`Permissions-Policy`).

## 0.17.0 — 2026-10-26

The last items from the feature plan, for AI Chat:
- **Thinking level:** Auto, Low, Medium or High in Model settings. Groq and OpenAI get `reasoning_effort`, OpenRouter its `reasoning` field, Gemini a thinking budget, with extra output room for the thinking. A model that cannot think gets the same message again without the setting, and the reply says "thinking: not supported by this model".
- **Images and PDFs:** an Attach button (up to 4 files, about 3 MB in total). Images are scaled down to 1568 px JPEG in the browser; PDFs go as they are to Gemini, OpenRouter or OpenAI (Groq cannot read PDFs and says so before sending). Files go only with their own message; history keeps only their names, never the file.
- **Steering:** while a reply is coming, the Send button becomes Steer. A new message stops the reply (its text so far is kept, marked "Redirected by your next message") and is answered at once.
- **Chat compression:** once more than 16 messages (or about 24,000 characters) are not yet summarized, the older ones are summarized by the same model before the next message, and only the summary plus the newest turns are sent. A Compress button does it on demand; the summary can be read above the chat and is removed by Clear all or by deleting a message it covers. History now keeps 60 messages.
- **Fix:** Stop did not cancel the request online (the browser shim dropped the abort signal), so a stopped reply kept downloading. It now cancels the request to the provider.
- The function accepts chat bodies up to 5 MB (model listing stays at 20 KB) and checks every file's type and base64.

## 0.16.1 — 2026-10-25

- The "Describe a task to plan" box in the top bar showed on every screen. It is removed; plans are made from the goal box on Home (and from the Tasks screen).

## 0.16.0 — 2026-10-25 (branch `atlas/cyber-ui`)

Redesign the owner asked for: every screen looked and worked the same, status, refresh and update were all in one corner, there was no light theme, and no effects or motion.
- **Neon cyberpunk look:** a moving perspective grid, drifting neon glows and scanlines in the background; glass panels with HUD corner brackets; neon buttons with a shine sweep; a glitch effect on the Home title now and then; a typing cursor while a reply streams.
- **Dark and light theme:** a switch in the top bar (phone) or sidebar, and Dark / Light / Auto on the System screen. The choice is applied before the page paints (`theme.js`), so it never flashes.
- **Every screen is different:** its own colour (Home cyan, AI Chat magenta, Tasks green, Automations orange, Memory violet, Integrations blue, Devices teal, System yellow), its own header with icon and a "decrypting" title, and its own layout (terminal-style chat, task form beside the task list, memory cards, integration tiles, automation timeline).
- **Screen transitions:** each screen wipes in and its parts rise in one after another. "Reduce motion" turns all of this off.
- **System screen (new):** status tiles (connection, version, AI keys, data, offline shell, app), Check for update, Refresh status, Install app, theme, and the activity log. The sidebar keeps one small status chip.
- **Automations (back, as a web version):** plans and reminders every day, every week, every few hours or once. They run while ATLAS is open in the browser; a missed run happens once when ATLAS opens again. Reminders can use system notifications.
- **Devices (back, as a web version):** what this device is, how much ATLAS stores, export everything to a file (AI keys left out unless you tick it), import on another device, ask the browser to keep the data, and erase ATLAS from the device.
- Tests: 33 pass (new browser tests for the theme, automations and devices).

## 0.15.0 — 2026-10-25 (branch `atlas/universal-web`)

ATLAS is now one web app for every device. The owner asked for a universal web app instead of separate Windows, Android, Linux and Mac versions, and chose to delete the PC version.
- **Removed the PC version:** the FastAPI backend and its tests, the Windows installer, the Docker image, and the Windows, backend, Docker and backend browser CI jobs. It is still in the Git history.
- **Removed PC-only parts of the app:** PC actions, local models (Ollama), document search, local Whisper/Piper voice, hands-free "Hey ATLAS", device pairing, and the placeholder Agents and Projects screens. Automations and Devices will come back as browser versions in the redesign.
- **iPhone and iPad:** "Install app" now shows how to add ATLAS from Safari's Share menu (Safari has no install prompt). The app is no longer locked to portrait. Text says "this device" instead of "this phone". Layout checked at four iPad sizes in Chromium with no sideways scrolling; not yet on a real iPad.
- `cloud.js` and its styles are part of the normal app now (`frontend/static/`); the build only adds version numbers.
- CI is one job, `cloud`: syntax check, build, function, attack, size and browser tests, `npm audit` and a secret scan.
- Docs rewritten for the web app: README, ARCHITECTURE, FEATURE_MATRIX, TEST_PLAN, THREAT_MODEL, SECURITY, CONTRIBUTING, HANDOFF; decision D-025.

## 0.14.0 — 2026-10-25 (branch `atlas/auto-route`)

Online version:
- **Auto-switch between free providers (like an AI gateway such as OmniRoute).** If the chosen provider hits its free limit (HTTP 429) or is down (5xx), the same message goes to the next free provider you added a key for, and the reply says so (for example "OpenRouter (auto-switched: Groq hit its free limit)").
  - It is on by default and can be turned off in Model settings.
  - Each key is still sent only to its own provider, in its own request.
  - It never switches into a paid provider.
- **Optional paid OpenAI key (for GPT-6 Astra).** The owner chose to offer paid keys as an option.
  - OpenAI is listed last as "OpenAI (paid)". Its key card warns that there is no free tier and every message is billed to the visitor's own account.
  - It is never a default, never shown in the "free key" banner, and never used by auto-switch or by Home plans unless the visitor picked it.
  - Requests use OpenAI's `max_completion_tokens`, capped at 2,048.
  - A paid Google key works with the existing Gemini provider and lists paid models such as Gemini 4 Argon.
- Tests:
  - The browser test covers the auto-switch, turning it off, and never switching into paid.
  - The function tests cover the OpenAI request shape.
  - The attack tests include the OpenAI host.

## 0.13.3 — 2026-10-25 (branch `atlas/security-pass`)

Security pass: I attacked the app myself, then fixed what got through. Every attack is now a test.
- Online function, four gaps fixed:
  - Requests from other websites (browser `Sec-Fetch-Site` cross-site, or a foreign `Origin`) now get 403.
  - Only `application/json` is accepted (415), so HTML forms on other sites cannot post.
  - A provider sent as an array (`["groq"]`) was accepted; it now must be a string.
  - JSON and stream replies now carry `X-Content-Type-Options: nosniff`.
  - Oversized bodies are also refused from `Content-Length` before reading.
- New `netlify/tests/attack.test.mjs` (9 tests) tries:
  - header injection through the key;
  - proxying to other hosts and paths through model IDs;
  - prototype tricks;
  - smuggling tools, roles or base URLs;
  - cross-site calls and form posts;
  - huge and deeply nested bodies;
  - leaking the key in errors.
  It runs in CI.
- New browser test: HTML/script in a memory and in a chat reply never runs, and a prompt-injection message cannot get the key, because the key is never put into the prompt.
- New `backend/tests/test_attack_sqli.py`: 11 SQL injection payloads against 10 storage endpoints on the PC app. No errors, no leaked rows, no changed tables.
- Rate limit unchanged and confirmed in the live deploy: 60 requests a minute per visitor (Netlify), output capped at 2,048 tokens. The PC API keeps its own LLM rate limit (`test_llm_rate_limit_returns_429_with_retry_after`).
- Threat model: T36 corrected (3 provider hosts), T38 (cross-site) and T39 (injection) added.

## 0.13.2 — 2026-10-25 (branch `atlas/update-notify`)

- Update notice (PC app and online): when a newer version is deployed, a "New version available" banner appears with "Update now" (reloads into the new version) and "Later". The app checks on open, when it comes back on screen (at most every 5 minutes) and every 30 minutes. It only works while the app is open; there are no push notifications.
- "Check for update" button in the menu (under system status) says either that a version is available or "You have the latest version (x.y.z)".
- Online the version comes from a new `/version.json` written by the Netlify build (served with `Cache-Control: no-cache`); on the PC it comes from `/health`.
- Model choice: once models are loaded they are shown as a dropdown with every model the key can use (OpenRouter: free ones only), plus "Other: type a model ID". Before, a text box with suggestions showed only the one pre-filled model on phones.
- Tests: cloud e2e covers the update banner, Check for update and the model dropdown; local UI tests type custom model IDs through "Other".

## 0.13.1 — 2026-10-25 (branch `atlas/key-paste`)

Chat messages can now be managed (PC app and online):
- Every saved message has Copy and Delete; your own messages also have Edit, which puts the text back in the message box and removes the replies after it, so you can change it and send again. Each asks before deleting.
- The "Clear" button is now "Clear all".
- New backend route `DELETE /api/chat/history/{id}` (`?following=true` also removes later messages). Browser-stored messages get ids; older ones are given ids on first load.

Online version: easier to add your key on a phone.
- The key box is now a plain text box (phone keyboards hide clipboard suggestions in password boxes) with a "Paste" button. If the browser blocks clipboard reading, it says to press and hold the box and tap Paste.
- Pasted keys are cleaned: spaces, line breaks, quotes and invisible characters are removed.
- If the provider rejects a key that looks like another provider's (for example a `gsk_` Groq key under Gemini), the card says which provider to pick.
- Friendlier error texts; the Tasks screen no longer asks for models online before a key exists.
- Browser test pastes a messy key and checks it is cleaned and saved, then deletes, edits and clears messages. A backend test covers the new delete route.

## 0.13.0 — 2026-10-25 (branch `atlas/redesign`)

Redesign (both the PC app and the online version):
- New logo: an "A" with an orbit ring on a violet tile. New app icons (PWA, Apple touch, maskable) made from it.
- Calmer theme: flat dark surfaces, one violet accent, no grid background or glows, consistent spacing and type sizes.
- Simpler Home: goal box and plan first, then a short overview. The CSV analyzer and activity log fold away. The "agents" and "execution principles" blocks were removed from Home.
- Phones: no boxes inside boxes, opaque chat composer, one-row chat buttons without emoji (some Android fonts cut them off).
- Online: until a key is added, AI Chat shows only the key card; Agents and Projects (not built yet) are hidden from the menu.
- Tests: a browser-test fixture now blocks the service worker so faked endpoints are always used; one selector follows the new layout. All suites pass; the look was checked from phone and desktop screenshots in Chromium, not on a real phone.

## 0.12.0 — 2026-10-25 (branch `atlas/free-keys`)

Online version (Netlify):
- Only free cloud providers: Groq, Google Gemini and OpenRouter (free `:free` models only). OpenAI and Anthropic were removed online.
- New "Get your free AI key" card in AI Chat: pick a provider, open its key page, paste the key, Save. The key is checked with the provider before it is saved.
- Home shows a "Start here: get a free AI key" banner with direct links until a key is added.
- No Ollama or local-model text in the online app (Home stat is now "Your AI keys"; Integrations and Chat texts updated).
- A rejected key (401/403, or Gemini's "API key not valid") is now reported when listing models instead of falling back to a suggested model.
- Chat composer background is fully opaque so text behind it no longer shows through on phones.
- Tests: 13 function tests and the phone browser test updated (fake model, labelled FAKE). No real provider call has been made from this workspace.

## 0.11.0 — 2026-10-25 (branch `atlas/byok`)

### Changed
- **ATLAS online now uses each visitor's own API key.** There is no sign-in, owner claim or pairing any more. Each person pastes their key in AI Chat → Model settings, and can tick "Remember my key on this phone". The function never reads Netlify environment variables or Netlify AI Gateway credentials, so the site owner's keys and credits are never used.
- Providers online: Groq, Google Gemini, OpenRouter (new), OpenAI and Anthropic, always at their official addresses.
- Provider error messages that repeat the key show "[your key]" instead.
- Tasks keep the key in memory for that task only; it is never saved with the task.

### Removed
- Netlify Blobs device records, the claim screen, the "Set up AI" card and the `@netlify/blobs` dependency.

## 0.10.0 — 2026-10-25 (branch `atlas/cloud`)

### Added
- **ATLAS online on Netlify** (`netlify.toml`, `netlify/`, `frontend/cloud/`, `docs/CLOUD.md`). Use ATLAS from a phone with no PC: AI Chat with a real cloud model (Groq, Gemini, OpenAI or Claude; key set in Netlify, never in the app), memory and chat history in the browser, plan and summarize tasks, Home quick plan, and device pairing.
- Owner sign-in for the online version: the first device claims it (optionally with an access code), other devices join with one-time links, and the owner can remove them. Only token hashes are stored.
- A "Set up AI" card explains how to add a key in Netlify when none is set.
- Node tests for the function (17) and browser tests for the online version (2), with a labelled FAKE model. New `cloud` CI job.

### Changed
- In the online version, PC-only features (PC actions, document search, local voice, hands-free, automations) say they need ATLAS on the PC instead of showing PC settings.
- The service worker never caches `/cloud/` responses.

## 0.9.0 — 2026-10-25 (branch `atlas/v0.9`)

### Added
- **Hands-free "Hey ATLAS"** (opt-in): say "Hey ATLAS" and your request; ATLAS listens only while the chat is open and only with speech-to-text on your PC.
- **Read-aloud on your PC** with Piper voices (English US/UK, Hindi), downloaded only when you press Download.
- **Microphone choice** for dictation on the PC and hands-free.
- **Browser control:** "Open a website" and "Search the web" PC actions, with approval. Only public http(s) pages.
- **Automations:** run a plan, re-index, web search or website on a schedule (daily, weekly, every few hours).
- **Fallback model** (opt-in): if the chosen model fails, another one the owner set up can answer, and the answer says so.
- 17 more red-team cases (67 in total).

### Changed
- The Home quick plan now asks your local model for a real plan. The fixed example plan is used only when no model is installed.

### Fixed
- Voice recordings over 256 KB (about 30 seconds) were refused before they reached speech-to-text on the PC.


## 0.8.0 — 2026-10-25 (branch `atlas/v0.8`)

### Added
- **Document search.** An approved "Index documents" PC action reads .txt, .md, .csv, .pdf and .docx files in an approved folder into a local full-text index. Memory → Documents searches or clears it. In chat, "Use my documents" sends matching excerpts with your message and lists the source files under the answer. A warning shows when the provider is a cloud one.
- **Writing files, safely.** New PC actions: create a note (.txt or .md), create a Word or Excel file, move a file to ATLAS trash, and restore it. ATLAS never overwrites a file and never deletes one permanently.
- **Media keys** (play/pause, next, previous, volume, mute) as an approved action on Windows.
- **Local speech-to-text (optional).** Pick "ATLAS on this PC" as the dictation engine. After `pip install -r requirements-voice.txt`, the owner can download a Whisper model (tiny, base or small) from the PC; audio is transcribed on the PC and not stored.
- **Windows installer:** `scripts/windows/install.ps1`, with `-StartOnLogin` and `-RemoveStartOnLogin`. CI runs it on Windows.
- 20 more red-team cases (50 in total) for writing, trash, indexing and search.

### Changed
- Approval cards for restore show the file's original place, not just an id.
- File names that Windows reserves for devices (`CON`, `NUL`, `COM1`…) are refused.


## 0.7.0 — 2026-10-25 (branch `atlas/v0.7`)

### Added
- Installable app (PWA): manifest, icons, and a service worker that shows the app shell when the PC is offline. It never caches `/api` data.
- Pairing QR code when the link's address is known, and a Wi-Fi address hint when it is not.
- Each chat answer lists exactly which saved memories were sent. Memories that share words with the message are sent first.
- Opt-in auto-delete for chat history and memories after 7, 30, 90 or 365 days (Memory screen, `/api/storage/retention`).
- Voice: choose the speech language (English India, US or UK, Hindi) and the read-aloud voice. Voices are labelled on-device or online, and microphone errors are clearer.
- `python -m app.serve`, with optional HTTPS (`ATLAS_TLS_CERT`, `ATLAS_TLS_KEY`), and `docs/REMOTE_ACCESS.md`.
- Research write-up (`docs/RESEARCH.md`), a latency benchmark (`backend/research/bench_latency.py`) and 30 red-team cases (`tests/test_redteam_actions.py`).
- Accessibility checks with axe-core on every screen, and contrast tests for gradient buttons.

### Fixed
- **Security:** a tunnel or reverse proxy on the PC (Tailscale Serve, cloudflared, nginx) made every visitor the owner. The owner login now needs direct same-computer access.
- **Security:** paired devices could open apps through `/api/desktop/launch` without an approval. It is now owner-only.
- Every chat message waited about 49 ms because a TLS context was rebuilt per request. ATLAS's overhead is now about 6 ms.
- Main buttons had 3.3:1 text contrast; they now meet WCAG AA (5.1:1 or better).
- The More sheet now moves keyboard focus inside and returns it on close, and the page behind is inert.
- The chat status line is visible on phones again, so microphone errors are not hidden.

## 0.6.1 — 2026-10-23 mobile polish (merged as PR #3)

### Fixed
- Symbols that showed as boxes on some Android phones are now inline SVG icons.
- Your own chat bubble was clipped by a header style (pill corners cut "YOU" and words); header styles are now scoped to the header.
- Chat box placeholder no longer wraps and gets cut at 320 px; composer buttons wrap instead of overflowing.
- PC action inputs stuck out of their card on narrow phones; they are now labelled fields.
- Home cards use a 2-column grid on phones instead of a sideways scroller; model name wraps instead of being cut.
- Verified with a scripted audit at 320/360/390/412 px for cut text, wrapped placeholders, round-corner clipping, elements outside their card, and tap targets in the More sheet (0 findings).

## 0.6.0 — 2026-10-23 (branch `atlas/windows-agent`)

### Added
- Desktop agent typed actions (`backend/app/agent.py`): `open_app` (allowlisted apps), `list_folder` and `search_files` (read-only, approved folders only). They run as tasks, always wait for approval of their exact parameters, and record who approved them.
- `ATLAS_AGENT_FOLDERS` to choose approved folders (default: Documents, Downloads, Desktop).
- Tasks screen: a PC actions form, approval cards that say exactly what will happen, and file results.

### Changed (mobile redesign)
- Phones get a bottom tab bar (Home, AI Chat, Tasks, Memory, More), a sticky top bar with live status, and a "More" sheet with every section and the system status. The squeezed quick-plan bar is hidden on phones.
- Chat: message bubbles, a collapsible model drawer with a route badge (local or cloud), an empty state with suggestions, and a composer that grows with the text and sticks above the tab bar.
- Bigger touch targets (44 px), 16 px inputs (no zoom on focus), horizontal agent cards, fixed oversized status dots.
- Browser test checks every screen at phone width for anything cut off past the screen edge.

### Changed
- `/api/desktop/status` also lists approved folders and actions. `/api/desktop/launch` uses the same launcher code.

## 0.5.0 — 2026-10-23 (branch `atlas/v7-foundation`, not yet released)

### Added
- Per-device logins (`backend/app/devices.py`). The Devices screen on the computer running ATLAS creates one-time pairing links (10 minutes, single use). Each paired device gets its own random token; only its SHA-256 hash is stored, in `devices.json` (0600).
- `/api/devices` (list), `/api/devices/pairing` (create code), `/api/devices/{id}` (remove), `/api/devices/current` (who am I / forget this device). Managing devices is owner-only.
- CLI: `python -m app.auth devices | revoke <id> | revoke-all`. `rotate` now also revokes every device.
- `ATLAS_PUBLIC_URL` (optional) so the Devices screen can show a complete link.

### Changed
- Pairing with the install token (`/?pair=<install token>`) now registers a device and gives it its own token; the install token is no longer stored on other devices.
- A browser on the same computer keeps an existing device session instead of being switched to the owner session.

## 0.4.0 — 2026-10-23 (branch `atlas/v7-foundation`, not yet released)

### Added
- API login (`backend/app/auth.py`): every `/api/` route needs the per-install token. A browser on the same computer gets it as an HttpOnly, SameSite=Strict cookie; other devices pair once with `/?pair=<token>` (shown by `python -m app.auth token`); scripts use `Authorization: Bearer`. `python -m app.auth rotate` signs every device out.
- Host-header allowlist (DNS-rebinding protection) and Origin check on writes (CSRF protection).
- UI banner explaining how to pair when a device is not signed in.
- CI: dependency audit, secret scan, and a Windows job that runs the test suite on a real Windows runner, including an actual Notepad launch.

## 0.3.0 — 2026-10-23 (branch `atlas/v7-foundation`, not yet released)

### Added
- SQLite storage (`backend/app/storage.py`) for memories, chat history and settings: versioned migrations, FTS5 search, `secure_delete`, export, import with dedupe, backup and restore (`python -m app.storage backup|restore|export|path`). Data lives in `%LOCALAPPDATA%\AtlasOS` on Windows or `~/.local/share/atlas-os` elsewhere (`ATLAS_DATA_DIR` overrides).
- `/api/memory`, `/api/memory/{id}`, `/api/memory/clear`, `/api/memory/settings`, `/api/memory/import`, `/api/chat/history`, `/api/storage/export`, `/api/storage/backup`.
- Background task engine (`backend/app/task_engine.py`) with real states, progress, cancel, pause/resume, priority, approval for cloud tasks, idempotency keys, timeouts and restart recovery. `/api/tasks` (create, list, get, approve, cancel, pause, resume, retry).
- Task types `plan` (model-written steps, never executed) and `summarize_text` (chunked).
- UI: Tasks screen; memory search and on/off switch; one-click move of old browser data into storage.

### Changed
- Memory and chat history default to server storage locally. In production mode server storage is off unless `ATLAS_SERVER_STORAGE=true`, because there is no authentication yet.
- The sidebar shows memory storage and task engine state.

## 0.2.0 — 2026-10-23 (branch `atlas/v7-foundation`, not yet released)

### Added
- Provider abstraction (`backend/app/providers/`) with per-provider capability flags, billing class and docs links.
- `POST /api/llm/chat/stream`: streaming replies as server-sent events (`start`, `delta`, `done`, `error`).
- Cancellation: the Stop button aborts generation, and the backend closes the provider connection.
- `POST /api/llm/models`: model discovery for Ollama (installed models only, never downloads) and cloud providers.
- `messages` (system/user/assistant) on chat endpoints, plus `temperature` and `max_tokens`. `prompt` still works.
- Latency, first-token time and token usage in responses when the provider reports them.
- Error classification: auth, rate limit, model not found, context too long, out of memory, timeout, unreachable.
- Bounded retries for connection failures only.
- `ATLAS_OLLAMA_BASE_URL`, `ATLAS_ALLOW_EXTERNAL_PROVIDERS`, `ATLAS_<PROVIDER>_API_KEY`, `ATLAS_ENV`, `ATLAS_ENABLE_API_DOCS`, rate/size/retry limits (see `backend/.env.example`).
- Security headers and a strict CSP; request-body size limit; per-IP rate limit on model endpoints.
- `GET /api/system/status` and a live status panel in the UI.
- Chat UI: provider dropdown, model list, streaming, Stop, data-routing and billing notice, answer provenance line.
- Memory export to JSON.
- Browser end-to-end tests (Playwright + Chromium + fake Ollama), ruff lint with security rules, and CI jobs for e2e and the Docker build.
- Docs: audit, feature matrix, architecture, threat model, test plan, decisions, handoff.

### Changed
- `backend/app/main.py` split into `config`, `security`, `providers/` and `routers/`. All 18 original tests pass; their only change is blank lines between import groups added by ruff.
- Frontend JS/CSS moved to `frontend/static/` with no inline script.
- The task plan now comes from the backend `/api/tasks/plan` and is labelled simulation.
- Status labels now come from real data. "Local demo ready", agent "READY" and "0 External connections" were removed.
- Validation errors return a readable `detail` string and never echo input values.
- API docs are off when `ATLAS_ENV=production`.
- Docker image runs as a non-root user with a healthcheck and production mode.
- Runtime and dev requirements split (`requirements-dev.txt`).

### Fixed
- `backend/Dockerfile` could not build (`COPY ../frontend`); removed in favour of the root `Dockerfile`.
- Activity log showed a literal `\n`.
- The mobile layout overflowed to 747 px at a 390 px viewport.
- README test count and API docs path.

## 0.1.0 — v7 research starter (imported as-is)
