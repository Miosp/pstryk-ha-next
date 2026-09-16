"""Scaffolding sanity checks."""
import json
from pathlib import Path

from custom_components.pstryk_energy.const import BASE_URL, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"


def test_domain_and_url():
    assert DOMAIN == "pstryk_energy"
    assert BASE_URL.endswith("/integrations/meter-data/unified-metrics/")


def test_manifest_shape():
    manifest = json.loads(
        (Path(__file__).parent.parent / "custom_components" / "pstryk_energy" / "manifest.json").read_text()
    )
    assert manifest["domain"] == DOMAIN
    assert manifest["config_flow"] is True
    assert manifest["requirements"] == []


def test_recorded_fixtures_exist():
    for name in ("latest.json", "pricing.json", "hourly.json", "daily.json"):
        payload = json.loads((FIXTURES / name).read_text())
        assert "frames" in payload, name
