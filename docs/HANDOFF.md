# Handoff — 2026-10-25 (v0.13.1)

## State

- `main` holds v0.11.0 (PRs #1–#8 merged). Branch `atlas/free-keys` holds v0.12.0: free providers only and an easy "get a free key" flow online. Claude pushes as GitHub user `SRM100`, a Write collaborator.
- The full app runs on the owner's own computer. The online version is the Netlify project `atlas-os-sm` (site id `d61caa99-389d-418d-8f50-f49928bf0c2c`), created from this workspace on 2026-10-25. The owner linked the GitHub repository on 2026-10-25, so Netlify deploys every merge to `main`. This workspace's network cannot reach Netlify or the live site; check deploys with the Netlify MCP tools or ask the owner for a screenshot.

## New in v0.13

- v0.13.1: the online key card is a plain text box with a Paste button and cleans pasted keys (the owner could not add a key on the phone; Netlify logs showed one key check succeed but no chat).
- Redesign and new logo (see CHANGELOG 0.13.0). The owner said the old UI was confusing, overlapping and the logo boring; this is the response. Judged from Chromium screenshots at 360 px and 1280 px only.

## New in v0.12

- Online version offers only free cloud providers (Groq, Gemini, OpenRouter `:free` models) and no Ollama text.
- "Get your free AI key" card in AI Chat and a "Start here" banner on Home link to each provider's key page. Save checks the key with the provider first.
- Still unverified: a real provider call with a real free key, on the live site.

## New in v0.11

The online version is bring-your-own-key: no sign-in, each visitor pastes their own key (optionally remembered on that phone), and the owner's keys and Netlify credits are never used. See `docs/CLOUD.md` and D-024.

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
| Real cloud provider test | The owner pastes their own key in the live site's Model settings (or sets `ATLAS_<PROVIDER>_API_KEY` locally). Never paste it into chat |

## Next tasks, in order

1. The owner sends a real chat on the live site with their own key, to verify a real provider end to end.
2. Remove `ATLAS_OS_Research_Starter_v4.zip` from `main` once the owner agrees.
3. Hardware checks from the blockers above, using `TEST_PLAN.md` §Manual.
4. Optional embedding search on top of the keyword index (D-016); OCR for scanned PDFs.
5. A trained wake-word model behind the hands-free switch (D-018).
6. Tool calling in chat and browser automation, each with its own threat-model entry first (D-019).
7. Agents and Projects screens (still placeholders).
8. An independent red-team pass by someone other than the author.
