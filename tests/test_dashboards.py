"""Dashboard YAML sanity."""
from pathlib import Path

import yaml

DASHBOARDS = Path(__file__).parent.parent / "dashboards"


def test_all_dashboard_yamls_parse():
    dashboards = list(DASHBOARDS.glob("*.yaml"))
    assert dashboards, f"No dashboards found in {DASHBOARDS}"
    for f in dashboards:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert isinstance(doc, dict), f
        assert doc["type"] == "custom:apexcharts-card", f
        assert "series" in doc, f
