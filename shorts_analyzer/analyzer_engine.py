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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pandas as pd
from yt_dlp import YoutubeDL

from . import config
from .youtube_api import YouTubeAPI


def _flat_search_titles(topic: str, search_mode: str, pool: int = 25) -> list[str]:
    """Cheap flat yt-dlp search returning just result titles (no deep fetch)."""
    suffix = ""
    if search_mode == "shorts" and config.SEARCH_SUFFIX.lower() not in topic.lower():
        suffix = f" {config.SEARCH_SUFFIX}"
    with YoutubeDL(config.YDL_SEARCH_OPTS) as ydl:
        info = ydl.extract_info(f"ytsearch{pool}:{topic}{suffix}", download=False)
    return [
        e["title"]
        for e in (info or {}).get("entries") or []
        if e and e.get("title")
    ]


def gather_suggestion_text(
    topic: str, search_mode: str = "shorts"
) -> tuple[list[str], list[str]]:
    """Light search for keyword suggestions: return ``(titles, descriptions)``.

    Hybrid like the main engine — API when a key is set, yt-dlp fallback on any
    failure. Titles are the signal; descriptions (API only) feed hashtag mining.
    """
    key = config.get_api_key()
    if key:
        try:
            items = YouTubeAPI(key).search_snippets(topic, 25, search_mode)
            return (
                [i["title"] for i in items],
                [i["description"] for i in items],
            )
        except Exception as exc:  # noqa: BLE001 - fall back to scraping
            print(f"[suggest] API failed ({exc}); falling back to yt-dlp")
    try:
        return _flat_search_titles(topic, search_mode), []
    except Exception as exc:  # noqa: BLE001
        print(f"[suggest] yt-dlp search failed: {exc}")
        return [], []


