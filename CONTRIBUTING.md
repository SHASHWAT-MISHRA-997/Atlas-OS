# Contributing

Thanks for helping improve ATLAS OS. This is an early-stage project; please keep claims aligned with implemented and tested behavior.

1. Open an issue describing the problem or proposed change.
2. Keep changes focused and document new behavior and limitations.
3. Never include credentials, personal data, or private datasets in commits or test fixtures.
4. Run the tests before opening a pull request:
   ```bash
   npm install
   npm run build
   npm test
   npm run test:e2e   # needs Chromium: npx playwright install chromium
   ```
5. Include tests for behavior and security-sensitive changes. Model providers are always faked in tests, and labelled FAKE.
6. Update `docs/FEATURE_MATRIX.md` when a feature's status changes. Mark a feature Verified only with passing tests in the named environment.
