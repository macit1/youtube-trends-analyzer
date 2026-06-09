"""Discovery + deep metadata extraction + metric scoring.

The :class:`AnalyzerEngine` drives the whole ingestion pipeline using ``yt-dlp``
for both search (``ytsearchN:``) and per-video metadata, then computes Velocity
and Engagement and returns a sorted :class:`pandas.DataFrame`.

Exception safety is aggressive: any single failing video or keyword is logged
and skipped so the run always completes.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone

import pandas as pd
from yt_dlp import YoutubeDL

from . import config


class AnalyzerEngine:
    """Search YouTube Shorts, score them, and serialize to a DataFrame."""

    def __init__(self, keywords: list[str] | None = None) -> None:
        # Flask passes runtime keywords from the control panel; fall back to
        # the config defaults (honoring TEST_MODE) when none are supplied.
        active = [k.strip() for k in (keywords or []) if k and k.strip()]
        self.keywords = active or config.get_active_keywords()
        self.results_per_keyword = config.get_results_per_keyword()
        self.max_duration = config.MAX_DURATION

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #
    def _search(self, keyword: str) -> list[str]:
        """Return watch URLs of likely Shorts for ``keyword``.

        Scans a large flat pool (cheap, one request) with a Shorts-biasing
        suffix, then keeps only entries whose duration is <= MAX_DURATION so the
        expensive deep extraction runs on real Shorts only.
        """
        suffix = "" if config.SEARCH_SUFFIX.lower() in keyword.lower() else f" {config.SEARCH_SUFFIX}"
        query = f"ytsearch{config.SEARCH_POOL}:{keyword}{suffix}"
        try:
            with YoutubeDL(config.YDL_SEARCH_OPTS) as ydl:
                info = ydl.extract_info(query, download=False)
        except Exception as exc:  # noqa: BLE001 - keep the run alive
            print(f"  [search-error] '{keyword}': {exc}")
            return []

        if not info:
            return []

        urls: list[str] = []
        for entry in info.get("entries") or []:
            if not entry:
                continue
            # Pre-filter by duration at the flat stage (skip None/long videos).
            duration = entry.get("duration")
            if duration is None or duration > self.max_duration:
                continue

            url = entry.get("url") or entry.get("webpage_url") or entry.get("id")
            if not url:
                continue
            # extract_flat returns bare IDs for youtube; normalise to a URL.
            if not str(url).startswith("http"):
                url = f"https://www.youtube.com/watch?v={url}"
            urls.append(url)
            if len(urls) >= self.results_per_keyword:
                break
        return urls

    # ------------------------------------------------------------------ #
    # Deep metadata
    # ------------------------------------------------------------------ #
    def _fetch_metadata(self, video_url: str) -> dict | None:
        """Deep-extract a single video's metadata; ``None`` on any failure."""
        try:
            with YoutubeDL(config.YDL_META_OPTS) as ydl:
                info = ydl.extract_info(video_url, download=False)
        except Exception as exc:  # noqa: BLE001
            print(f"  [meta-error] {video_url}: {exc}")
            return None
        return info or None

    @staticmethod
    def _compute_age_hours(info: dict) -> float:
        """Hours since upload, floored at 0.1 to avoid zero-division on fresh uploads."""
        now = datetime.now(timezone.utc)
        upload_dt: datetime | None = None

        ts = info.get("timestamp")
        if ts:
            try:
                upload_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            except (OSError, ValueError, OverflowError):
                upload_dt = None

        if upload_dt is None:
            raw_date = info.get("upload_date")  # YYYYMMDD
            if raw_date:
                try:
                    upload_dt = datetime.strptime(raw_date, "%Y%m%d").replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    upload_dt = None

        if upload_dt is None:
            return 1.0  # unknown age -> conservative 1h to keep velocity finite

        age_hours = (now - upload_dt).total_seconds() / 3600.0
        return max(age_hours, 0.1)  # 0.1h ceiling guards brand-new uploads

    @staticmethod
    def _classify(velocity: float, engagement: float) -> str:
        """Map metrics to CRITICAL / POTENTIAL / SKIP per spec thresholds."""
        if velocity > config.VELOCITY_CRITICAL and engagement > config.ENGAGEMENT_CRITICAL:
            return "CRITICAL"
        if velocity > config.VELOCITY_POTENTIAL:
            return "POTENTIAL"
        return "SKIP"

    # ------------------------------------------------------------------ #
    # Orchestration
    # ------------------------------------------------------------------ #
    def run(self) -> pd.DataFrame:
        """Execute the full pipeline and return a Velocity-sorted DataFrame."""
        rows: list[dict] = []
        seen_ids: set[str] = set()  # de-duplicate videos across keywords
        mode = "TEST" if config.TEST_MODE else "FULL"
        print(
            f"[engine] {mode} mode | {len(self.keywords)} keywords | "
            f"{self.results_per_keyword} videos/keyword"
        )

        for keyword in self.keywords:
            print(f"[search] {keyword!r}")
            video_urls = self._search(keyword)
            print(f"         {len(video_urls)} candidates")

            for url in video_urls:
                # Human-like pacing between network requests (anti-ban).
                time.sleep(random.uniform(config.MIN_DELAY, config.MAX_DELAY))

                info = self._fetch_metadata(url)
                if info is None:
                    continue

                # Skip videos already collected under another keyword.
                video_id = info.get("id") or info.get("webpage_url") or url
                if video_id in seen_ids:
                    continue
                seen_ids.add(video_id)

                duration = info.get("duration")
                if duration is None or duration > self.max_duration:
                    continue  # not a Short

                views = info.get("view_count") or 0
                likes = info.get("like_count") or 0
                if views <= 0:
                    continue  # hidden/zero views -> metrics meaningless

                age_hours = self._compute_age_hours(info)
                velocity = views / age_hours
                engagement = (likes / views) * 100.0
                classification = self._classify(velocity, engagement)

                rows.append(
                    {
                        "title": info.get("title") or "Untitled",
                        "channel": info.get("channel")
                        or info.get("uploader")
                        or "Unknown",
                        "views": int(views),
                        "likes": int(likes),
                        "age_hours": round(age_hours, 2),
                        "velocity": round(velocity, 2),
                        "engagement": round(engagement, 2),
                        "classification": classification,
                        "keyword": keyword,
                        "url": info.get("webpage_url") or url,
                    }
                )

        if not rows:
            print("[engine] no videos collected.")
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = df.sort_values("velocity", ascending=False).reset_index(drop=True)

        critical = int((df["classification"] == "CRITICAL").sum())
        print(f"[engine] collected {len(df)} videos | {critical} critical trends")
        return df
