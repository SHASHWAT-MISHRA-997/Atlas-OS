# Handoff — 2026-10-29 (v0.28.0)

## State

- ATLAS is one web app at https://atlas-os-sm.netlify.app (Netlify project `atlas-os-sm`, site id `d61caa99-389d-418d-8f50-f49928bf0c2c`). Every merge to `main` deploys.
- The owner works from a phone and an iPad, and now sometimes from a Windows PC with Brave. The PC version of ATLAS stays deleted (D-025, v0.15.0); it is in the Git history up to 45298f7.
- Earlier sessions pushed as GitHub user `SRM100`, a Write collaborator (no admin, so branch protection must be set by the owner). The 2026-10-28 session ran on the owner's Windows PC and pushed with the owner's own `gh` login; its commits use the owner's GitHub no-reply address.
- On Windows, run the secret scan with `PYTHONUTF8=1` (otherwise Python reads the UTF-8 sources as cp1252 and skips them silently), and use `--exclude-files '(^|.)(\.git|node_modules|dist|tests).'` because paths use `\`. CI on Linux runs the command from `.github/workflows/tests.yml` unchanged.
- Feature plan from 2026-10-25: https://claude.ai/artifact/6jsB1Jyo3mppD8b4u1BUY8.
- PC control (PR #25, made in another session) was brought up to date with `main`, reviewed, fixed and tested on the owner's PC, and shipped as 0.26.0. `AtlasHelper.exe` is published by CI as a GitHub release (`pc-helper-v<version>`).

## Recent versions

- v0.28.0: Google Calendar and Gmail and the "Calendar, email, messaging" tile removed at the owner's request; CSP and COOP tightened back.
- v0.27.1: phone actions fixed against real Gemini Live (stricter tool instruction; `call_phone` renamed `dial_number` because Google's server failed on it).
- v0.27.0: phone actions in Live (one-tap call, SMS, WhatsApp, Maps, YouTube, website, share); Microsoft Store readiness (privacy page, manifest); WebKit run.
- v0.26.1: Live started by typing starts with the microphone muted (nearby speech took over a typed question on the owner's phone); typing while connecting confirmed against real Gemini.
- v0.26.0: PC control in Live (ATLAS PC helper) with fixes from a real test on the owner's PC; typing in Live real-time modes works (auto-start, waits while connecting); silence cut before Whisper.
- v0.25.3: Test my voice setup passed on the owner's phone with real keys; Whisper words for silence are dropped.
- v0.25.2: fixes found on real services and the owner's phone: stale version after a tab restore (service worker), a wrong OpenRouter key accepted, a wrong OpenAI key in ChatGPT voice described as a dropped call. Also: README redesign, CodeQL and Dependabot.
- v0.25.1: housekeeping: `ATLAS_OS_Research_Starter_v4.zip` removed from `main` (still in Git history), stale claims fixed across the docs, the Integrations voice tile now describes Brave/Firefox correctly.
- v0.25.0: "Test my voice setup" on Live (real-time models, Gemini Live `setupComplete`, `/cloud/speak`, 1-second `/cloud/transcribe`, each with pass/fail and the provider's exact words); every Live error names the step and what to do. Untested against real services.
- v0.24.0: read-only Google Calendar and Gmail on Integrations (`frontend/static/google.js`): today's and tomorrow's events, the 10 latest unread senders and subjects, token in memory only, Sign out revokes. Needs the owner's Google OAuth client ID (docs/CLOUD.md). Untested against real Google.
- v0.22.1: every Live mode can be picked; a mode without its key shows a key box on the Live screen.
- v0.22.0: natural voice for spoken answers through `/cloud/speak` (Gemini speech models; OpenAI only when chosen). Untested against the real Gemini TTS API.
- v0.21.0: Dictate and Live work in Brave/Firefox (record + Groq Whisper or Gemini writes it down).
- v0.20.0: ChatGPT voice in Live (OpenAI Realtime API, paid, behind a billing tick). Untested against the real API.
- v0.19.0: Live real-time voice through the Gemini Live API. Untested against the real API.
- v0.18.0: Live screen, About the developer, key remembered by default, Auto-switch switch in Integrations.
- v0.15.0–v0.17.0: web app only; neon redesign; thinking level, images and PDFs, steering, chat compression.

## Verified in this session (Windows 11, Node 24, Playwright Chromium 141 headless, FAKE services)

- At v0.22.1 (start of the session): 32 function/attack/size tests and 15 browser tests passed.
- At v0.27.0: 38 function/attack/size tests, 23 browser tests and 19 PC helper tests pass; the secret scan reports nothing; first load is 75.1 KB gzipped at v0.28.0 (budget 80 KB).
- Real services were checked with invalid keys (daily `Provider check`), Test my voice setup passed on the owner's Android phone with real keys, the browser tests passed in real Brave, Chrome and Edge, and the PC helper was tested for real on the owner's Windows PC. Not in Safari.

## Next tasks, in order

1. Google Calendar and Gmail were removed in 0.28.0 at the owner's request (also the Google Cloud project `atlas-os-513012` and the Netlify variable `ATLAS_GOOGLE_CLIENT_ID`).
2. The owner runs **Live → Test my voice setup** with real Gemini and Groq keys on the PC (Brave) and the phone, and sends the text of any FAIL.
3. The owner sends a real chat with their own key on the live site, including a photo, a PDF (Gemini) and a thinking level.
4. The owner makes the repository private and protects `main` (only the `cloud` check) in GitHub settings.
