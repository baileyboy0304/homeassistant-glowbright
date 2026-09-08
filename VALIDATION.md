# GlowBright 0.1.0 validation record

Recorded 8 September 2026. **Stable-release acceptance is not complete.**
Version `0.1.0rc1` is the first numbered release candidate, requested by the user
after installation; it does not mark the remaining stable-release gates complete.

## Automated results

Environment: Ubuntu under WSL, Python 3.14, Home Assistant 2026.9.1,
pytest-homeassistant-custom-component 0.13.364, HA frontend 20260826.6.

| Check | Result |
| --- | --- |
| `pytest` | 40 passed; actual HA Recorder database and current HA aiohttp mocks |
| `node --test tests/frontend.test.mjs` | 5 passed: bundled calendar functions and reconnect registration |
| `node --check custom_components/glowbright/frontend/glowbright-panel.js` | Passed |
| `ruff check custom_components tests` | Passed |
| `ruff format --check custom_components tests` | Passed |
| Official `script.hassfest --integration-path .../custom_components/glowbright` | 1 integration, 0 invalid integrations, no validation warnings |
| HACS GitHub Action | Passed on published implementation commit `f751841` |

The six phase-six regression cases passed before implementing costs, backfill
and the panel. They import and query real Recorder statistics: a delayed Monday
hour changes Monday, an upward revision propagates through later cumulative
sums, missing responses preserve history, older backfill adjusts the later
baseline, and both UK DST days preserve zero readings and continuous sums.

### Coverage against the requested cases

Numbers refer to the mandatory tests in the project brief. Parameterized tests
and combined scenarios cover multiple requirements; these are not 38 separate
test functions.

| Requested cases | Evidence |
| --- | --- |
| 1–3: electricity, dual fuel, independent VEs | `test_coordinator.py::test_selected_resources_and_costs`; `test_config_flow.py::test_independent_flow` |
| 4–5: duplicate electricity/gas classifiers | `test_api.py::test_discovery_keeps_duplicate_classifiers` |
| 6–7: same-VE cost pairing | `test_api.py::test_cost_pairing_stays_in_ve`; selected-resource Recorder tests |
| 8–9: delayed/revised Monday, no Wednesday spike | `test_statistics.py::test_delayed_and_revised_hours` |
| 10–13: preservation after outage, 500, 429, network failure | `test_coordinator.py::test_outage_tariff_and_last_good`; `test_api.py::test_transient_retry` |
| 14–15: expired and server-rejected JWT | `test_api.py::test_expired_and_server_rejected_token`, `test_only_one_reauthentication` |
| 16–18: tariff outage, optional costs, no standing-charge injection | `test_coordinator.py::test_outage_tariff_and_last_good`, `test_selected_resources_and_costs` |
| 19–20: genuine zero, nulls, trailing placeholders | `test_statistics.py::test_dst_and_genuine_zero`, `test_incomplete_hour_does_not_replace_known_hour`; `test_api.py::test_nulls_zeros_and_half_open_chunks` |
| 21–22: half-open PT30M/PT1H chunks, excessive-range retry | `test_api.py::test_nulls_zeros_and_half_open_chunks`, `test_excessive_range_halves_chunk` |
| 23–25: UK DST 23/25 hours and sums | `test_statistics.py::test_dst_and_genuine_zero`; frontend calendar tests |
| 26–28: gas kWh/m³ and explicit conversion | Recorder metadata and selected-resource tests; `test_coordinator.py::test_conversion_is_explicit` |
| 29–31: independent flow, resource rebuild, duplicate account | `test_config_flow.py`; `test_coordinator.py::test_resource_change_rebuilds_one_fuel` |
| 32: current metadata, no deprecated `has_mean` | `test_statistics.py::test_modern_metadata`; `test_websocket.py::test_actual_recorder_metadata` |
| 33–35: electricity, native gas, GBP Energy compatibility | Actual Recorder metadata and first-hour Energy change tests, plus the actual HA Energy UI below |
| 36–37: secrets and account/fuel permissions | `test_websocket.py`; allowlisted diagnostic tests |
| 38: cancel/unload while work is active | `test_coordinator.py::test_unload_cancels_background`; `test_websocket.py::test_cancellation_drains_inflight_query`; full entry unload test |

Additional tests cover resumable failed backfill, cache fallback, same-account
reauthentication, account/fuel device parenting, entry migration, and removing
only the selected entry's statistics while preserving another account.

The first GitHub run passed HACS and hassfest. Its console-script `pytest`
invocation exposed a missing repository import path; pytest configuration now
explicitly includes the project root. Official checkout/setup-python Actions
were also upgraded to v7 after the runner reported deprecated Node 20 targets.

