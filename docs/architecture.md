# Architecture

`pstryk_energy` — Home Assistant custom integration for the Pstryk Energy
(Poland) dynamic electricity tariff. Consumer-focused: no solar/export logic,
no MQTT, no carbon metrics.

## Layering

```
api.py            thin transport: URL/params, auth header, status→exception
   ↓
models.py         pure dataclasses + derived math, no HA imports (except const)
   ↓
coordinator.py    scheduling, gated sub-fetches, error translation
   ↓
sensor.py / binary_sensor.py / config_flow.py / diagnostics.py
```

- `api.py` never parses; `models.py` never fetches; sensors never compute
  anything a model helper doesn't already expose.
- All modules use relative imports (`from .const import ...`) — hassfest style.

## The API (verified live, 2026-09)

Single endpoint:

```
GET https://api.pstryk.pl/integrations/meter-data/unified-metrics/
Authorization: <raw API key>          # no prefix, no Bearer
```

Query params:

| Param | Values | Notes |
|---|---|---|
| `metrics` (required) | `meter_values,cost,carbon,pricing` | comma-combined |
| `resolution` | `minute,hour,day,month` | required |
| `temporal` | `range` (default), `latest` | `latest` ignores window params |
| `window_start`, `window_end` | ISO-8601 UTC | half-open; hour buckets |
| `for_tz` | e.g. `Europe/Warsaw` | **400 with `resolution=hour`** — day/month only |
| `breakdown` | `none`, `device` | unused here (single meter per key) |

### Hard-won facts (each cost a bug or a probe)

- **`temporal=latest` buckets** (verified by double-probe 70 s apart):
  `meter_values` = kWh consumed in the **last minute** → power estimate =
  value × 60 kW; `cost` = **last completed hour** (value frozen during the
  running hour, `as_of` = completion); `pricing` = current hour.
- **Tomorrow's prices are `null`** (tge/gross/net) until publication
  ~13:00–14:00 Polish time. Nulls are "not published", never an error.
- `latest` returns `frames` as a **dict keyed by metric**; range queries
  return a **list of frames** plus a `summary` block with window totals.
- Hourly `cost` frames carry 1/24 of the fixed distribution fee — summing
  hourly `energy_import_cost` reproduces the day total. `energy_import_cost`
  is the gross (VAT-inclusive) figure; use it for all cost sensors.
- 429 responses carry `Retry-After`; 401/403/404 mean bad key / revoked /
  no active contract → reauth.
- Frames are hour buckets aligned to **Warsaw wall clock** even though
  `start`/`end` are UTC (Warsaw day == 22:00Z boundary, CET).

## Coordinators

### PricingDataCoordinator (`PricingData`)
- Window: `_warsaw_midnight(1)` → `_warsaw_midnight(-2)` — yesterday 00:00 →
  tomorrow 24:00 **Warsaw calendar days** (3 local days = 71–73 absolute
  hours across DST; never compute the end as `start + timedelta(days=3)`).
- Refresh: `_next_refresh_interval(now)` aligns to the next hour boundary
  +15 s, floored 30 s, capped 30 min — current price flips promptly at each
  hour change and tomorrow's publication is picked up quickly.

### UsageDataCoordinator (`UsageData`)
- `latest` every poll (default 10 min, option 5–30).
- Hourly-today refetch when `_needs_hour_refetch`: >55 min **or** Warsaw
  date changed. Daily month-to-date refetch when `_needs_day_refetch`:
  >6 h **or** date changed; window = `min(month_start, yesterday midnight)`
  so `cost_yesterday` survives the 1st of the month.
- Gate timestamps commit **only after the whole update succeeds** — a failed
  sibling fetch must not suppress the next refetch.
- Errors: `PstrykAuthError` → `ConfigEntryAuthFailed`; rate-limit/other →
  `UpdateFailed`. Coordinators fail independently.

### DST rules (Europe/Warsaw — transitions at 02:00/03:00, never midnight)

1. Navigate calendar days on the **date component**
   (`local.date() - timedelta(days=N)` + `datetime.combine`), never by
   subtracting absolute `timedelta(days=N)` from an aware datetime — that
   lands at 23:00/01:00 local across transition nights.
2. A Warsaw day is **23, 24, or 25 hours long**. Any consumer that assumes
   24 frames/day breaks twice a year; `for_day()` + wall-clock-complete
   generation handle it.
3. Tests must generate synthetic days wall-clock-complete (see
   `_day_frames` in `tests/test_sensors_price.py`).

## Entities

One device per config entry, 14 sensors + 1 binary sensor, prefix `pstryk_`.
Entity IDs are preset explicitly (HA 2026.x drops `suggested_object_id`).

Attribute contracts (also consumed by `dashboards/*.yaml` data generators):
- `sensor.pstryk_current_price` → `today_prices`, `tomorrow_prices`:
  `[{start, gross, net, is_cheap}]`; tomorrow entries carry nulls until
  published.
- `sensor.pstryk_cost_month` → `daily: [{start: "YYYY-MM-DD", cost}]`,
  `forecast`, `avg_per_day`.
- `sensor.pstryk_consumption_today` → `hourly: [{start, kwh, cost}]`.

State classes (recorder-correct statistics):
- `consumption_today`: `TOTAL_INCREASING` (kWh never negative, daily reset).
- `cost_today`: `TOTAL` + `last_reset` (Warsaw midnight) — negative-spot
  hours can dip the running sum, which TOTAL_INCREASING would misread as a
  reset.
- `cost_yesterday/month`, `consumption_yesterday/month`: `MEASUREMENT` —
  period-report values that replace wholesale; meters they are not.
- `power`: staleness-guarded `max(15, 1.5 × poll_minutes)`; a stalled feed
  reports unknown instead of a constant kW.

Cheapest window is **forward-looking**: only published frames with
`f.end > now`; a window over elapsed hours is useless for load shifting.
Window *selection* ranks on gross (VAT is monotonic), displayed value
honors the gross/net option.

## Config flow

Single step (API key, validated live via `temporal=latest`), unique_id =
`sha256(key)`. Reauth re-derives the hash, aborts on duplicates (framework
excludes the entry being reauthenticated), and propagates the new unique_id
via `async_update_reload_and_abort(..., unique_id=...)`. Options: window
hours 1–8 (default 3), price basis gross/net, poll minutes 5–30 (default
10); every option change reloads the entry.
