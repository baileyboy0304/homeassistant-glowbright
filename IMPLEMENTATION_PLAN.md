# GlowBright implementation plan

Research date: 8 September 2026. Target: Home Assistant 2026.9+.
New implementation in an empty workspace; no integration was cloned or forked.
Repository identity: baileyboy0304/homeassistant-glowbright. MIT, initial version 0.1.0.

## Reference review (phase 1)

All references below were read before implementation. Downloaded reference files
are ignored research material, not vendored integration code.

| Reference | Design informed / deliberate differences |
| --- | --- |
| [Core SRP coordinator](https://github.com/home-assistant/core/blob/dev/homeassistant/components/srp_energy/coordinator.py) | Separate consumption and cost external statistics; interval state and running sum; delayed revisions. Do not adopt blanket trailing-nonzero trimming. |
| [Core SolarEdge coordinator](https://github.com/home-assistant/core/blob/dev/homeassistant/components/solaredge/coordinator.py) | Re-fetch recent data, obtain a sum before the rewrite window, overwrite original timestamps. Extend the query backwards across gaps rather than taking an unrelated global latest sum. |
| [Core Opower coordinator](https://github.com/home-assistant/core/blob/dev/homeassistant/components/opower/coordinator.py) | Executor-backed Recorder access, historical insertion and explicit ownership/migrations. |
| [Core Elvia importer](https://github.com/home-assistant/core/blob/dev/homeassistant/components/elvia/importer.py) | Simple interval state/cumulative sum external import. |
| [Core kitchen_sink](https://github.com/home-assistant/core/blob/dev/homeassistant/components/kitchen_sink/__init__.py) | Native kWh energy and cubic-metre volume external statistics. |
| [Octopus statistics and flow](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/tree/develop/custom_components/octopus_energy) | Inspected statistics/consumption.py, cost.py, __init__.py and config_flow.py. Separate costs, bounded baseline queries and independent meter selection. Current metadata includes mean_type/unit_class but also deprecated has_mean: omit the latter. Aggregate actual instants, not pairs by array index. No Kraken/GraphQL API or source copied. |
| [existentia](https://github.com/existentia/hildebrand-glow-ha) | Catchup throttling, chunk import, trailing-sum repair and stopping checks. Do not adopt its supplementary today-total design as the Energy source. |
| [jonandel](https://github.com/jonandel/ha-hildebrandglow-dcc) | Bright authentication, tariff retrieval, resource.catchup and HACS packaging. No daily-reset Energy sensor. |
| [zMastaa](https://github.com/zMastaa/hildebrand-glow-ha) | Preserve Virtual Entities and fetch tariffs automatically. Its nested classifier dictionary still collapses same-classifier resources within one VE: use (ve_id, resource_id) throughout. |
| [PixelShorts](https://github.com/PixelShorts/hildebrand-glow-ha) | Timestamp-based half-hour aggregation and historical backfill concepts. Do not adopt sensor-owned statistics or synthetic present-day zeros. |
| [root0x](https://github.com/root0x/ha-hildebrandglow-dcc) | PT30M historical readings and tariff concepts only. No historical-sensor dependency. |

Authoritative contracts:

- [Bright individual API PDF](https://docs.glowmarkt.com/GlowmarktAPIDataRetrievalDocumentationIndividualUserForBright.pdf).
  The older individual-user PDF explicitly redirects Bright users here.
- [Live resources Swagger](https://api.glowmarkt.com/api-docs/v0-1/resourcesys/),
  including swagger-ui-init.js: readings supports integer `nulls=1`, UTC queries
  with offset=0, first-time/last-time, tariff and tariff-list. Tariff history is
  unordered and cannot necessarily precede registration. Catchup is asynchronous.
- [Recorder API changes](https://developers.home-assistant.io/blog/2025/10/16/recorder-statistics-api-changes/)
  and actual Core 2026.9.0 recorder models/statistics.py and statistics.py.
- [Manifest](https://developers.home-assistant.io/docs/creating_integration_manifest/):
  hub models an account with multiple meters; explicit Recorder/panel dependencies.
- [Local branding](https://developers.home-assistant.io/docs/core/integration/brand_images/):
  custom integrations support a local brand directory since 2026.3.

## Architecture (phase 2)

Recorder external hourly statistics are canonical. Sensors have no state_class.
IDs are `glowbright:<entry_id>_<fuel>_consumption` and `_cost`. Resource identity,
conversion parameters and cost identity are persisted alongside owned IDs. A fuel
resource change explicitly clears only that fuel's two owned statistics and
rebuilds. A conversion change likewise rebuilds gas. No cross-meter concatenation.

Resource dataclass: VE ID/name, resource ID/name, classifier, base unit, active,
first/last reading. Discovery returns a list, never a classifier-keyed map.
Consumption selectors are independent. Cost candidates are restricted to the
selected VE and classifier; an advanced selector resolves ambiguity.

API uses the HA aiohttp session, a locked expiring JWT, accountId unique identity,
one forced reauthentication on server 401, bounded exponential retry/jitter for
429/5xx/network faults, typed sanitized errors, named query limits and half-open
boundary filtering. No passwords/tokens in logs or diagnostics. Tokens stay in
memory; restart authentication is acceptable for v0.1.

### Rewrite algorithm and invariants

1. Request UTC PT30M with nulls=1; filter [start,end), deduplicate timestamp per
   resource, exclude intervals beyond last-time and still-open hours.
2. Import an hour only with both half-hours known. A partial new response cannot
   replace a known complete hour. Recent windows will retry incomplete hours.
3. Under one import lock, read the last sum strictly before H0 with a time-bounded
   query, expanding backward to epoch if there is a gap. Read all existing states
   from H0 through the latest stored hour, even for an old backfill chunk.
4. Merge authoritative complete new hours over existing states. Missing stays
   missing; known states survive. Recompute every following sum from baseline.
5. Import at original UTC starts, flush Recorder before releasing the lock or
   saving a progress checkpoint. No per-hour deletion. No arrival-time spike.
6. All synchronous queries execute on Recorder's executor. Track and shield an
   in-flight query during cancellation, drain it before unload, check stopping
   before each new Recorder operation.

Consumption metadata: NONE mean_type, has_sum, EnergyConverter/kWh or
VolumeConverter/m³. Cost metadata: NONE mean_type, has_sum, unit_class=None, GBP.
No has_mean. Native gas volume is default. Optional conversion requires explicit
calorific value and correction factor and is labelled estimated. Cost uses only
historical same-VE cost resources, converting pence to GBP according to units;
never today's tariff, never synthetic standing charges.

### Lifecycle and UI

Setup authenticates/discovers, restores compact Store state and starts a
ConfigEntry background task. Poll hourly; catchup best effort at conservative
two-hour intervals. Last-good values survive transient failures; auth failures
require reauth. Backfill: first-time boundary, default 365 days, oldest first in
30-day PT1H chunks, then recent 7-day PT30M. Excessive-range 400 halves chunks.
Checkpoint each committed chunk, retry failed chunks, resume after restart,
cancel and drain safely at stop/unload. No permanent second historical database.

ConfigEntry.data: credentials/account identity. options: independent resource
keys, cost choices, backfill/window, panel and gas conversion settings. Versioned
flow, reauth, reconfigure and options; English translations in translations/en.json.

Bundled plain web component + SVG, no CDN. Authenticated WebSockets validate
domain, loaded entry and HA user access to account devices. Status is explicitly
allowlisted. PT30M uses bounded TTL memory cache; other periods query Recorder
hourly states and aggregate by Europe/London calendar boundaries. Local dates
convert to UTC before querying, so 23/25-hour DST days work. Staleness, partial
coverage and cached/outage status stay visible. Plural static-path registration
and panel_custom; sidebar available to non-admin users with access.

## Implementation and release gates

3–4. Skeleton, client, discovery and independent config flow.
5–6. Recorder importer and real Recorder regression tests for delayed/revised
data. **Do not implement phases 7+ until those tests pass.**
7. Cost and tariff support.
8. Resumable background backfill and lifecycle.
9. Informational sensors, devices, diagnostics.
10. Bundled responsive panel and validated WebSockets.
11. pytest-homeassistant-custom-component, current HA aiohttp mocks, actual Recorder helper
assertions; DST, selection, auth/retry, ownership, cost/unit compatibility,
shutdown and panel access coverage. Run hassfest and HACS validation honestly.
12. Real HACS installation, Bright login, multi-VE selection, backfill and actual
Energy selectors/dashboard plus desktop/mobile panel. Requires a reachable HA
instance and interactive account login. Automated fixture-based HA tests cannot
substitute for this gate. No release until it is completed.

Evidence and remaining acceptance work are recorded in VALIDATION.md. The
six phase-six regression cases passed before cost, backfill and frontend work
began. Current HA aiohttp test helpers replaced the initially proposed
aioresponses dependency because of compatibility with the current aiohttp.
