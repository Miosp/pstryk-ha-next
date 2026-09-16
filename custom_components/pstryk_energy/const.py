"""Constants for the Pstryk Energy integration."""
from zoneinfo import ZoneInfo

DOMAIN = "pstryk_energy"
TZ_WARSAW = ZoneInfo("Europe/Warsaw")
BASE_URL = "https://api.pstryk.pl/integrations/meter-data/unified-metrics/"

CONF_API_KEY = "api_key"
CONF_WINDOW_HOURS = "window_hours"
CONF_PRICE_BASIS = "price_basis"
CONF_POLL_MINUTES = "poll_minutes"

DEFAULT_WINDOW_HOURS = 3
DEFAULT_PRICE_BASIS = "gross"
DEFAULT_POLL_MINUTES = 10

PRICE_BASIS_GROSS = "gross"
PRICE_BASIS_NET = "net"
