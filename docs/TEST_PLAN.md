# Test plan and latest report

## Suites

| Suite | Location | What it uses | Command |
|---|---|---|---|
| Function | `netlify/tests/cloud.test.mjs` | Node test runner; **FAKE provider** fetch stubs | `npm test` |
| Attacks | `netlify/tests/attack.test.mjs` | Header injection, smuggled fields, other hosts, cross-site and form posts | `npm test` |
| Size budget | `netlify/tests/budget.test.mjs` | Built `dist/`, gzip sizes, deferred scripts | `npm run build && npm test` |
| Browser e2e | `netlify/tests/e2e.test.mjs` | Local preview server with `ATLAS_FAKE_MODEL=1`, real Chromium via Playwright | `npm run test:e2e` |
| CI extras | `.github/workflows/tests.yml` | JS syntax check, `npm audit --omit=dev`, `detect-secrets` | GitHub Actions job `cloud` |
| Real providers, daily | `scripts/netlify/provider-check.mjs`, `.github/workflows/provider-check.yml` | The **live** site and the **real** Groq, Gemini (incl. Live WebSocket), OpenRouter, OpenAI (incl. Realtime WebSocket) and Google sign-in, with deliberately invalid keys (nothing billed, no secret) | `node scripts/netlify/provider-check.mjs` (runs daily on GitHub; a failure emails the owner) |
| Other browsers | same e2e suite | Real Brave, Chrome and Edge on the owner's PC | `ATLAS_E2E_CHROMIUM=<path to brave.exe / chrome.exe / msedge.exe> node --test netlify/tests/e2e.test.mjs` |

Fakes live only in tests and in the preview server behind `ATLAS_FAKE_MODEL=1`; replies say FAKE.

## Latest report

Date: 2026-10-28, v0.27.0. Environment: Windows 11, Node 24, Playwright 1.64 Chromium (headless); CI runs the same on Linux with Node 22. **Not Safari.**

| Command | Passed | Failed |
|---|---|---|
| `node --test netlify/tests/cloud.test.mjs netlify/tests/attack.test.mjs netlify/tests/budget.test.mjs` | 38 | 0 |
| `node --test netlify/tests/e2e.test.mjs` (set `PYTHON=python` on Windows for the PC helper test) | 23 | 0 |
| Same suite in WebKit (Safari's engine): `ATLAS_E2E_BROWSER=webkit` | 11 | 9 (all need a microphone, camera or audio, which Playwright's WebKit on Windows does not have) |
| `python -m unittest test_atlas_helper` (in `pc-helper/`, Windows 11) | 19 | 0 |
| `detect-secrets scan` (excluding tests, node_modules, dist) | no findings | — |

## Against the real services, without a key (2026-10-28, live site)

Each provider was called through the live function (or directly, for the WebSockets) with a deliberately invalid key, so the real service answers and nothing is billed:

| Real service | Answer | ATLAS shows |
|---|---|---|
| Groq models, chat, Whisper (1 s WAV) | HTTP 401 "Invalid API Key" | "Provider answered HTTP 401: Invalid API Key. Check your API key." |
| Gemini models, Live models, speech, transcription | HTTP 400 "API key not valid…" | the same words + "Check your API key." |
| OpenAI models | HTTP 401 "Incorrect API key provided…" (key masked by OpenAI) | the same words |
| OpenRouter models | **HTTP 200 with any key** (public list) → bug, fixed in 0.25.2 via `/api/v1/key` (401) | "HTTP 401 … Check your API key." |
| Gemini Live WebSocket | closes with code 1007, reason "API key not valid. Please pass a valid API key." | "Connecting to Google Gemini (…) failed: API key not valid…" |
| OpenAI Realtime WebSocket | `error` event "Incorrect API key provided…", then close 3000 | fixed in 0.25.2 to name the connecting step |
| Google sign-in script (`accounts.google.com/gsi/client`) | loads under the CSP with no errors; a blocked pop-up reports `popup_failed_to_open` | "The browser blocked the Google sign-in window. Allow pop-ups…" |

2026-10-28 run of `provider-check.mjs`: 14 passed, 0 failed. Real browsers on the owner's PC (Windows 11): **Brave 1.98 (Chromium 156, `navigator.brave` true), Chrome 156 and Edge 156 each passed all 17 browser tests.**

Not covered: a successful answer, a real voice, real Calendar/Gmail data and quotas, which need the owner's own keys and Google client ID.

## PC control on the owner's Windows PC (2026-10-28, real helper, real Brave, local preview)

| Action | Result |
|---|---|
| Pair with the 6-digit code | paired |
| system_info, list_apps | PC name, battery, 164 Start menu apps (first list 13–17 s, now loaded at start) |
| open_app Notepad, media volume up/down, open_folder Documents, web_search YouTube | done |
| write_note, then find_files | first run: **not found** (a big Desktop used up the 4 s) → fixed: found in `Documents\ATLAS Notes` |
| type_text, Allow box | first run: the box named a Brave tab but the text went into Notepad → **fixed** (only the approved window). Then, in a test window that records keys: **Yes → 73/73 characters exactly**, **No → nothing typed** |
| open PowerShell, Win+R, `C:\Windows\System32\cmd.exe`, `Documents\evil.ps1`, `run_command` | all refused, no box |

