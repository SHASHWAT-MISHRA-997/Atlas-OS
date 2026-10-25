# Handoff — 2026-10-25 (v0.7.0)

## State

- `main` holds v0.6.1: PR #1 (foundation, v0.5.0), PR #2 (Windows agent typed actions, v0.6.0) and PR #3 (mobile redesign) are merged.
- Branch `atlas/v0.7` holds v0.7.0 and goes up as its own PR. Claude pushes as GitHub user `SRM100`, a Write collaborator.
- No deployment exists. ATLAS runs on the owner's own computer.

## Verified in this session (Linux container, not Windows)

All unit, API and Playwright e2e tests pass, ruff is clean, and CI runs four jobs: backend, windows, frontend-e2e and docker-build. The research numbers in `RESEARCH.md` come from this container with a fake model.

## Blockers (need the owner's hardware or accounts)

| Blocker | What unblocks it |
|---|---|
| Real Ollama test and Q1 latency | The owner chose not to pursue it for now; this workspace also blocks Ollama downloads |
| Personal Windows 11 PC check (agent, launcher, voice) | A Windows PC. The owner currently has only a phone |
| Real phone over Wi-Fi or Tailscale, PWA install, QR scan | A phone plus the PC running ATLAS; follow `REMOTE_ACCESS.md` |
| Real cloud provider test | The owner's own key set as `ATLAS_<PROVIDER>_API_KEY` locally. Never paste it into chat |

## Next tasks, in order

1. Merge the v0.7 PR once CI is green.
2. Remove `ATLAS_OS_Research_Starter_v4.zip` from `main` once the owner agrees.
3. Hardware checks from the blockers above, using `TEST_PLAN.md` §Manual.
4. Milestone D: choose local STT and TTS engines (e.g. faster-whisper, Piper) as an opt-in download the user starts; a wake-word spike.
5. Milestone E: a file-write design (trash, undo, dry run) before any write or delete action; Office document generation.
6. Document search (RAG) over approved folders, read-only, building on the agent's path rules.
7. An independent red-team pass, by someone other than the author, over `test_redteam_actions.py` and the threat model.
