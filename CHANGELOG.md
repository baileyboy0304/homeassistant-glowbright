# Changelog

## 0.1.0rc3 — 2026-10-12

- Fix current unit rates and standing charges being read from consumption
  resources. Read the matching cost resource's tariff, as Bright's tariff screen
  does; the two resources can report different rates.
- Use the selected historical cost resource, or the unique matching cost
  resource in the same Virtual Entity when historical costs are disabled.
  Missing or ambiguous matches leave tariffs unknown instead of guessing.
- Discard cached tariffs from the old source on upgrade. Retain last-good rates
  during outages only when they came from the same cost resource.
- Expose tariff source, last successful tariff refresh, and error status in
  sensor attributes and diagnostics. Historical statistics remain unchanged.

## 0.1.0rc2 — 2026-10-11

- Add a persistent, keyboard-accessible Home tile to the native panel header,
  with the requested 96 × 88 px layout and outlined house icon.
- Navigate directly through Home Assistant's router to `/home-launcher/home`,
  independent of graph navigation and the currently displayed account.
- Add a validated **Home launcher path** option. Keep the current HTTP/HTTPS
  origin and reject external or malformed destinations.
- Preserve the header and its keyboard focus during data refreshes. Home works
  before meter data loads and is available to permitted non-admin users.
- Add navigation regression tests and a launcher/ordinary-user fixture to the
  disposable HA demo. No device services, tokens, ingress messages or global
  Home Assistant sidebar settings are changed.

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
