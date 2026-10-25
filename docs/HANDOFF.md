# Handoff — 2026-10-25 (v0.10.0)

## State

- `main` holds v0.9.0 (PRs #1–#6 merged). Branch `atlas/cloud` holds v0.10.0 (the online version). Claude pushes as GitHub user `SRM100`, a Write collaborator.
- The full app runs on the owner's own computer. The online version is the Netlify project `atlas-os-sm` (site id `d61caa99-389d-418d-8f50-f49928bf0c2c`), created from this workspace on 2026-10-25. This workspace's network cannot reach Netlify, so it cannot upload a deploy or open the live site itself; deploys come from Netlify building the GitHub repository once the owner links it (see `docs/CLOUD.md`).

## New in v0.10

ATLAS online on Netlify for a phone-only owner: AI Chat with a cloud model whose key is a Netlify environment variable, memory and history in the browser, plan and summarize tasks, owner claim and device pairing. PC-only features are refused clearly. See `docs/CLOUD.md`.

## New in v0.9

Hands-free "Hey ATLAS" (VAD plus local Whisper), local read-aloud (Piper), microphone choice, browser control (open a website, web search), automations (scheduled tasks), an opt-in fallback model, and a real local-model plan on Home. A v0.8 bug was fixed: voice uploads over 256 KB were rejected by the JSON body limit.

## New in v0.8

Document search (index approved folders, search, "Use my documents" in chat), safe file writing (new notes, Word, Excel; ATLAS trash with restore; never overwrite or delete), Windows media keys, optional local speech-to-text (faster-whisper, owner-started download), and a Windows installer with start-on-login. See `CHANGELOG.md` and `FEATURE_MATRIX.md`.

## Verified in this session (Linux container, not Windows)

401 unit, API and Playwright e2e tests pass on Python 3.13 (367 non-browser tests also on 3.11), ruff is clean, and a phone audit at 320, 360, 390 and 412 px found 0 cut-off or hidden items. Local speech-to-text and read-aloud were tested only with labelled mock engines, and hands-free with a fake microphone and mocked transcription: this workspace blocks Hugging Face, so no real model or voice was run. The installer is tested by the Windows CI job.

## Blockers (need the owner's hardware or accounts)

| Blocker | What unblocks it |
|---|---|
| Real Ollama test and Q1 latency | The owner chose not to pursue it for now; this workspace also blocks Ollama downloads |
| Personal Windows 11 PC check (installer, agent, media keys, Office files, voice) | A Windows PC. The owner currently has only a phone |
| Real local speech model and voice (quality on Hindi/Hinglish, hands-free accuracy) | A PC that can reach Hugging Face; press Download in AI Chat → Model settings |
| Real phone over Wi-Fi or Tailscale, PWA install, QR scan | A phone plus the PC running ATLAS; follow `REMOTE_ACCESS.md` |
| Real cloud provider test | The owner's own key set in Netlify (`GROQ_API_KEY` or `GEMINI_API_KEY`) or locally as `ATLAS_<PROVIDER>_API_KEY`. Never paste it into chat |
| First live deploy of the online version | The owner links the GitHub repository to the Netlify project once (Netlify → atlas-os-sm → Link repository) |

## Next tasks, in order

1. Link the repository in Netlify, check the first deploy, claim the site, add a key, and send a real chat.
2. Remove `ATLAS_OS_Research_Starter_v4.zip` from `main` once the owner agrees.
3. Hardware checks from the blockers above, using `TEST_PLAN.md` §Manual.
4. Optional embedding search on top of the keyword index (D-016); OCR for scanned PDFs.
5. A trained wake-word model behind the hands-free switch (D-018).
6. Tool calling in chat and browser automation, each with its own threat-model entry first (D-019).
7. Agents and Projects screens (still placeholders).
8. An independent red-team pass by someone other than the author.