class AnalyzerEngine:
    """Search YouTube (Shorts or all videos), score results, return a DataFrame."""

    def __init__(
        self,
        keywords: list[str] | None = None,
        date_range_days: int | None = None,
        min_likes: int | None = None,
        min_views: int | None = None,
        results_per_keyword: int | None = None,
        search_mode: str | None = None,
    ) -> None:
        # Flask passes runtime keywords from the control panel; fall back to
        # the config defaults (honoring TEST_MODE) when none are supplied.
        active = [k.strip() for k in (keywords or []) if k and k.strip()]
        self.keywords = active or config.get_active_keywords()
        # How many videos to keep per keyword (control panel input). Defaults to
        # the config value (honoring TEST_MODE); floored at 1.
        self.results_per_keyword = (
            config.get_results_per_keyword()
            if results_per_keyword is None
            else max(int(results_per_keyword), 1)
        )
        # Search mode: "shorts" biases queries with SEARCH_SUFFIX and enforces a
        # duration ceiling; "all" runs plain queries with no duration limit.
        self.search_mode = (
            search_mode if search_mode in config.SEARCH_MODES else config.DEFAULT_SEARCH_MODE
        )
        self.max_duration = config.MAX_DURATION if self.search_mode == "shorts" else None
        # Upload-date filter: keep only videos newer than this many days. None
        # (or non-positive) disables the filter entirely.
        self.date_range_days = date_range_days if (date_range_days and date_range_days > 0) else None
        # Primary inclusion gates: minimum likes / views. Default to config.
        self.min_likes = config.MIN_LIKES if min_likes is None else max(int(min_likes), 0)
        self.min_views = config.MIN_VIEWS if min_views is None else max(int(min_views), 0)
        # Filter-funnel counters from the last run() — lets the dashboard explain
        # WHY a run came back empty instead of silently showing nothing.
        self.stats: dict[str, int] = {}
        # Hybrid data source: use the official API when a key is configured,
        # otherwise scrape with yt-dlp. ``provider`` reflects what actually ran
        # (the API path can fall back mid-run on quota/error).
        key = config.get_api_key()
        self.api = YouTubeAPI(key) if key else None
        self.provider = "yt-dlp"

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #
    def _search(self, keyword: str) -> list[str]:
        """Return watch URLs of candidate videos for ``keyword``.

        Shorts mode: scans a large flat pool (cheap, one request) with a
        Shorts-biasing suffix, keeping only entries within MAX_DURATION so the
        expensive deep extraction runs on real Shorts only. All-videos mode:
        plain query, no suffix, no duration gate.
        """
        if self.search_mode == "shorts":
            suffix = "" if config.SEARCH_SUFFIX.lower() in keyword.lower() else f" {config.SEARCH_SUFFIX}"
            # Pool large enough to survive duration attrition and still fill the
            # requested per-keyword count (~4 candidates scanned per Short kept).
            pool = max(config.SEARCH_POOL, self.results_per_keyword * 4)
        else:
            suffix = ""
            pool = self.results_per_keyword
        query = f"ytsearch{pool}:{keyword}{suffix}"
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
            # Shorts mode: pre-filter by duration at the flat stage (skip
            # None/long videos). All mode keeps everything, duration unknown or not.
            duration = entry.get("duration")
            if self.max_duration is not None and (
                duration is None or duration > self.max_duration
            ):
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
    def _upload_datetime(info: dict) -> datetime | None:
        """Best-effort UTC upload datetime from yt-dlp metadata; ``None`` if unknown."""
        ts = info.get("timestamp")
        if ts:
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (OSError, ValueError, OverflowError):
                pass

        raw_date = info.get("upload_date")  # YYYYMMDD
        if raw_date:
            try:
                return datetime.strptime(raw_date, "%Y%m%d").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return None

    @classmethod
    def _compute_age_hours(cls, info: dict) -> float:
        """Hours since upload, floored at 0.1 to avoid zero-division on fresh uploads."""
        upload_dt = cls._upload_datetime(info)
        if upload_dt is None:
            return 1.0  # unknown age -> conservative 1h to keep velocity finite

        age_hours = (datetime.now(timezone.utc) - upload_dt).total_seconds() / 3600.0
        return max(age_hours, 0.1)  # 0.1h ceiling guards brand-new uploads

    def _within_date_range(self, info: dict) -> bool:
        """True if the video passes the active upload-date filter.

        No filter -> always True. Unknown upload date -> kept (can't prove it's
        outside the range; dropping good data is worse than an occasional stale row).
        """
        if self.date_range_days is None:
            return True
        upload_dt = self._upload_datetime(info)
        if upload_dt is None:
            return True
        age_days = (datetime.now(timezone.utc) - upload_dt).total_seconds() / 86400.0
        return age_days <= self.date_range_days

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
    def _collect_candidates(self) -> list[tuple[str, str]]:
        """Search every keyword; return de-duplicated ``(keyword, url)`` pairs.

        De-duplicating by video id BEFORE deep extraction avoids re-fetching the
        same video surfaced under multiple keywords.
        """
        tasks: list[tuple[str, str]] = []
        seen_ids: set[str] = set()
        for keyword in self.keywords:
            print(f"[search] {keyword!r}")
            video_urls = self._search(keyword)
            print(f"         {len(video_urls)} candidates")
            for url in video_urls:
                video_id = url.rsplit("v=", 1)[-1]
                if video_id in seen_ids:
                    continue
                seen_ids.add(video_id)
                tasks.append((keyword, url))
        return tasks

    def _process(self, keyword: str, url: str) -> tuple[str, dict | None]:
        """Deep-fetch one candidate (yt-dlp path) and score it.

        Returns ``(funnel_reason, row)`` where ``row`` is ``None`` whenever the
        video was filtered out; the reason feeds the run's drop statistics.
        """
        # Human-like jitter staggers parallel workers (anti-ban pacing).
        time.sleep(random.uniform(config.MIN_DELAY, config.MAX_DELAY))

        info = self._fetch_metadata(url)
        if info is None:
            return "fetch_failed", None
        return self._score_info(keyword, info, url)

    def _score_info(
        self, keyword: str, info: dict, url: str
    ) -> tuple[str, dict | None]:
        """Apply the filter funnel to a hydrated info dict and score survivors.

        Provider-agnostic: ``info`` may come from yt-dlp deep extraction or from
        the YouTube Data API (normalized to the same keys).
        """
        duration = info.get("duration")
        if self.max_duration is not None and (
            duration is None or duration > self.max_duration
        ):
            return "over_duration", None  # shorts mode: not a Short (or unknown length)

        if not self._within_date_range(info):
            return "outside_date_range", None

        views = info.get("view_count") or 0
        likes = info.get("like_count") or 0
        if views <= 0:
            return "zero_views", None  # hidden/zero views -> metrics meaningless

        # Primary gates: only keep videos clearing the likes & views thresholds.
        if likes < self.min_likes or views < self.min_views:
            return "below_thresholds", None

        age_hours = self._compute_age_hours(info)
        velocity = views / age_hours
        engagement = (likes / views) * 100.0
        classification = self._classify(velocity, engagement)
        upload_dt = self._upload_datetime(info)

        return "kept", {
            "title": info.get("title") or "Untitled",
            "channel": info.get("channel") or info.get("uploader") or "Unknown",
            "description": info.get("description") or "",
            "views": int(views),
            "likes": int(likes),
            "duration": int(duration) if duration else 0,
            "age_hours": round(age_hours, 2),
            "upload_date": upload_dt.strftime("%Y-%m-%d") if upload_dt else "—",
            "velocity": round(velocity, 2),
            "engagement": round(engagement, 2),
            "classification": classification,
            "keyword": keyword,
            "url": info.get("webpage_url") or url,
        }

    @staticmethod
    def _empty_stats() -> dict[str, int]:
        return {
            "candidates": 0,
            "fetch_failed": 0,
            "over_duration": 0,
            "outside_date_range": 0,
            "zero_views": 0,
            "below_thresholds": 0,
            "kept": 0,
        }

    def _collect_api_pairs(self) -> list[tuple[str, dict]]:
        """API path: search + hydrate every keyword into ``(keyword, info)`` pairs.

        Date filtering is pushed server-side via ``publishedAfter`` so we never
        even fetch stats for out-of-window videos. De-dupes IDs across keywords.
        """
        published_after = None
        if self.date_range_days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.date_range_days)
            published_after = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        pairs: list[tuple[str, dict]] = []
        seen_ids: set[str] = set()
        for keyword in self.keywords:
            print(f"[api-search] {keyword!r}")
            ids = self.api.search_ids(
                keyword, self.results_per_keyword, self.search_mode, published_after
            )
            new_ids = [vid for vid in ids if vid not in seen_ids]
            seen_ids.update(new_ids)
            infos = self.api.fetch_stats(new_ids)
            print(f"            {len(infos)} videos")
            for info in infos:
                pairs.append((keyword, info))
        return pairs

    def run(self) -> pd.DataFrame:
        """Execute the full pipeline and return a Velocity-sorted DataFrame."""
        mode = "TEST" if config.TEST_MODE else "FULL"
        window = f"{self.date_range_days}d" if self.date_range_days else "any time"
        source = "API" if self.api else "yt-dlp"
        print(
            f"[engine] {mode} mode | source: {source} | search: {self.search_mode} | "
            f"{len(self.keywords)} keywords | "
            f"{self.results_per_keyword} videos/keyword | window: {window} | "
            f"min likes: {self.min_likes} | min views: {self.min_views} | "
            f"{config.MAX_WORKERS} workers"
        )

        stats = self._empty_stats()
        rows: list[dict] = []

        # --- Fast path: YouTube Data API (falls back to yt-dlp on any failure) ---
        if self.api is not None:
            try:
                pairs = self._collect_api_pairs()
                stats["candidates"] = len(pairs)
                for keyword, info in pairs:
                    reason, row = self._score_info(
                        keyword, info, info.get("webpage_url", "")
                    )
                    stats[reason] += 1
                    if row is not None:
                        rows.append(row)
                self.provider = "YouTube Data API"
            except Exception as exc:  # noqa: BLE001 - any API failure -> scrape
                print(f"[engine] API unavailable ({exc}); falling back to yt-dlp")
                stats = self._empty_stats()
                rows = []
                self.api = None  # disable for the rest of this run

        # --- Fallback path: yt-dlp scraping (also the default when no key) ---
        if self.api is None:
            self.provider = "yt-dlp"
            tasks = self._collect_candidates()
            stats["candidates"] = len(tasks)
            if tasks:
                # Parallel deep extraction: biggest time sink is per-video
                # metadata, so fan it out across a modest worker pool.
                with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
                    for reason, row in pool.map(lambda t: self._process(*t), tasks):
                        stats[reason] += 1
                        if row is not None:
                            rows.append(row)

        self.stats = stats
        print(f"[engine] provider: {self.provider} | funnel: {stats}")

        if not rows:
            print("[engine] no videos collected.")
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = df.sort_values("velocity", ascending=False).reset_index(drop=True)

        critical = int((df["classification"] == "CRITICAL").sum())
        print(f"[engine] collected {len(df)} videos | {critical} critical trends")
        return df
