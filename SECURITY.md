# Security Policy

ATLAS OS is an early-stage project.

## Reporting a vulnerability

Please do not publish exploit details or secrets in public issues. Contact the repository owner privately through the contact method listed on the GitHub profile and include the affected version, impact, and reproducible steps. Do not include real user data, API keys, or access tokens.

## Current security limitations

- There is no ATLAS account. Each visitor uses their own AI key; the function only forwards it to the chosen provider and does not store it. Real-time voice goes straight from the browser to Google Gemini or OpenAI. It has a per-visitor rate limit of 60 requests a minute.
- Memories, chat history and a remembered key are kept in the browser's localStorage. They are not encrypted by ATLAS and do not sync.
- Provider errors are shown with any echoed key replaced; the page is served with a strict script CSP (this site's scripts plus Google's sign-in script).
- See docs/THREAT_MODEL.md for threats, mitigations and residual risks.
- This project has not undergone an independent penetration test or formal security audit.

## Safe use

Never commit `.env` files, API keys, passwords, private datasets, or personal documents. If a secret is exposed, revoke/rotate it immediately; deleting it from the latest commit may not remove it from Git history.
