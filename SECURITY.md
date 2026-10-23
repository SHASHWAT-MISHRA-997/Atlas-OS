# Security Policy

ATLAS OS is an early-stage project and is not yet suitable for untrusted public multi-user production use.

## Reporting a vulnerability

Please do not publish exploit details or secrets in public issues. Contact the repository owner privately through the contact method listed on the GitHub profile and include the affected version, impact, and reproducible steps. Do not include real user data, API keys, or access tokens.

## Current security limitations

- The BYOK chat endpoint has no built-in user authentication or per-user rate limiting.
- Browser-local memory and chat history are not encrypted by this application and do not sync across devices.
- API keys submitted to the chat endpoint are used for that request and are not intentionally persisted by this application; HTTPS and trusted hosting are required in deployment.
- The task planner is simulation-only and does not execute shell commands or operate the desktop.
- This project has not undergone an independent penetration test or formal security audit.

## Safe use

Never commit `.env` files, API keys, passwords, private datasets, or personal documents. If a secret is exposed, revoke/rotate it immediately; deleting it from the latest commit may not remove it from Git history.
