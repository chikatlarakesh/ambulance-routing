"""
Central configuration for the ambulance routing system.

All magic numbers live here so they are easy to audit and override via
environment variables or test fixtures.
"""

import os

# ---------------------------------------------------------------------------
# Routing / rerouting
# ---------------------------------------------------------------------------

# Minimum time saving (seconds) required to trigger an automatic reroute.
REROUTE_THRESHOLD_SEC: float = float(os.getenv("REROUTE_THRESHOLD_SEC", "120"))

# Maximum ambulance speed used as the A* haversine heuristic (metres / second).
# 15 m/s ≈ 54 km/h — conservative for urban emergency driving.
A_STAR_MAX_SPEED_MS: float = float(os.getenv("A_STAR_MAX_SPEED_MS", "15.0"))

# How many upcoming segments to inspect for slowdown detection in reroute_check.
SLOWDOWN_LOOKAHEAD: int = int(os.getenv("SLOWDOWN_LOOKAHEAD", "3"))

# Ratio of current travel time to baseline that triggers a slowdown flag.
SLOWDOWN_RATIO: float = float(os.getenv("SLOWDOWN_RATIO", "1.5"))

# ---------------------------------------------------------------------------
# Traffic / edge updates
# ---------------------------------------------------------------------------

# Maximum number of edge updates accepted in a single traffic_snapshot request.
MAX_EDGE_UPDATES_PER_SNAPSHOT: int = int(os.getenv("MAX_EDGE_UPDATES_PER_SNAPSHOT", "500"))

# Valid range for edge multipliers.
MULTIPLIER_MIN: float = float(os.getenv("MULTIPLIER_MIN", "0.01"))
MULTIPLIER_MAX: float = float(os.getenv("MULTIPLIER_MAX", "1000.0"))

# Minimum value for absolute_time overrides (seconds). No upper cap — large values
# are valid for simulating road closures (e.g. 99999s).
ABSOLUTE_TIME_MIN: float = float(os.getenv("ABSOLUTE_TIME_MIN", "0.0"))

# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

# Maximum length for ambulance_id strings.
AMBULANCE_ID_MAX_LEN: int = int(os.getenv("AMBULANCE_ID_MAX_LEN", "64"))

# Valid latitude / longitude ranges.
LAT_MIN: float = -90.0
LAT_MAX: float = 90.0
LON_MIN: float = -180.0
LON_MAX: float = 180.0

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

# Graph file loaded at startup.  Override via env for different deployments.
GRAPH_PATH: str = os.getenv("GRAPH_PATH", "")  # empty → resolved relative to api/

# Logging level: DEBUG | INFO | WARNING | ERROR
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

# Application environment: development | testing | production
APP_ENV: str = os.getenv("APP_ENV", "development").lower()
