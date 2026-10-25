# Research (Milestone K)

This file reports what was measured, how, and what the numbers do not show. The questions come from `DECISIONS.md` D-008.

**Environment for every result below:** a cloud Linux container (x86_64, 4 CPUs, Python 3.13.16), 2026-10-25, commit on branch `atlas/v0.7`. This is not the owner's Windows PC. No real model was used.

## Q1. Time to first token: local vs cloud

**Not measured.** That needs a real Ollama install and a real cloud key on stated hardware. The owner chose not to pursue Ollama for now, and keys are never requested in chat.

**What was measured instead** is the delay ATLAS adds between the app and the model. A fake OpenAI-compatible server in the same process streams one token every 2 ms. The same persistent client measures the time to the first token two ways: talking to the fake server directly, and going through ATLAS's `/api/llm/chat/stream`.

| 100 runs each | Direct to fake model | Through ATLAS, before fix | Through ATLAS, after fix |
|---|---|---|---|
| Median | 1.6–1.7 ms | 50.6 ms | **7.5 ms** |
| 95th percentile | 2.3–2.6 ms | 89.1 ms | **9.3 ms** |
| Max | 4.3–4.5 ms | 102.4 ms | 15.2 ms |

**Finding and fix.** Before the fix, ATLAS added about 49 ms to every chat message. The cause was that a new HTTP client was built per request, and each build reloaded the TLS certificate bundle, which took about 50 ms when measured on its own. ATLAS now builds the TLS context once (`app/providers/tls.py`). Each request still gets its own client, so Stop still closes only that request. The overhead is now about 6 ms.

A real model's first token takes hundreds of milliseconds to seconds, so 49 ms was a real but secondary cost. It mattered most on the phone, where every message pays it.

Raw output: `docs/research/latency-2026-10-25-before-tls-cache.json` and `…-after-tls-cache.json`. To reproduce: `cd backend && python research/bench_latency.py 100`.

## Q2. Cancellation latency

This is the time from the client closing the stream (what the Stop button does) to the model server seeing its connection closed. The fake server records the moment its next write fails.

| 100 runs | Result |
|---|---|
| Median | 3.5 ms |
| 95th percentile | 3.7 ms |
| Max | 3.7 ms (9.6 ms in the "before" run) |
| Runs where Stop never reached the model | 0 of 100 |

The fake server writes every 2 ms, so up to 2 ms of each number is just waiting for its next write. When you press Stop, the model server is told to stop within a few milliseconds of ATLAS noticing. Ollama then stops generating; that part was not measured here.

## Q3. Does the permission policy block unauthorised actions?

`backend/tests/test_redteam_actions.py` has **67 attack cases** against the desktop agent and its approval flow (30 from v0.7, 20 added in v0.8 for writing files, the trash, indexing and document search, 17 in v0.9 for browser control). All 67 are blocked or contained, and they run in CI on every push.

| Group | Cases | What is tried |
|---|---|---|
| Leave the approved folder | 15 | `..` paths, nested `..`, a symlink to a folder outside, absolute and UNC paths, unlisted or odd folder names, NUL bytes, URL-encoded `..`, search through a symlink |
| Run something not allowlisted | 7 | `shell` and `run_command` kinds, PowerShell, `notepad & calc`, `cmd.exe`, a missing app, extra `command`/`args` fields |
| Get around approval | 4 | nothing runs unapproved, a wrong hash, a hash from another task, approving twice, approving after the agent is switched off |
| Wrong person asks | 4 | no login, a cross-site page, a tunnel on the PC, a paired phone using the old direct launcher |
| Browser control (v0.9) | 17 | `file:`, `javascript:`, `data:`, `ms-settings:` and UNC addresses, embedded logins, localhost and ATLAS's own API, IPv6 loopback, router and private addresses, cloud metadata, `.local`, spaces and newlines, search words trying to change the address |
| Write, trash and index (v0.8) | 20 | `..`, slashes and backslashes in new file names, dotfiles, Windows device names (`CON`, `nul.txt`), writing into a linked folder, overwriting an existing file, trashing a file outside or a whole folder, restore over a newer file, indexing through a link, FTS query syntax |

The cases **found two real problems**, both fixed in this version:

1. **A tunnel on the PC made every visitor the owner.** A browser on the PC is signed in as the owner automatically. Tailscale Serve, cloudflared and nginx also connect from `127.0.0.1`, so anyone reaching ATLAS through them would have become the owner. The automatic owner login now also requires a loopback Host name and no forwarding headers. `test_devices.py` has the cases; they fail on the old code.
2. **A paired phone could skip approval.** The old `/api/desktop/launch` endpoint opened an allowlisted app when the request said `confirm: true`. A phone can send that flag, so it was not approval. The endpoint is now owner-only, and phones use approved tasks.

**Limits.** The same author wrote the code and these cases, so this is a regression suite, not an independent red-team evaluation. Prompt injection through chat is ruled out by design rather than tested: the chat endpoint cannot create tasks or actions, so a model's reply has no path to the agent. That holds until a tool-calling feature exists. Since v0.8, document excerpts can carry injected text into chat; they are labelled untrusted, and the same rule applies: chat cannot act. Nothing here was run on Windows except the `test_windows.py` cases on the CI Windows runner.

## Accessibility (supporting evidence)

The e2e suite runs axe-core (WCAG 2.1 A and AA rules) on every screen, at 1280 px and at 390 px including the More sheet. There are 0 serious or critical findings. axe cannot measure text on gradients, so `test_contrast.py` computes those directly. It found the main buttons at 3.3:1 (white on `#2a8cff`), below the 4.5:1 minimum, and they were fixed to 5.1:1 or better. Automated checks catch only part of real accessibility problems. No screen-reader session with a real user has been done.
