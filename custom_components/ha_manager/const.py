"""Constants for HA Manager."""

from datetime import timedelta

DOMAIN = "ha_manager"
VERSION = "0.3.0"

PANEL_URL_PATH = "ha-manager"
PANEL_TITLE = "HA Manager"
PANEL_ICON = "mdi:home-heart"
PANEL_COMPONENT = "ha-manager-panel"
STATIC_URL = "/ha_manager_static"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

SCAN_INTERVAL = timedelta(minutes=30)

# Severity levels, worst first.
CRITICAL = "critical"
WARNING = "warning"
TIDY = "tidy"
SEVERITIES = (CRITICAL, WARNING, TIDY)

# Score: points lost per finding, and the most each level can cost in total.
SCORE_WEIGHTS = {CRITICAL: 10.0, WARNING: 3.0, TIDY: 0.5}
SCORE_CAPS = {CRITICAL: 60.0, WARNING: 30.0, TIDY: 10.0}

# Thresholds.
ZOMBIE_DAYS = 90
FLAPPING_TRIGGERS_PER_DAY = 100
BATTERY_LOW = 15
SAFETY_BATTERY_LOW = 20
SAFETY_BATTERY_CRITICAL = 10
SAFETY_TEST_INTERVAL_DAYS = 35

# binary_sensor device classes treated as life-safety, with a plain name.
SAFETY_DEVICE_CLASSES = {
    "smoke": "Smoke",
    "carbon_monoxide": "Carbon monoxide",
    "gas": "Gas",
    "moisture": "Water leak",
}
# Give any entity the label "Life safety" in Home Assistant to include it too.
SAFETY_LABEL_ID = "life_safety"

# Repairs raised by these integrations duplicate our own checks, so they are
# shown for cross-checking but do not count towards the score.
CROSS_CHECK_DOMAINS = {"spook", "watchman"}

BACKUP_MAX_AGE_DAYS = 7

# Naming styles for the naming checker.
STYLE_ROOM_FIRST = "room_first"  # "Kitchen Ceiling Light"
STYLE_NO_ROOM = "no_room"  # "Ceiling Light", the room is set separately
NAMING_STYLES = (STYLE_ROOM_FIRST, STYLE_NO_ROOM)

BATTERY_FORECAST_DAYS = 14  # warn when a battery has this long left
BATTERY_HISTORY_DAYS = 180
BATTERY_BACKFILL_DAYS = 120

REPORT_HISTORY_KEEP = 26
PLAN_STORAGE_KEY = f"{DOMAIN}_plan"
PLAN_IMAGE_MAX = 2_000_000  # characters of data URL, roughly 1.5 MB of picture

CHANGES_STORAGE_KEY = f"{DOMAIN}_changes"
CHANGES_KEEP = 500
