# Pstryk Energy for Home Assistant

A custom integration for the [Pstryk Energy](https://pstryk.pl) dynamic electricity tariff (Poland). It polls the official Pstryk integrations API and exposes hourly spot prices, running cost estimates, and meter consumption as Home Assistant entities — ready to drive automations ("run the dishwasher when power is cheap") and the built-in Energy Dashboard.

This is a community project and is not affiliated with or endorsed by Pstryk.

## Features

- **Live hourly prices** — current price, next hour price, and the exact time of the next price change, with the full day's curve exposed as attributes (great for charts).
- **Cheapest window finder** — rolls a configurable 1–8 hour window over today's prices and surfaces the cheapest block, so "start the washing machine at 23:00" becomes data instead of guesswork.
- **Is-it-cheap binary sensor** — one entity that flips ON when the current hour is among the cheapest of the day.
- **Real cost tracking** — today / yesterday / month-to-date cost in PLN, computed from your actual meter data with a per-component breakdown (energy, distribution, service, excise, VAT).
- **Consumption sensors** — kWh today / yesterday / month plus a kW power estimate from minute-resolution meter reads. Energy device classes are set, so the sensors drop straight into the HA Energy Dashboard.
- **Tomorrow prices** — picked up automatically once Pstryk publishes them (usually around 13:00–14:00 Polish time).
- **Robust API client** — rate-limit aware (stops retrying when the server says slow down), retries failures, and triggers re-authentication if the API key stops working.

## Requirements

- Home Assistant **2025.6 or newer** (integration requires HA >= 2025.6; tested against 2026.9).
- A Pstryk account with a dynamic tariff and a smart meter reporting to Pstryk.
- A **Pstryk API key** — generate one in the Pstryk mobile app under **Integrations** (choose an integration key). Keep it secret; it grants read access to your meter and pricing data.

## Installation

### HACS (recommended)

1. Push/clone this repository to your GitHub account (it must be reachable at `https://github.com/<you>/pstryk-ha-next`).
2. In Home Assistant, open **HACS → ⋮ (three dots) → Custom repositories**.
3. Add `https://github.com/<you>/pstryk-ha-next` with category **Integration**.
4. Find **Pstryk Energy** in HACS and download it.
5. Restart Home Assistant.

### Manual

Copy `custom_components/pstryk_energy/` into the `custom_components/` directory of your HA configuration, then restart Home Assistant.

> If you previously used the old `ha_Pstryk` integration or a `pstryk` custom component, remove them first to avoid domain and entity confusion.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration** and search for **Pstryk Energy**.
2. Paste your API key (from the Pstryk mobile app → **Integrations**). The key is validated live during setup — a bad key fails immediately instead of at runtime.
3. Submit. Entities appear after the first coordinator refresh (within a minute or so).

To change the API key later, remove the integration and add it again. All other settings live in **Configure** (options).

## Entities

| Entity | Description | Notable attributes |
|---|---|---|
| `sensor.pstryk_current_price` | Current hour price in PLN/kWh (basis per option) | `today_prices`, `tomorrow_prices`, `hour_rank_today`, `tge_spot`, `dist`, `service`, `vat`, `excise`, `is_cheap`, `is_expensive` |
| `sensor.pstryk_next_hour_price` | Price for the next hour | `delta_vs_current` |
| `sensor.pstryk_next_price_change` | Timestamp of the next price change | `new_price`, `delta` |
| `sensor.pstryk_today_avg_price` | Today's average price | `min`, `max`, `min_hour`, `max_hour` |
| `sensor.pstryk_tomorrow_avg_price` | Tomorrow's average price (unavailable until publication) | `min`, `max`, `min_hour`, `max_hour` |
| `sensor.pstryk_cheapest_window` | Average price of today's cheapest N-hour window | `start`, `end`, `length` |
| `binary_sensor.pstryk_is_cheap_now` | ON when the current hour is cheap | — |
| `sensor.pstryk_cost_today` | Electricity cost so far today (PLN) | per-component breakdown (`energy_net`, `dist_var_net`, `dist_fix_net`, `service_net`, `excise`, `vat`) |
| `sensor.pstryk_cost_yesterday` | Total cost yesterday (PLN) | per-component breakdown |
| `sensor.pstryk_cost_month` | Month-to-date cost (PLN) | `forecast`, `avg_per_day`, `daily` |
| `sensor.pstryk_hourly_cost` | Cost of the last completed hour (PLN) | `as_of` |
| `sensor.pstryk_consumption_today` | kWh consumed today | `hourly` (per-hour kWh + cost) |
| `sensor.pstryk_consumption_yesterday` | kWh consumed yesterday | — |
| `sensor.pstryk_consumption_month` | kWh this month (completed days) | — |
| `sensor.pstryk_power` | Instantaneous power estimate (kW) | — |

`sensor.pstryk_consumption_today` uses the `energy` device class with `total_increasing` state class, so it can be added directly to the HA Energy Dashboard as a grid consumption source.

## Options

Open the integration's **Configure** dialog:

| Option | Range | Default | Meaning |
|---|---|---|---|
| Cheapest window length | 1–8 hours | 3 | Window size used by `sensor.pstryk_cheapest_window` |
| Price basis | gross / net | gross | Whether sensors report prices with VAT (`gross`) or without (`net`) |
| Usage poll interval | 5–30 minutes | 10 | How often meter/usage data is refreshed |

## Dashboards

The [`dashboards/`](dashboards/) directory ships three ready-made [ApexCharts](https://github.com/RomRider/apexcharts-card) cards (in Polish) plus an Energy Dashboard guide:

- `price-today-tomorrow.yaml` — today's and tomorrow's hourly price curve, so cheap and expensive hours are easy to spot.
- `price-vs-consumption.yaml` — price overlaid with your hourly consumption.
- `cost-month.yaml` — daily cost bars for the current month with a forecast line.

To use them:

1. Install the **apexcharts-card** frontend plugin via HACS (Frontend category).
2. Open a dashboard → edit → **Manual** card (or add to a vertical stack), and paste the YAML from the file.
3. If your installation renamed entities, adjust the `entity:` lines to match.

### Energy Dashboard

`sensor.pstryk_consumption_today` plugs into the native HA Energy Dashboard. Step-by-step instructions (in Polish) are in [`dashboards/energy-dashboard.md`](dashboards/energy-dashboard.md): add it under **Energy → Grid consumption**, and optionally use `sensor.pstryk_cost_today` to cross-check the official cost estimates against Pstryk's billing components.

## Troubleshooting

- **Tomorrow's prices are `unavailable` / missing.** Normal until roughly 13:00–14:00 Polish time — that's when Pstryk (via the power exchange) publishes next-day prices. They appear automatically; no restart needed.
- **`sensor.pstryk_power` shows 0 or nothing right after setup.** It needs a fresh minute-resolution read from the API; give it one poll interval.
- **Rate limited / update failures.** The API enforces rate limits. The client stops retrying when rate-limited and waits for the next scheduled poll — lower the usage poll interval only if failures persist.
- **`404` / invalid key errors, or a re-authentication prompt.** The API key was rejected — regenerate it in the Pstryk app (**Integrations**) and reconfigure the integration.
- **Entities missing after install.** Confirm the integration loaded (Settings → Devices & Services → Pstryk Energy), and check you removed any older Pstryk custom component.
- **Diagnostics.** Settings → Devices & Services → Pstryk Energy → *device* → ⋮ → **Download diagnostics**. The export is redacted — it strips the API key and personal data before writing.

## Development

This repo uses [uv](https://docs.astral.sh/uv/) for environment and
dependency management:

```bash
uv sync       # create .venv with dev dependencies
uv run pytest # run the test suite (offline, ~1s)
```

Tests run fully offline against recorded API fixtures in `tests/fixtures/`
(personal meter data scrubbed to synthetic values; pricing is public TGE
data). To re-record fixtures against the live API, put your key in a `.env`
file (`PSTRYK_API_KEY=...`) and run:

```bash
uv run python scripts/record_fixtures.py
```

The script reads the key from `.env` (gitignored) and never prints or
stores it in the fixtures.

See `docs/architecture.md` (design, verified API contract, DST rules) and
`docs/development.md` (testing patterns, harness quirks, release process)
before changing anything time- or timezone-related.

## License

Released under the [MIT License](LICENSE).
