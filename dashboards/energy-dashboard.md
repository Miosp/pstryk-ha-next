# Home Assistant Energy Dashboard setup

1. Settings → Dashboards → Energy
2. Grid consumption → Add:
   - Consumption: `sensor.pstryk_consumption_today`
     (device_class energy, total_increasing, daily reset — statistics ready)
   - Cost: choose "Use current price" and pick `sensor.pstryk_current_price`
     (dynamic tariff — HA multiplies hourly kWh by the hourly gross price).
3. Done. Pstryk cost sensors (`sensor.pstryk_cost_today` etc.) remain
   available for Lovelace cards and automations; the Energy dashboard
   computes its own cost from the price entity.

Requires `apexcharts-card` frontend plugin (HACS → Frontend → "ApexCharts card").
