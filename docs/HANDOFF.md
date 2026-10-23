# Handoff — session of 2026-10-23

## State

- Branch `atlas/v7-foundation`, based on `origin/main` (`9edc3c0`). The commits are listed in `git log origin/main..atlas/v7-foundation`.
- **Not pushed.** The working session had read-only access to `SHASHWAT-MISHRA-997/Atlas-OS`. The change set is delivered as a git bundle and a patch series. To apply it:

```bash
git clone https://github.com/SHASHWAT-MISHRA-997/Atlas-OS && cd Atlas-OS
git fetch /path/to/atlas-os-v0.2.0.bundle atlas/v7-foundation:atlas/v7-foundation
git push -u origin atlas/v7-foundation      # then open a PR into main
```

Or apply the patches: `git checkout -b atlas/v7-foundation && git am /path/to/patches/*.patch`.

- No deployment exists.

## Verified in this session (Linux, not Windows)

63 API/unit tests and 8 browser e2e tests pass; ruff is clean; detect-secrets and pip-audit are clean. See `TEST_PLAN.md`.

## Blockers

| Blocker | What unblocks it |
|---|---|
| Push / PR / CI run | Give Claude push access to the repo (install the Claude GitHub App on it), or push the bundle yourself |
| Real Ollama test | Run the manual steps in `TEST_PLAN.md` on your PC |
| Windows verification (desktop launcher, future agent) | A Windows 11 machine. Run the manual steps, or connect a Windows device or runner |
| Real cloud provider test | Your own key set as `ATLAS_<PROVIDER>_API_KEY` locally. Never paste it into chat |

## Next tasks, in order

1. Merge this branch; confirm the CI jobs `backend`, `frontend-e2e` and `docker-build` go green; update `TEST_PLAN.md`.
2. Remove `ATLAS_OS_Research_Starter_v4.zip` from `main` once the owner agrees. It is superseded and should not be the source of truth.
3. Milestone F-lite: SQLite store (`backend/app/storage.py`) for memories and chat history with migrations, export/import and delete; move the UI off localStorage behind a toggle.
4. Milestone G: task engine (`Queued → … → Succeeded/Failed/Cancelled`) with cancellation tokens; replace the fixed-step planner with a model-backed planner that still executes nothing.
5. Add `pip-audit` and `detect-secrets` to CI; add a lockfile.
6. Milestone E design: typed action schemas + risk policy + audit log, verified on Windows.
