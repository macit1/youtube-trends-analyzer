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
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

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


class YouTubeAPI:
    """Thin wrapper over the two endpoints the pipeline needs."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    # ------------------------------------------------------------------ #
    def _get(self, endpoint: str, params: dict) -> dict:
        """GET an endpoint; raise QuotaExceeded/APIError on failure."""
        query = urllib.parse.urlencode({**params, "key": self.api_key})
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
            # 403 covers both quotaExceeded and rateLimitExceeded reasons.
            if exc.code == 403 and ("quota" in body.lower() or "rateLimit" in body):
                raise QuotaExceeded(body[:300]) from exc
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
