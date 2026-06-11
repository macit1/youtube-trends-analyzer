"""Global configuration: keywords, runtime limits, thresholds and visual mappings.

Everything tunable lives here so the engine and report generator stay declarative.
"""

from __future__ import annotations

import os

# --------------------------------------------------------------------------- #
# YouTube Data API v3 (optional fast path)
# --------------------------------------------------------------------------- #
# When YOUTUBE_API_KEY is set the engine uses the official API (seconds, no IP
# risk, exact stats); otherwise it falls back to yt-dlp scraping. The key is
# read from the environment or a git-ignored .env file at the project root.
USE_API = True                     # master switch — set False to force yt-dlp
API_ORDER = "viewCount"            # search.list ordering ("viewCount"/"relevance"/"date")


def _load_dotenv() -> None:
    """Populate os.environ from a project-root ``.env`` (KEY=VALUE lines).

    Zero-dependency and non-destructive: never overrides a value already set in
    the real environment. Silently no-ops when the file is absent.
    """
    root = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(root, ".env")
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


_load_dotenv()


def get_api_keys() -> list[str]:
    """All configured YouTube Data API keys, in rotation order.

    Sources (combined, de-duplicated, order preserved):
    - YOUTUBE_API_KEY, then YOUTUBE_API_KEY_2 .. YOUTUBE_API_KEY_9
    - YOUTUBE_API_KEYS: comma-separated list (alternative single-variable form)

    When one key's daily quota is exhausted the client rotates to the next
    (see youtube_api.KeyPool). Empty list -> engine runs on yt-dlp only.
    """
    if not USE_API:
        return []
    raw: list[str] = [os.environ.get("YOUTUBE_API_KEY", "")]
    raw += [os.environ.get(f"YOUTUBE_API_KEY_{i}", "") for i in range(2, 10)]
    raw += os.environ.get("YOUTUBE_API_KEYS", "").split(",")
    keys: list[str] = []
    for item in raw:
        item = item.strip()
        if item and item not in keys:
            keys.append(item)
    return keys


def get_api_key() -> str | None:
    """First configured API key, or ``None`` when unset/disabled."""
    keys = get_api_keys()
    return keys[0] if keys else None


# --------------------------------------------------------------------------- #
# Topic-driven keyword generation
# --------------------------------------------------------------------------- #
# The control panel takes a single free-text topic and expands it into concrete
# search keywords via these templates ({topic} is substituted). Generic by
# design — works for any subject, not just football/World Cup.
KEYWORD_TEMPLATES: list[str] = [
    "{topic} shorts",
    "{topic} viral",
    "{topic} 2026",
    "{topic} highlights",
    "{topic} best moments",
    "{topic} reaction",
]

# Fallback topic used by the CLI / engine default when no topic is supplied.
DEFAULT_TOPIC = "trending"


def generate_keywords(topic: str) -> list[str]:
    """Expand a free-text ``topic`` into search keywords via KEYWORD_TEMPLATES.

    Empty/whitespace topics yield an empty list (nothing to search).
    """
    topic = (topic or "").strip()
    if not topic:
        return []
    return [tpl.format(topic=topic) for tpl in KEYWORD_TEMPLATES]


# --------------------------------------------------------------------------- #
# Search mode (control panel toggle)
# --------------------------------------------------------------------------- #
# "shorts": appends SEARCH_SUFFIX to queries and enforces MAX_DURATION.
# "all": plain queries, no duration ceiling (long-form videos included).
SEARCH_MODES: dict[str, str] = {
    "shorts": "Shorts Only",
    "all": "All Videos",
}
DEFAULT_SEARCH_MODE = "shorts"

# --------------------------------------------------------------------------- #
# Upload-date range presets (control panel selector -> days)
# --------------------------------------------------------------------------- #
# Ordered value -> label map. Value is the number of days back to keep videos.
# "0" disables the upload-date filter entirely (likes threshold is the only gate).
DATE_RANGES: dict[str, str] = {
    "0": "All time",
    "1": "Last 24 hours",
    "7": "Last 7 days",
    "30": "Last 30 days",
}
DEFAULT_DATE_RANGE = "0"

# Primary filters: keep only videos with at least this many likes / views. These
# are the quality gates the user tunes from the control panel — everything passing
# them is shown (velocity/engagement only affect ranking & color, not inclusion).
# MIN_VIEWS defaults to 0 (no view restriction) so likes is the gate out of the box.
MIN_LIKES = 1000
MIN_VIEWS = 0

# --------------------------------------------------------------------------- #
# Runtime settings
# --------------------------------------------------------------------------- #
RESULTS_PER_KEYWORD = 15           # videos kept per keyword in full mode
MAX_DURATION = 180                 # Shorts-mode ceiling: YouTube raised the max
                                   # Shorts length to 3 min (180s) in 2024.
                                   # Ignored entirely in "all" search mode.
MIN_DELAY, MAX_DELAY = 0.5, 1.0    # random.uniform delay between requests (anti-ban)
MAX_WORKERS = 4                    # parallel yt-dlp metadata fetches (keep modest
                                   # to stay IP-safe; each worker still jitters)
SOCKET_TIMEOUT = 15               # yt-dlp network timeout (seconds)

# Shorts mode only: plain keyword searches surface long compilation videos, so we
# append a suffix to bias toward Shorts and scan a larger flat pool, pre-filtering
# by duration BEFORE the expensive deep extraction. "all" mode skips both.
SEARCH_SUFFIX = "shorts"
SEARCH_POOL = 40                   # flat candidates scanned per keyword (shorts mode)

# --------------------------------------------------------------------------- #
# IP-safe test mode
# --------------------------------------------------------------------------- #
TEST_MODE = False                  # light scan to avoid IP blocks while validating
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
    """Default keyword list (CLI / engine fallback) from ``DEFAULT_TOPIC``.

    In test mode the list is trimmed to keep the network footprint small.
    """
    keywords = generate_keywords(DEFAULT_TOPIC)
    if TEST_MODE:
        return keywords[:TEST_MODE_KEYWORDS_PER_CATEGORY]
    return keywords


def get_results_per_keyword() -> int:
    """Active per-keyword result count depending on TEST_MODE."""
    return TEST_MODE_RESULTS_PER_KEYWORD if TEST_MODE else RESULTS_PER_KEYWORD
