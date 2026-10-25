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

Date: 2026-10-25, v0.15.0. Environment: Linux container, Node 22, Chromium 141. **Not Safari, not a real phone.**

| Command | Passed | Failed |
|---|---|---|
| `node --test netlify/tests/cloud.test.mjs netlify/tests/attack.test.mjs netlify/tests/budget.test.mjs` | 25 | 0 |
| `node --test netlify/tests/e2e.test.mjs` | 5 | 0 |
| `detect-secrets scan` (excluding tests, node_modules, dist) | no findings | — |

## Manual checks still needed

- Real provider chat with the owner's own key on the live site.
- Real iPad and iPhone in Safari: layout, Paste button, Add to Home Screen.
- Real Android phone: install prompt.
