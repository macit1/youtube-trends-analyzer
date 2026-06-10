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

# Only true connectors are blocked at phrase boundaries — content words like
# "all", "best", "new" are allowed inside phrases ("all goals", "best moments").
_PHRASE_STOP = frozenset(
    "the a an and or of to in on at for with from by as is are was were vs feat ft".split()
)

# Generic media boilerplate also blocked inside phrases so "official music" /
# "music video" don't masquerade as trends (kept out of phrases, not words).
_MEDIA_NOISE = frozenset(
    "official music video audio lyrics lyric remix version full hd mv song songs "
    "episode part trailer teaser".split()
)


def analyze_words(df: pd.DataFrame, top_n: int = 10, top_tags: int = 8) -> dict:
    """Trend panel data: repeated 2-word phrases + clean single words + hashtags.

    Single-word frequency over descriptions is noisy (lyric fragments, spam,
    boilerplate), so we mine **titles** — the cleanest signal. Genuinely repeated
    2-word phrases ("all goals", "transfer news") lead the list because they read
    like trends; remaining slots are filled with the top single words that aren't
    already part of a shown phrase. Hashtags (deliberate tags) come from titles +
    descriptions and are shown separately. ``pct`` drives the bar widths.

    Filtered out: stopwords, the searched topic's own words, pure numbers (except
    4-digit years), and <3-char noise.
    """
    if df.empty:
        return {"words": [], "hashtags": [], "mode": "words"}

    # Exclude the searched keywords' own tokens (e.g. "world", "cup", "2026").
    topic_tokens = {
        t
        for kw in df["keyword"].unique()
        for t in re.findall(r"\w+", str(kw).lower())
    }

    def keep_word(tok: str) -> bool:
        if len(tok) < 3:
            return False
        if tok.isdigit() and len(tok) != 4:  # keep years, drop other bare numbers
            return False
        return tok not in _STOPWORDS and tok not in topic_tokens

    def keep_in_phrase(tok: str) -> bool:
        if len(tok) < 3 or tok.isdigit():
            return False
        return (
            tok not in _PHRASE_STOP
            and tok not in _MEDIA_NOISE
            and tok not in topic_tokens
        )

    phrases: Counter[str] = Counter()  # 2-word phrases from titles
    words: Counter[str] = Counter()    # single words from titles
    hashtags: Counter[str] = Counter()

    for _, r in df.iterrows():
        # Hashtags: deliberate tags, mine from title + description.
        for raw in (str(r.get("title", "")), str(r.get("description", ""))):
            for tag in re.findall(r"#\w{2,}", raw.lower()):
                hashtags[tag] += 1

        # Phrases/words: titles only (descriptions are too spammy to be useful).
        toks = re.findall(r"\w+", str(r.get("title", "")).lower())
        for tok in toks:
            if keep_word(tok):
                words[tok] += 1
        # Bigrams from consecutive title tokens where both survive the filter.
        for a, b in zip(toks, toks[1:]):
            if keep_in_phrase(a) and keep_in_phrase(b):
                phrases[f"{a} {b}"] += 1

    # Lead with genuinely repeated phrases (count >= 2); record their tokens so we
    # don't then list those same words again as redundant single entries.
    chosen: list[tuple[str, int]] = []
    covered: set[str] = set()
    for phrase, count in phrases.most_common():
        if count < 2 or len(chosen) >= top_n:
            break
        chosen.append((phrase, count))
        covered.update(phrase.split())
    mode = "phrases" if len(chosen) >= 2 else "words"

    # Fill remaining slots with the top single words not already in a phrase.
    for word, count in words.most_common():
        if len(chosen) >= top_n:
            break
        if word in covered:
            continue
        chosen.append((word, count))

    chosen.sort(key=lambda wc: wc[1], reverse=True)
    items = chosen[:top_n]
    peak = items[0][1] if items else 1
    return {
        "mode": mode,
        "words": [
            {"word": w, "count": c, "pct": max(round(c / peak * 100), 5)}
            for w, c in items
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
