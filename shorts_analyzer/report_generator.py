"""Transform the scored DataFrame into template context and rendered HTML.

A single source of truth (``templates/dashboard.html``) is shared by the Flask
app (``render_template``) and the standalone CLI, which renders the same Jinja
template to a static ``dashboard.html`` file.
"""

from __future__ import annotations

import os
import re
from collections import Counter

import pandas as pd

from . import config

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

# Words filtered out of the trend analysis: English + a few Turkish function
# words, plus YouTube-description boilerplate (subscribe/follow/links/legal).
# Lowercase. The searched topic's own words are excluded dynamically too.
_STOPWORDS = frozenset(
    """
    the a an and or but if then else of to in on at for with from by as is are was
    were be been being this that these those it its it's i you he she we they them
    his her our your their my me us him so not no yes do does did done have has had
    will would can could should may might must just out up down off over under more
    most some any all each every other into about above below than too very only own
    now here there when what who why how where which while also back after before
    again once ever never today still even much many lot make made want need see
    new get got go going one two three new vs feat ft via about com www http https
    official lets let feat ft remix audio lyrics version full episode part
    subscribe channel video videos watch like comment share follow link links bio
    instagram twitter tiktok facebook youtube shorts short copyright credit credits
    music song please thanks thank business inquiries inquiry email contact dm
    ve bir bu da de ile için çok daha en ki mi mı ne o şu gibi ama veya her
    """.split()
)

# Token = a #hashtag or a bare word (unicode-aware: keeps Turkish letters too).
_TOKEN_RE = re.compile(r"#\w+|\w+", re.UNICODE)


def analyze_words(df: pd.DataFrame, top_n: int = 12, top_tags: int = 8) -> dict:
    """Most frequent meaningful words + hashtags across titles & descriptions.

    Gives the dashboard its "analysis tool" view. Filters stopwords, the searched
    topic's own words (so associated terms surface, not just what you searched),
    pure numbers (except 4-digit years), and 1-2 char noise. ``pct`` is each
    word's count relative to the top word — drives the bar widths in the UI.
    """
    if df.empty:
        return {"words": [], "hashtags": []}

    # Exclude the searched keywords' own tokens (e.g. "world", "cup", "2026").
    topic_tokens = {
        t
        for kw in df["keyword"].unique()
        for t in re.findall(r"\w+", str(kw).lower())
    }

    blob = " ".join(
        f"{r.get('title', '')} {r.get('description', '')}" for _, r in df.iterrows()
    ).lower()

    words: Counter[str] = Counter()
    hashtags: Counter[str] = Counter()
    for tok in _TOKEN_RE.findall(blob):
        if tok.startswith("#"):
            if len(tok) > 2:
                hashtags[tok] += 1
            continue
        if len(tok) < 3:
            continue
        if tok.isdigit() and len(tok) != 4:  # keep years, drop other bare numbers
            continue
        if tok in _STOPWORDS or tok in topic_tokens:
            continue
        words[tok] += 1

    top = words.most_common(top_n)
    peak = top[0][1] if top else 1
    return {
        "words": [
            {"word": w, "count": c, "pct": max(round(c / peak * 100), 5)}
            for w, c in top
        ],
        "hashtags": [{"tag": t, "count": c} for t, c in hashtags.most_common(top_tags)],
    }


def _fmt_duration(seconds: int) -> str:
    """``95 -> "1:35"``, ``3700 -> "1:01:40"``; 0/unknown -> em dash."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "—"
    minutes, secs = divmod(seconds, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _top_keyword(df: pd.DataFrame) -> str:
    """Keyword driving the highest aggregate velocity right now."""
    if df.empty:
        return "—"
    agg = df.groupby("keyword")["velocity"].sum()
    return str(agg.idxmax())


def build_context(df: pd.DataFrame) -> dict:
    """Build the template context (metric cards + leaderboard rows) from a DataFrame."""
    total = len(df)
    critical = int((df["classification"] == "CRITICAL").sum()) if total else 0

    rows: list[dict] = []
    if total:
        for rank, (_, r) in enumerate(df.iterrows(), start=1):
            cls = config.CLASSIFICATION.get(
                r["classification"], config.CLASSIFICATION["SKIP"]
            )
            title = str(r["title"])
            if len(title) > 70:
                title = title[:67] + "…"
            rows.append(
                {
                    "rank": rank,
                    "title": title,
                    "channel": str(r["channel"]),
                    "velocity": float(r["velocity"]),
                    "engagement": float(r["engagement"]),
                    "views": int(r["views"]),
                    "likes": int(r["likes"]),
                    "duration": _fmt_duration(r.get("duration", 0)),
                    "upload_date": str(r.get("upload_date", "—")),
                    "url": str(r["url"]),
                    "pill": cls["pill"],
                    "emoji": cls["emoji"],
                    "label": cls["label"],
                }
            )

    return {
        "total_scraped": total,
        "critical_count": critical,
        "top_keyword": _top_keyword(df),
        "analysis": analyze_words(df),
        "rows": rows,
    }


class ReportGenerator:
    """Render an analysis DataFrame to a static ``dashboard.html`` (CLI path)."""

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df

    def generate(self, output_path: str | None = None) -> str:
        """Render the shared Jinja template to disk and return the output path."""
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        output_path = output_path or config.OUTPUT_HTML
        env = Environment(
            loader=FileSystemLoader(TEMPLATES_DIR),
            autoescape=select_autoescape(["html"]),
        )
        template = env.get_template("dashboard.html")
        html = template.render(standalone=True, **build_context(self.df))

        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"[report] wrote {output_path}")
        return output_path
