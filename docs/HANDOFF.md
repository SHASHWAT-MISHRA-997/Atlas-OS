# Handoff — session of 2026-10-23 (updated for v0.5.0)

## State

- Branch `atlas/v7-foundation`, based on `origin/main` (`9edc3c0`). The commits are listed in `git log origin/main..atlas/v7-foundation`.
- **Not pushed.** The working session's GitHub login is `SRM100`, which has no write access to `SHASHWAT-MISHRA-997/Atlas-OS`. Adding `SRM100` as a collaborator (Write) unblocks it. The change set is delivered as a git bundle and a patch series. To apply it:

```bash
git clone https://github.com/SHASHWAT-MISHRA-997/Atlas-OS && cd Atlas-OS
git fetch /path/to/atlas-os.bundle atlas/v7-foundation:atlas/v7-foundation
git push -u origin atlas/v7-foundation      # then open a PR into main
```

Or apply the patches: `git checkout -b atlas/v7-foundation && git am /path/to/patches/*.patch`.

- No deployment exists.

## Verified in this session (Linux, not Windows)

169 API/unit tests (Python 3.11 and 3.13; 3 Windows-only tests skipped) and 17 browser e2e tests pass with login on; ruff and pip-audit are clean. See `TEST_PLAN.md`.

## Blockers

| Blocker | What unblocks it |
|---|---|
| Push / PR / CI run | Add `SRM100` as a Write collaborator on the repo, or push the bundle yourself (e.g. from a Codespace) |
| Real Ollama test | Owner chose not to pursue it for now; the workspace network also blocks Ollama downloads |
| Windows verification (desktop launcher, future agent) | The CI `windows` job covers part of it once the code is pushed; full checks need a Windows 11 PC |
| Real cloud provider test | Your own key set as `ATLAS_<PROVIDER>_API_KEY` locally. Never paste it into chat |

## Next tasks, in order

1. Merge this branch; confirm the CI jobs `backend`, `frontend-e2e` and `docker-build` go green; update `TEST_PLAN.md`.
2. Remove `ATLAS_OS_Research_Starter_v4.zip` from `main` once the owner agrees. It is superseded and should not be the source of truth.
3. ~~Milestone F-lite (SQLite memory)~~ done in v0.3.0. ~~Milestone G (task engine)~~ done in v0.3.0.
4. ~~Local API login~~ and ~~CI scans~~ done in v0.4.0. ~~Per-device credentials with revocation~~ done in v0.5.0. Next for security: a hashed lockfile; QR pairing; TLS/remote access design (rest of Milestone H).
6. Milestone E: typed action schemas + risk policy + audit log, built as task types on the new engine, and verified on Windows.
7. Milestone D: local STT/TTS engine selection (e.g. faster-whisper, Piper) and a wake-word spike, which needs real hardware.
