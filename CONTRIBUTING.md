# Contributing

Thanks for helping improve ATLAS OS. This is an early-stage project; please keep claims aligned with implemented and tested behavior.

1. Open an issue describing the problem or proposed change.
2. Keep changes focused and document new behavior and limitations.
3. Never include credentials, personal data, or private datasets in commits or test fixtures.
4. Run the backend tests before opening a pull request:
   ```bash
   cd backend
   PYTHONPATH=. python -m pytest -q
   ```
5. Include tests for API behavior and security-sensitive changes.
6. Do not introduce real desktop execution, file transfer, or remote-control actions without explicit authorization, scoped permissions, and tests.
