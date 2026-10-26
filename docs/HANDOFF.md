# Handoff — 2026-10-26 (v0.19.0)

## State

- ATLAS is one web app at https://atlas-os-sm.netlify.app (Netlify project `atlas-os-sm`, site id `d61caa99-389d-418d-8f50-f49928bf0c2c`). Every merge to `main` deploys. Claude pushes as GitHub user `SRM100`, a Write collaborator (no admin, so branch protection must be set by the owner).
- The owner works from a phone and an iPad, has no PC, and chose to delete the PC version (D-025, v0.15.0). It is in the Git history up to 45298f7.
- This workspace's network cannot open the live site; check deploys with the Netlify MCP tools.
- Feature plan from 2026-10-25: https://claude.ai/artifact/6jsB1Jyo3mppD8b4u1BUY8.

## Recent versions

- v0.18.0: Live screen (voice, camera, screen share), About the developer, key remembered by default, Auto-switch switch in Integrations.
- v0.18.1: Home cleaned up: the title no longer shows a copied layer of its own text, repeated wording removed.
- v0.19.0: Live real-time voice through the Gemini Live API (`frontend/static/realtime.js`, `live-worklet.js`), straight from the browser to Google with the user's Gemini key. Untested against the real API; the owner must try it with their key.
- v0.17.0: thinking level, images and PDFs, steering mid-reply, chat compression; Stop now cancels the request online.
- v0.16.1: removed the top-bar task box.
- v0.16.0: neon redesign with dark/light theme, per-screen colours and transitions; System screen; Automations and Devices back as web versions.
- v0.15.0: web app only; iPhone/iPad install hint; one CI job (`cloud`).
- v0.14.0: auto-switch between free providers on 429/5xx (never into paid); optional paid OpenAI.
- v0.13.3: security pass with attack tests (T38/T39).
- v0.13.2: update banner and Check for update; model dropdown.
- v0.13.1: key card is a plain text box with Paste; edit/delete messages; Clear all.

## Verified in this session (Linux, Chromium, FAKE model)

29 function/attack/size tests and 11 browser tests pass. iPad sizes were checked in Chromium only. With 4x CPU slowdown on slow 4G (headless, no GPU): first paint about 0.8 s, app ready about 1.4 s, idle animation about 52–58 fps, longest task 133 ms on load.

## Next tasks, in order

1. The owner checks the redesign on the iPad and phone and says what to change.
2. The owner sends a real chat with their own key on the live site, on the iPad, including a photo, a PDF (Gemini) and a thinking level.
3. Remove `ATLAS_OS_Research_Starter_v4.zip` from `main` once the owner agrees.
4. The owner makes the repository private and protects `main` (only the `cloud` check) in GitHub settings; Claude's account cannot change repository settings.