All three GitHub workflows passed on implementation commit `f751841`:
[Tests](https://github.com/baileyboy0304/homeassistant-glowbright/actions/runs/34213734355),
[Hassfest](https://github.com/baileyboy0304/homeassistant-glowbright/actions/runs/34213734349),
and [HACS](https://github.com/baileyboy0304/homeassistant-glowbright/actions/runs/34213734324).

## Actual Home Assistant UI test with synthetic readings

The integration ran in Home Assistant 2026.9.1 with the real frontend, config
flow, Recorder, Energy Dashboard and WebSocket server. Only Glowmarkt responses
were replaced by the disposable fixture in `scripts/run_ha_demo.py`.

Completed through the actual UI:

- Added GlowBright in Devices & services using synthetic credentials.
- Displayed multiple Virtual Entities, including a stale gas alternative.
- Selected electricity from **DCC Sourced full** and gas from **DCC Sourced**.
- Selected their matching historical cost resources and imported all four streams.
- Observed completed backfill checkpoints for all four streams.
- Selected **GlowBright electricity consumption** in Energy configuration.
- Selected **GlowBright electricity cost** for total-cost tracking.
- Selected **GlowBright gas consumption**, with native **m³** metadata, and gas cost.
- Saved Energy settings and displayed historical charts. The synthetic 6 September
  day showed **18 kWh**, **5.4 m³**, **£4.68 electricity** and **£3.78 gas**.
  The newest partial date retained only its available data; it was not a download-day spike.
- Opened GlowBright from the sidebar; exercised electricity/gas, usage/cost,
  30-minute/hour/day/week/month and previous-date navigation.
- Inspected desktop and 390-pixel mobile layouts, freshness and partial coverage.

Screenshots in [`docs/screenshots`](docs/screenshots) are from this synthetic
instance. They are evidence of real HA UI compatibility, **not** evidence that a
live Bright account or HACS download has been tested. Delayed/revised upstream
arrival was exercised in actual Recorder regression tests, not observed from a
live DCC meter. Outage behavior has automated coverage; it was not fault-injected
through every panel control. Dark theme uses HA theme variables but has not had
a separate visual acceptance run.

The disposable Python installation reported missing optional FFmpeg/TurboJPEG
libraries and HA's normal custom-integration warning. Forced WSL test-server
restarts also produced an unclean SQLite session warning. These are not suppressed.
Reconnecting while replacing the panel bundle exposed a duplicate custom-element
registration error; the final guard has a direct regression test. Bundle URLs
also include a content digest to invalidate stale development-install caches.
No GlowBright compatibility/deprecation warnings were observed after correcting
device parenting to the current `via_device_id` API. Hassfest also identified
and prompted fixes for the direct HTTP dependency and config-entry-only schema.

## User installation evidence

The user subsequently supplied a HACS download dialog and an Energy Dashboard
screenshot showing GlowBright electricity consumption together with gas usage
and costs on a historical date. This provides user-supplied installation and
Energy UI evidence beyond the synthetic test instance. It does not independently
verify every selected VE, backfill completion, gas source units, or the arrival
of revised live intervals. The personal screenshots are not republished here.

## Remaining stable-release gates

- [x] Explicit approval to create the **public** GitHub repository
  `baileyboy0304/homeassistant-glowbright` and publish the source.
- [x] Push code; enable issues and set description/topics.
- [x] Run all GitHub Actions, including the official HACS validation, without
  suppressing genuine warnings.
- [ ] Install through HACS custom repositories in a real HA 2026.9+ instance,
  restart, and authenticate a real Bright account inside Home Assistant.
- [ ] Confirm all live VEs/resources, independent fuel choices, tariff data and
  historical cost availability; complete live historical backfill.
- [ ] Repeat electricity/gas/cost Energy selections on the real account and
  verify its historical shape and source units.
- [ ] Observe or deliberately replay delayed/revised real-source intervals and
  verify the original date changes without a current-day spike.
- [ ] Complete desktop/mobile, theme and transient-outage panel acceptance on
  that installation.
- [ ] Only after these gates pass, prepare the stable 0.1.0 tag and GitHub release.

The user explicitly approved public publication and the code was pushed to
`baileyboy0304/homeassistant-glowbright` on 8 September 2026. A real Home
Assistant test URL has not yet been supplied. Bright credentials should be
entered directly in Home Assistant, never in chat.

## Reproduce the synthetic UI

Use a disposable Linux Python 3.14 environment with the pinned dependencies
listed in README. Run `python scripts/run_ha_demo.py` from this repository.
It binds only to `127.0.0.1:8123` and creates ignored local data in `.ha-test`.
The script documents its synthetic login values. Do not deploy this script in a
real Home Assistant configuration; the integration itself contains no demo mode.
Stop it with Ctrl+C when finished.