Not covered: a real Gemini/OpenAI tool call (needs a key in the PC browser), pairing from the live site (Chrome/Brave local-network permission), `lock_pc`.

## With the owner's real keys, on the owner's phone (2026-10-28)

**Test my voice setup** on the live site (v0.25.2), with the Gemini and Groq keys saved on the phone, microphone allowed by the owner:

| Step | Result |
|---|---|
| 1. Real-time models for the Gemini key | PASS: 9 found; Live uses `gemini-2.5-flash-native-audio-preview-12-2025` |
| 2. Gemini Live connection | PASS: Google accepted the key and model, setup in 2,753 ms |
| 3. Natural voice (`/cloud/speak`) | PASS: 3.8 s of Gemini speech (voice Puck), played on the phone |
| 4. 1 s of microphone (`/cloud/transcribe`, Groq) | PASS, but Whisper wrote "Gracias." for (most likely) silence: fixed in 0.25.3 |

Live typing with the real Gemini key on the phone (v0.26.0): tapping the orb and typing at once was answered in 4 s while Gemini was still connecting; a question typed without tapping the orb was sent (`setup`, then `clientContent`) but not answered because the open microphone heard a video playing nearby: fixed in 0.26.1 (started by typing = microphone muted).

Not yet with real keys: a full Live conversation, ChatGPT voice (paid), Calendar and Gmail.

## On the owner's phone (OnePlus CPH2573, Android 16, Chrome 156, over USB)

All 10 screens open with no sideways scrolling and no controls off screen; no small tap targets; no long tasks; the phone has AudioWorklet, microphone, speech recognition, speech synthesis and WebSocket (no screen sharing, as expected on Android). Only console message: Netlify's blocked badge script. **The phone was running 0.18.0** from the browser's cache after a tab restore; fixed in 0.25.2 (service worker).

## Live-site audit (2026-10-28, v0.25.1, from the owner's Windows PC)

- Every screen opened on https://atlas-os-sm.netlify.app with no sideways scrolling. The only console message is **one CSP error caused by Netlify's free-plan badge** (`/.netlify/scripts/hud`, injected by Netlify into every page): it builds an iframe with inline script, which the site's CSP blocks. Allowing it would need `'unsafe-inline'` or a hash Netlify can change at any time, which weakens XSS protection, so it stays blocked. Only a paid Netlify plan removes the badge. The local e2e tests do not see it because the badge is injected only on Netlify.
- Load time from this PC: about 2.4 s to DOMContentLoaded on a first visit, almost all of it network (TLS setup 0.3–0.8 s per connection to Netlify); the app is about 67 KB compressed and the function answers in under 1 s.
- Attack probes against the live function, with no real key: a cross-site `Origin` or `Sec-Fetch-Site` got 403, a form post 415, an SQL-style provider name 422, CR/LF in the key 422, `__proto__` as provider 422, a smuggled `tool` role 422, bad JSON 400, a 6 MB body 413. Headers present: CSP, HSTS (preload), `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, COOP. The rate limit (60 a minute per visitor) was not flooded on purpose.
- `npm audit`: 0 vulnerabilities. No `innerHTML`, `eval`, `new Function` or string timers in the app. CodeQL code scanning and Dependabot were added so future problems are reported automatically.

## Manual checks still needed

- Real provider chat with the owner's own key on the live site, including a thinking level, a photo and a PDF.
- Live on a real phone and iPad: microphone, speech, camera; screen sharing on a computer.
- **Test my voice setup** on the live site with the owner's real Gemini and Groq keys, on the PC (Brave) and the phone: all four steps should pass; note the exact text of any FAIL. This is the quickest way to check the steps below.
- Live real-time voice with the owner's real Gemini key: that Google accepts the setup, the voice sounds right, interrupting works, and a session lasting over 10 minutes reconnects. The e2e test uses a FAKE Gemini Live server.
- Natural voice with the owner's real Gemini key: that `gemini-2.5-flash-preview-tts` answers on a free key, how it sounds for Hinglish, and how long the first words take (the e2e test uses a FAKE tone).
- Google Calendar and Gmail with the owner's real OAuth client ID, on the PC (Brave) and the phone: the sign-in pop-up opens and reports back (Brave Shields may block it; allow pop-ups), the consent screen lists only the two read-only scopes, today's and tomorrow's events and the 10 unread emails match Gmail, Sign out revokes (the app disappears from https://myaccount.google.com/permissions). The e2e test uses a FAKE Google sign-in script and FAKE APIs.
- ChatGPT voice with a real paid OpenAI key (the e2e test uses a FAKE OpenAI Realtime server).
- Real iPad and iPhone in Safari: layout, Paste button, Add to Home Screen.
- Real Android phone: install prompt.
- Reminder notifications on a real phone (iPhone and iPad only allow them for an installed app).
- Smoothness of the animated background on a real low-end phone.
