"""YouTube Data API v3 client — the fast path used when an API key is present.

Per keyword: one ``search.list`` (100 quota units) returns up to 50 video IDs,
then one batched ``videos.list`` (1 unit) hydrates them with exact view/like
counts, duration and publish time. That's ~101 units/keyword vs. yt-dlp's dozens
of slow per-video page fetches — seconds instead of minutes, and no IP-ban risk.

Stdlib only (``urllib``) so no extra dependency. The engine treats this as a
best-effort accelerator: any failure here (missing key, quota exhausted, network)
raises and the engine falls back to yt-dlp, so the run never dies.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config

API_BASE = "https://www.googleapis.com/youtube/v3"

# ISO-8601 duration as returned by contentDetails.duration, e.g. "PT1M35S".
_ISO_DURATION = re.compile(
    r"P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
)


class QuotaExceeded(Exception):
    """Raised when the daily quota (or rate limit) is hit — triggers fallback."""


class APIError(Exception):
    """Any other API/transport failure — triggers fallback."""


class KeyUnusable(APIError):
    """Key-scoped failure (invalid key, API disabled in that project, key
    blocked/restricted) — the pool rotates past it instead of giving up."""


def _parse_duration(iso: str | None) -> int | None:
    """``"PT1M35S" -> 95``; ``None``/unparseable -> ``None``."""
    if not iso:
        return None
    m = _ISO_DURATION.fullmatch(iso)
    if not m:
        return None
    parts = {k: int(v) for k, v in m.groupdict(default="0").items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def _parse_published(iso: str | None) -> int | None:
    """RFC-3339 ``"2026-06-01T12:00:00Z"`` -> unix timestamp; ``None`` on failure."""
    if not iso:
        return None
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


class KeyPool:
    """Rotating pool of API keys shared across the whole process.

    When a key hits its daily quota it's marked exhausted and the next key
    takes over. Quotas reset at midnight Pacific, so the exhausted set is
    cleared when the Pacific calendar day changes. Thread-safe (the suggest
    endpoint and engine runs can overlap under gunicorn threads).
    """

    def __init__(self, keys: list[str]) -> None:
        self._keys = list(keys)
        self._exhausted: set[str] = set()
        self._lock = threading.Lock()
        self._day = self._pacific_day()

    @staticmethod
    def _pacific_day():
        # Fixed UTC-8 (PST) is fine here: worst case during PDT a key un-marks
        # an hour late, and a stray retry just gets re-marked exhausted.
        return datetime.now(timezone(timedelta(hours=-8))).date()

    def current(self) -> str | None:
        """First non-exhausted key, or ``None`` when all are spent today."""
        with self._lock:
            today = self._pacific_day()
            if today != self._day:  # daily quota reset -> everyone back in play
                self._day = today
                self._exhausted.clear()
            for key in self._keys:
                if key not in self._exhausted:
                    return key
            return None

    def mark_exhausted(self, key: str) -> None:
        with self._lock:
            self._exhausted.add(key)

    def __len__(self) -> int:
        return len(self._keys)


_pool: KeyPool | None = None
_pool_lock = threading.Lock()


def get_key_pool() -> KeyPool:
    """Process-wide pool built from config (rebuilt if the env keys change)."""
    global _pool
    keys = config.get_api_keys()
    with _pool_lock:
        if _pool is None or _pool._keys != keys:
            _pool = KeyPool(keys)
        return _pool


class YouTubeAPI:
    """Thin wrapper over the two endpoints the pipeline needs.

    Uses the shared :class:`KeyPool`: every request takes the current live key,
    and a quota error rotates to the next key transparently. QuotaExceeded only
    propagates once ALL configured keys are spent for the day.
    """

    def __init__(self, pool: KeyPool | None = None) -> None:
        self.pool = pool or get_key_pool()

    # ------------------------------------------------------------------ #
    def _get(self, endpoint: str, params: dict) -> dict:
        """GET an endpoint, rotating keys on quota or key-scoped errors."""
        last_error: Exception | None = None
        while True:
            key = self.pool.current()
            if key is None:
                detail = f" (last error: {last_error})" if last_error else ""
                raise QuotaExceeded(
                    f"all {len(self.pool)} API key(s) exhausted or unusable{detail}"
                )
            try:
                return self._get_with_key(endpoint, params, key)
            except (QuotaExceeded, KeyUnusable) as exc:
                last_error = exc
                idx = self.pool._keys.index(key) + 1
                kind = "quota exhausted" if isinstance(exc, QuotaExceeded) else "unusable"
                print(f"[api] key #{idx} {kind}; rotating to next key ({exc})")
                self.pool.mark_exhausted(key)

    def _get_with_key(self, endpoint: str, params: dict, api_key: str) -> dict:
        """GET an endpoint with one specific key; raise QuotaExceeded/APIError."""
        query = urllib.parse.urlencode({**params, "key": api_key})
        req = urllib.request.Request(
            f"{API_BASE}/{endpoint}?{query}", headers={"Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=config.SOCKET_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            low = body.lower()
            # Quota/rate-limit: Google answers 403 (quotaExceeded, rateLimitExceeded,
            # dailyLimitExceeded) OR 429 (RESOURCE_EXHAUSTED) depending on the path.
            if exc.code == 429 or (
                exc.code == 403
                and ("quota" in low or "ratelimit" in low or "dailylimit" in low)
            ):
                raise QuotaExceeded(body[:300]) from exc
            # Key-scoped failures: invalid key, YouTube Data API not enabled in
            # that Google Cloud project, or key blocked/restricted. The pool
            # should skip this key and try the rest, not abandon the API path.
            if exc.code in (400, 403) and (
                "api key" in low          # "API key not valid" / "API key expired"
                or "keyinvalid" in low
                or "accessnotconfigured" in low
                or "has not been used" in low
                or "is disabled" in low
                or "blocked" in low
                or "permission_denied" in low
            ):
                raise KeyUnusable(f"HTTP {exc.code}: {body[:300]}") from exc
            raise APIError(f"HTTP {exc.code}: {body[:300]}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise APIError(str(exc)) from exc

    # ------------------------------------------------------------------ #
    def search_ids(
        self,
        keyword: str,
        max_results: int,
        search_mode: str,
        published_after: str | None = None,
    ) -> list[str]:
        """Return up to ``max_results`` video IDs for ``keyword``.

        Shorts mode restricts to the API's ``short`` duration bucket (<4 min);
        the engine still trims to the precise MAX_DURATION ceiling afterwards.
        """
        params = {
            "part": "id",
            "q": keyword,
            "type": "video",
            "maxResults": min(max(max_results, 1), 50),
            "order": config.API_ORDER,
        }
        if search_mode == "shorts":
            params["videoDuration"] = "short"
        if published_after:
            params["publishedAfter"] = published_after
        data = self._get("search", params)
        return [
            item["id"]["videoId"]
            for item in data.get("items", [])
            if item.get("id", {}).get("videoId")
        ]

    def search_snippets(
        self, query: str, max_results: int, search_mode: str
    ) -> list[dict]:
        """Light search returning ``{title, description}`` per result in one call.

        Uses ``part=snippet`` so titles + (truncated) descriptions arrive without a
        follow-up ``videos.list`` — used for keyword suggestions. Same 100-unit cost
        as any ``search.list``.
        """
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": min(max(max_results, 1), 50),
            "order": config.API_ORDER,
        }
        if search_mode == "shorts":
            params["videoDuration"] = "short"
        data = self._get("search", params)
        out: list[dict] = []
        for item in data.get("items", []):
            sn = item.get("snippet", {})
            out.append(
                {"title": sn.get("title", ""), "description": sn.get("description", "")}
            )
        return out

    def fetch_stats(self, video_ids: list[str]) -> list[dict]:
        """Hydrate IDs into yt-dlp-shaped info dicts (batched 50/request)."""
        infos: list[dict] = []
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i : i + 50]
            if not batch:
                continue
            data = self._get(
                "videos",
                {"part": "snippet,statistics,contentDetails", "id": ",".join(batch)},
            )
            for item in data.get("items", []):
                infos.append(self._normalize(item))
        return infos

    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize(item: dict) -> dict:
        """Map an API video resource onto the same keys yt-dlp's info dict uses.

        Lets the engine's scoring path stay provider-agnostic. ``like_count`` is
        absent when the uploader hides likes -> left as ``None`` (filtered later).
        """
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        details = item.get("contentDetails", {})
        vid = item.get("id")

        def _int(value) -> int | None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        return {
            "id": vid,
            "title": snippet.get("title") or "Untitled",
            "channel": snippet.get("channelTitle") or "Unknown",
            "description": snippet.get("description") or "",
            "view_count": _int(stats.get("viewCount")) or 0,
            "like_count": _int(stats.get("likeCount")),  # None when hidden
            "duration": _parse_duration(details.get("duration")),
            "timestamp": _parse_published(snippet.get("publishedAt")),
            "webpage_url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
        }
