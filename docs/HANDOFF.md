# Handoff — 2026-10-25 (v0.15.0)

## State

- ATLAS is one web app at https://atlas-os-sm.netlify.app (Netlify project `atlas-os-sm`, site id `d61caa99-389d-418d-8f50-f49928bf0c2c`). Every merge to `main` deploys. Claude pushes as GitHub user `SRM100`, a Write collaborator (no admin, so branch protection must be set by the owner).
- The owner works from a phone and an iPad, has no PC, and chose to delete the PC version (D-025, v0.15.0). It is in the Git history up to 45298f7.
- This workspace's network cannot open the live site; check deploys with the Netlify MCP tools.
- Feature plan from 2026-10-25: https://claude.ai/artifact/6jsB1Jyo3mppD8b4u1BUY8.

## Recent versions

- v0.15.0: web app only; iPhone/iPad install hint; one CI job (`cloud`).
- v0.14.0: auto-switch between free providers on 429/5xx (never into paid); optional paid OpenAI.
- v0.13.3: security pass with attack tests (T38/T39).
- v0.13.2: update banner and Check for update; model dropdown.
- v0.13.1: key card is a plain text box with Paste; edit/delete messages; Clear all.

## Verified in this session (Linux, Chromium, FAKE model)

25 function/attack/size tests and 5 browser tests pass. iPad sizes were checked in Chromium only.

## Next tasks, in order

1. Redesign the owner asked for: dark and light theme; neon cyberpunk look with background, motion and transitions; each screen visibly different; a separate System status / update panel.
2. Web versions of Automations (run on a schedule while the page is open) and Devices (this device, its data, move data to another device).
3. The owner sends a real chat with their own key on the live site, on the iPad.
4. Remove `ATLAS_OS_Research_Starter_v4.zip` from `main` once the owner agrees.
5. Remaining plan items: chat compression, thinking-level switch, image/PDF input, steering mid-reply.
