# Changelog

## 0.1.0rc1 — 2026-09-08

First numbered release candidate for HACS installation and testing.

- Import delayed and revised Bright DCC readings into hourly Home Assistant
  Recorder statistics at their original timestamps.
- Select electricity and gas independently across Virtual Entities, with
  matching historical cost resources and native m³ gas support.
- Resume historical backfill and refresh recent intervals without erasing
  known data when the API is unavailable.
- Include the bundled usage/cost panel, informational sensors, diagnostics,
  original branding and English configuration translations.
- Include the CI import-path fix and current GitHub Actions versions.

The integration, Python project and diagnostics use `0.1.0rc1`; the immutable
Git tag and GitHub pre-release use `v0.1.0rc1`. Later candidates and releases
will each receive a new version; published tags will not be moved.

User-supplied screenshots show successful Energy Dashboard usage. Remaining
live-source and panel acceptance checks are tracked in [VALIDATION.md](VALIDATION.md)
before stable 0.1.0. Historical usage costs exclude standing charges.
