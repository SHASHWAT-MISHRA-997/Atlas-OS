# Contributing

Thanks for helping improve ATLAS OS. This is an early-stage project; please keep claims aligned with implemented and tested behavior.

1. Open an issue describing the problem or proposed change.
2. Keep changes focused and document new behavior and limitations.
3. Never include credentials, personal data, or private datasets in commits or test fixtures.
4. Run the backend tests before opening a pull request:
   ```bash
   cd backend
   pip install -r requirements-dev.txt
   python -m ruff check .
   python -m pytest -q -m "not e2e"
   python -m pytest -q -m e2e   # needs: python -m playwright install chromium
   ```
5. Include tests for API behavior and security-sensitive changes.
6. Do not introduce real desktop execution, file transfer, or remote-control actions without explicit authorization, scoped permissions, and tests.
7. Update `docs/FEATURE_MATRIX.md` when a feature's status changes. Mark a feature Verified only with passing acceptance tests in the named environment, and label mocked-provider results as mocked.
