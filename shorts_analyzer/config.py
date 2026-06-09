"""Global configuration: keywords, runtime limits, thresholds and visual mappings.

Everything tunable lives here so the engine and report generator stay declarative.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Keyword categories (from CLAUDE.md spec)
# --------------------------------------------------------------------------- #
TOURNAMENT_KEYWORDS = [
    "World Cup 2026 qualifiers",
    "World Cup 2026 goals",
    "Road to 2026 World Cup",
]

PLAYER_TRANSFER_KEYWORDS = [
    "Football transfer news shorts",
    "Here we go football shorts",
    "Arda Guler Turkey skills",
    "Mbappe France 2026",
]

ALGORITHM_HOOKS = [
    "Football shorts edit",
    "Football rare moments",
    "Prime football edits",
]

KEYWORD_CATEGORIES: dict[str, list[str]] = {
    "TOURNAMENT": TOURNAMENT_KEYWORDS,
    "PLAYER_TRANSFER": PLAYER_TRANSFER_KEYWORDS,
    "ALGORITHM_HOOKS": ALGORITHM_HOOKS,
}

# --------------------------------------------------------------------------- #
# Runtime settings
# --------------------------------------------------------------------------- #
RESULTS_PER_KEYWORD = 15           # shorts kept per keyword in full mode
MAX_DURATION = 60                  # Shorts guarantee: keep duration <= 60s
MIN_DELAY, MAX_DELAY = 1.0, 2.0    # random.uniform delay between requests (anti-ban)
SOCKET_TIMEOUT = 15               # yt-dlp network timeout (seconds)

# Plain keyword searches surface long compilation videos, not Shorts. We append
# a suffix to bias toward Shorts and scan a larger flat pool, pre-filtering by
# duration BEFORE the expensive deep extraction so only real Shorts are fetched.
SEARCH_SUFFIX = "shorts"
SEARCH_POOL = 40                   # flat candidates scanned per keyword

# --------------------------------------------------------------------------- #
# IP-safe test mode
# --------------------------------------------------------------------------- #
TEST_MODE = True                   # light scan to avoid IP blocks while validating
TEST_MODE_KEYWORDS_PER_CATEGORY = 2
TEST_MODE_RESULTS_PER_KEYWORD = 10

# --------------------------------------------------------------------------- #
# Classification thresholds
# --------------------------------------------------------------------------- #
VELOCITY_CRITICAL = 3000           # views/hour
ENGAGEMENT_CRITICAL = 6            # percent
VELOCITY_POTENTIAL = 1000          # views/hour

# Class -> visual mapping (emoji, hex, tailwind bg class, label)
CLASSIFICATION: dict[str, dict[str, str]] = {
    "CRITICAL": {
        "label": "CRITICAL TREND",
        "emoji": "🔴",
        "hex": "#ef4444",
        "pill": "bg-red-500",
    },
    "POTENTIAL": {
        "label": "POTENTIAL",
        "emoji": "🟡",
        "hex": "#eab308",
        "pill": "bg-yellow-500",
    },
    "SKIP": {
        "label": "SKIP",
        "emoji": "⚪",
        "hex": "#64748b",
        "pill": "bg-slate-500",
    },
}

# --------------------------------------------------------------------------- #
# yt-dlp option sets
# --------------------------------------------------------------------------- #
YDL_SEARCH_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,          # fast: list entries without per-video extraction
    "skip_download": True,
    "socket_timeout": SOCKET_TIMEOUT,
    "ignoreerrors": True,
}

YDL_META_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,         # deep extraction for precise counts/timestamps
    "skip_download": True,
    "socket_timeout": SOCKET_TIMEOUT,
    "ignoreerrors": True,
}

# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
OUTPUT_HTML = "dashboard.html"


def get_active_keywords() -> list[str]:
    """Return the flat keyword list to scan, honoring TEST_MODE.

    In test mode only the first ``TEST_MODE_KEYWORDS_PER_CATEGORY`` keywords of
    each category are used to keep the network footprint small.
    """
    keywords: list[str] = []
    for category_keywords in KEYWORD_CATEGORIES.values():
        if TEST_MODE:
            keywords.extend(category_keywords[:TEST_MODE_KEYWORDS_PER_CATEGORY])
        else:
            keywords.extend(category_keywords)
    return keywords


def get_results_per_keyword() -> int:
    """Active per-keyword result count depending on TEST_MODE."""
    return TEST_MODE_RESULTS_PER_KEYWORD if TEST_MODE else RESULTS_PER_KEYWORD
