"""Transform the scored DataFrame into template context and rendered HTML.

A single source of truth (``templates/dashboard.html``) is shared by the Flask
app (``render_template``) and the standalone CLI, which renders the same Jinja
template to a static ``dashboard.html`` file.
"""

from __future__ import annotations

import os

import pandas as pd

from . import config

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")


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
