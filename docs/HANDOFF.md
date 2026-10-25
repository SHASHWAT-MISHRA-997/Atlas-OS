# Handoff — 2026-10-25 (v0.8.0)

## State

- `main` holds v0.7.0 (PRs #1–#4 merged). Branch `atlas/v0.8` holds v0.8.0 and goes up as PR #5. Claude pushes as GitHub user `SRM100`, a Write collaborator.
- No deployment exists. ATLAS runs on the owner's own computer.

## New in v0.8

Document search (index approved folders, search, "Use my documents" in chat), safe file writing (new notes, Word, Excel; ATLAS trash with restore; never overwrite or delete), Windows media keys, optional local speech-to-text (faster-whisper, owner-started download), and a Windows installer with start-on-login. See `CHANGELOG.md` and `FEATURE_MATRIX.md`.

## Verified in this session (Linux container, not Windows)

336 unit, API and Playwright e2e tests pass on Python 3.13 and 3.11, ruff is clean, and a phone audit at 320, 360, 390 and 412 px found 0 cut-off or hidden items. Local speech-to-text was tested only with a labelled mock engine: this workspace blocks Hugging Face, so no real model was run. The installer is tested by the Windows CI job.

## Blockers (need the owner's hardware or accounts)

| Blocker | What unblocks it |
|---|---|
| Real Ollama test and Q1 latency | The owner chose not to pursue it for now; this workspace also blocks Ollama downloads |
| Personal Windows 11 PC check (installer, agent, media keys, Office files, voice) | A Windows PC. The owner currently has only a phone |
| Real local speech model (quality on Hindi/Hinglish) | A PC that can reach Hugging Face; press Download in AI Chat → Model settings |
| Real phone over Wi-Fi or Tailscale, PWA install, QR scan | A phone plus the PC running ATLAS; follow `REMOTE_ACCESS.md` |
| Real cloud provider test | The owner's own key set as `ATLAS_<PROVIDER>_API_KEY` locally. Never paste it into chat |

## Next tasks, in order

1. Merge the v0.8 PR once CI is green.
2. Remove `ATLAS_OS_Research_Starter_v4.zip` from `main` once the owner agrees.
3. Hardware checks from the blockers above, using `TEST_PLAN.md` §Manual.
4. Optional embedding search on top of the keyword index (D-016); OCR for scanned PDFs.
5. Local text-to-speech (e.g. Piper) and a wake-word spike.
6. Browser control and tool calling in chat, each with its own threat-model entry first.
7. An independent red-team pass by someone other than the author.
