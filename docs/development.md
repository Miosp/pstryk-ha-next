# Development guide

## Toolchain: uv

[uv](https://docs.astral.sh/uv/) manages the interpreter and dev deps
(`pyproject.toml`, `[dependency-groups] dev`). The project is not an
installable package (`[tool.uv] package = false`) — it's a workspace for a
Home Assistant `custom_components/` directory.

```bash
uv sync                     # create/update .venv with dev deps (uses .python-version)
uv run pytest               # run the suite
uv run python scripts/record_fixtures.py   # re-record API fixtures (needs .env)
uv run python -m compileall custom_components scripts
```

`.python-version` pins the dev interpreter. HA harness compatibility is the
real constraint: `pytest-homeassistant-custom-component` must match the HA
APIs used — the suite is currently green against the 2026.9 harness on
Python 3.14; bump deliberately and expect API shifts (see Quirks below).

## Tests

55 tests, ~1.5 s, fully offline against recorded fixtures
(`tests/fixtures/*.json`) plus time-relative synthetic data builders.

Patterns that matter:

- **Mock dispatch**: one `aioclient_mock.get` with a `side_effect` that
  routes on `url.query.get("temporal") == "latest"` → dict-shaped
  `frames`, else list-shaped. See `tests/conftest.py::setup_entry`.
- **Sensor tests** load the entry via mocked HTTP, then push synthetic data
  with `coordinator.async_set_updated_data(...)` (a plain sync call on the
  2026.9 harness) and assert on `hass.states`.
- **Time-flake discipline**: every assertion that depends on "now" must
  handle the boundary windows — late-day (<3 published hours remain →
  cheapest window is unknown), early-month (synthetic day-2 frame falls in
  the previous month → `pytest.skip`), DST days (23/25-hour days →
  `_day_frames` builds wall-clock-complete days; counts asserted as
  `>= 23`). Gate math is unit-tested with **fixed datetimes**, never
  `utcnow()` deltas.
- **Retry test** patches `api.RETRY_BACKOFF_S` to `(0, 0, 0)` — no real
  sleeps in the suite.

### Recording fixtures

`scripts/record_fixtures.py` reads the API key from `.env` (gitignored,
format `PSTRYK_API_KEY=...` or a bare key) and records four payloads.

**Privacy**: personal meter/cost figures are scrubbed to a deterministic
synthetic pattern before writing (`_scrub_personal`) — frames metrics, the
top-level `summary` block, `power_fee_cost_net`, export totals. Only
`pricing.json` (public TGE market data) is kept verbatim. If a new personal
field appears in the API, extend the scrubber AND re-scrub the committed
fixtures; never commit raw recordings.

## Harness quirks (2026.9 era — memorize before bumping)

| Quirk | Workaround in this repo |
|---|---|
| `payload=` removed from aioclient_mock | use `json=` |
| `mock_calls` tuple | headers at `mock_calls[0][3]` |
| `async_set_updated_data` awaited | now a plain sync call |
| `_attr_suggested_object_id` dropped | preset `self.entity_id = "sensor.pstryk_*"` |
| `async_forward_platform_setups` gone | `async_forward_entry_setups` |
| OptionsFlow needs entry | framework-injected `self.config_entry` |
| `hass.helpers.*` removed | direct imports from `homeassistant.helpers` |

## Dashboard cards

`dashboards/*.yaml` are `custom:apexcharts-card` 2.2.3 configs;
`data_generator` JS reads the attribute contracts listed in
`architecture.md`. Traps verified the hard way — check against the 2.2.3
sources (README at tag + `src/types-config-ti.ts`), not the master README,
and don't reintroduce:

- Generator sandbox exposes **`entity`** only — use `entity.attributes`,
  `entity.state`; bare `attributes`/`state` throw.
- `in_header`, `legend_value`, `name_in_header` live **under the series
  `show:` block** per the validator, despite the README listing them flat.
- Card-level `yaxis.decimals` (default **1**) overrides
  `apex_config.yaxis`; tooltip/header precision comes from series
  `float_precision` (max digits — fixed trailing zeros need an
  `EVAL:function` tooltip formatter via `apex_config`).
- `now:` (current-time marker) is **card-level**, not per-series.
- **Three series (column + 2 lines) collapse bars to 1px** in 2.2.3
  regardless of `columnWidth` — keep mixed charts at column + one line.
- An `in_chart: false` series **still contributes to axis scaling** —
  header-only values need a real side entity card instead.
- Different units sharing an axis stretch it invisibly (a 2.2 PLN/kWh price
  spike on a kWh axis); give each unit its own axis, and set `min: 0`
  explicitly when a line series would auto-snap the floor above zero.
- `new Date("YYYY-MM-DD")` parses as **UTC midnight** (ECMAScript date-only
  rule) → append `T00:00:00` for local midnight.
- `span: end: day` windows end today; a series whose endpoint is
  end-of-month needs `span: start: month` or it renders clipped.
- `chart.zoom` does not work on touch devices — left disabled.

## Release / HACS

- `hacs.json` (integration type), version lives in
  `custom_components/pstryk_energy/manifest.json` (HACS reads it; keep in
  sync with `pyproject.toml`).
- Release = annotated tag `vX.Y.Z` on the commit to ship. Repo layout for
  HACS: this repository root, category "Integration".
- Known accepted limitations (documented, don't "fix" silently):
  single-entry design (entity_id presets collide on a second entry),
  English-only Gross/Net option labels.
- Diagnostics redact the API key; fixtures are scrubbed. If history ever
  contained raw personal data, rewrite before pushing publicly.
