"""Record live API payloads as test fixtures. Usage: python scripts/record_fixtures.py

Reads PSTRYK_API_KEY (or bare key) from .env. Never prints or stores the key.
Recorded personal metrics (meter/cost figures) are scrubbed to deterministic
synthetic values automatically; only public TGE pricing data is kept verbatim.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Warsaw")
BASE = "https://api.pstryk.pl/integrations/meter-data/unified-metrics/"
OUT = Path(__file__).parent.parent / "tests" / "fixtures"


def load_key() -> str:
    env = Path(__file__).parent.parent / ".env"
    if not env.is_file():
        sys.exit("No API key found in .env (file missing)")
    text = env.read_text()
    m = re.search(r"^\s*(?:PSTRYK[_A-Z]*\s*=\s*)?([A-Za-z0-9_.-]{20,64})\s*$", text, re.M)
    if not m:
        sys.exit("No API key found in .env")
    return m.group(1)


def get(key: str, params: dict) -> dict:
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{BASE}?{qs}", headers={"Authorization": key})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scrub_frame_metrics(frame: dict, index: int) -> None:
    """Replace personal meter/cost figures with a deterministic synthetic
    pattern, preserving frame shape and public pricing fields."""
    synth_kwh = round(0.4 + (index % 7) * 0.25, 3)
    m = frame.get("metrics", {})
    if "meter_values" in m:
        m["meter_values"]["energy_active_import_register"] = synth_kwh
        m["meter_values"]["energy_active_export_register"] = 0
        m["meter_values"]["energy_balance"] = synth_kwh
        m["meter_values"].pop("energy_active_export_register_total", None)
    if "cost" in m:
        c = m["cost"]
        c["energy_import_cost"] = round(synth_kwh * 0.9, 2)
        for key in ("var_dist_cost_net", "fix_dist_cost_net", "energy_cost_net",
                    "service_cost_net", "excise", "vat", "var_dist_cost_vat",
                    "fix_dist_cost_vat", "power_fee_cost_net"):
            if key in c:
                c[key] = round(synth_kwh * 0.1, 2)
        c["energy_sold_value"] = 0
        c["energy_sold_value_net"] = 0
        c["energy_balance_value"] = c["energy_import_cost"]


def _scrub_personal(payload, name: str):
    if name == "pricing.json":
        return payload
    frames = payload.get("frames")
    if isinstance(frames, list):
        for i, frame in enumerate(frames):
            _scrub_frame_metrics(frame, i)
    elif isinstance(frames, dict):  # latest.json: dict keyed by metric
        meter = frames.get("meter_values", {})
        meter["energy_active_import_register"] = 0.005
        meter["energy_active_export_register"] = 0
        meter["energy_balance"] = 0.005
        meter.pop("energy_active_export_register_total", None)
        cost = frames.get("cost", {})
        cost["energy_import_cost"] = 0.61
        for key in ("var_dist_cost_net", "fix_dist_cost_net", "energy_cost_net",
                    "service_cost_net", "excise", "vat", "var_dist_cost_vat",
                    "fix_dist_cost_vat", "power_fee_cost_net"):
            if key in cost:
                cost[key] = 0.05
        cost["energy_sold_value"] = 0
        cost["energy_sold_value_net"] = 0
        cost["energy_balance_value"] = 0.61
    # Range responses carry a top-level summary with personal totals —
    # nothing consumes it, so drop the personal parts entirely.
    summary = payload.get("summary")
    if isinstance(summary, dict):
        summary.pop("meter_values", None)
        summary.pop("cost", None)
    return payload


def main() -> None:
    key = load_key()
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(TZ)
    yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    fixtures = {
        "latest.json": get(key, {
            "metrics": "meter_values,cost,pricing", "temporal": "latest", "resolution": "hour"}),
        "pricing.json": get(key, {
            "metrics": "pricing", "resolution": "hour",
            "window_start": iso(yesterday), "window_end": iso(yesterday + timedelta(days=3))}),
        "hourly.json": get(key, {
            "metrics": "meter_values,cost", "resolution": "hour",
            "window_start": iso(now.replace(hour=0, minute=0, second=0, microsecond=0)),
            "window_end": iso(now)}),
        "daily.json": get(key, {
            "metrics": "meter_values,cost", "resolution": "day", "for_tz": "Europe/Warsaw",
            "window_start": iso(month_start), "window_end": iso(now)}),
    }
    for name, payload in fixtures.items():
        _scrub_personal(payload, name)
        text = json.dumps(payload, indent=1)
        (OUT / name).write_text(text)
        note = "" if name == "pricing.json" else " [personal data scrubbed]"
        print(f"wrote {OUT / name} ({len(text)} bytes){note}")


if __name__ == "__main__":
    main()
