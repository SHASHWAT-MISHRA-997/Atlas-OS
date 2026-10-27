# Test plan and latest report

## Suites

| Suite | Location | What it uses | Command |
|---|---|---|---|
| Function | `netlify/tests/cloud.test.mjs` | Node test runner; **FAKE provider** fetch stubs | `npm test` |
| Attacks | `netlify/tests/attack.test.mjs` | Header injection, smuggled fields, other hosts, cross-site and form posts | `npm test` |
| Size budget | `netlify/tests/budget.test.mjs` | Built `dist/`, gzip sizes, deferred scripts | `npm run build && npm test` |
| Browser e2e | `netlify/tests/e2e.test.mjs` | Local preview server with `ATLAS_FAKE_MODEL=1`, real Chromium via Playwright | `npm run test:e2e` |
| CI extras | `.github/workflows/tests.yml` | JS syntax check, `npm audit --omit=dev`, `detect-secrets` | GitHub Actions job `cloud` |

Fakes live only in tests and in the preview server behind `ATLAS_FAKE_MODEL=1`; replies say FAKE.

## Latest report

Date: 2026-10-28, v0.25.1. Environment: Windows 11, Node 24, Playwright Chromium 141 (headless); CI runs the same on Linux with Node 22. **Not Safari, not Brave, not a real phone.**

| Command | Passed | Failed |
|---|---|---|
| `node --test netlify/tests/cloud.test.mjs netlify/tests/attack.test.mjs netlify/tests/budget.test.mjs` | 34 | 0 |
| `node --test netlify/tests/e2e.test.mjs` | 17 | 0 |
| `detect-secrets scan` (excluding tests, node_modules, dist) | no findings | — |

## Manual checks still needed

- Real provider chat with the owner's own key on the live site, including a thinking level, a photo and a PDF.
- Live on a real phone and iPad: microphone, speech, camera; screen sharing on a computer.
- **Test my voice setup** on the live site with the owner's real Gemini and Groq keys, on the PC (Brave) and the phone: all four steps should pass; note the exact text of any FAIL. This is the quickest way to check the steps below.
- Live real-time voice with the owner's real Gemini key: that Google accepts the setup, the voice sounds right, interrupting works, and a session lasting over 10 minutes reconnects. The e2e test uses a FAKE Gemini Live server.
- Natural voice with the owner's real Gemini key: that `gemini-2.5-flash-preview-tts` answers on a free key, how it sounds for Hinglish, and how long the first words take (the e2e test uses a FAKE tone).
- Google Calendar and Gmail with the owner's real OAuth client ID, on the PC (Brave) and the phone: the sign-in pop-up opens and reports back (Brave Shields may block it; allow pop-ups), the consent screen lists only the two read-only scopes, today's and tomorrow's events and the 10 unread emails match Gmail, Sign out revokes (the app disappears from https://myaccount.google.com/permissions). The e2e test uses a FAKE Google sign-in script and FAKE APIs.
- ChatGPT voice with a real paid OpenAI key (the e2e test uses a FAKE OpenAI Realtime server).
- Real iPad and iPhone in Safari: layout, Paste button, Add to Home Screen.
- Real Android phone: install prompt.
- Reminder notifications on a real phone (iPhone and iPad only allow them for an installed app).
- Smoothness of the animated background on a real low-end phone.
