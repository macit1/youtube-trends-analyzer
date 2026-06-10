"""Flask driver: keyword control panel (page 1) + analytics leaderboard (page 2).

Routes
------
GET  /     -> render the keyword control panel seeded with config defaults
POST /run  -> capture edited keywords, run the engine live, render the dashboard
"""

from __future__ import annotations

from flask import Flask, render_template, request

from . import config
from .analyzer_engine import AnalyzerEngine
from .report_generator import build_context

app = Flask(__name__)


@app.route("/", methods=["GET"])
def index():
    return render_template(
        "index.html",
        keyword_templates=config.KEYWORD_TEMPLATES,
        search_modes=config.SEARCH_MODES,
        default_search_mode=config.DEFAULT_SEARCH_MODE,
        api_active=config.get_api_key() is not None,
        date_ranges=config.DATE_RANGES,
        default_date_range=config.DEFAULT_DATE_RANGE,
        default_min_likes=config.MIN_LIKES,
        default_min_views=config.MIN_VIEWS,
        default_per_keyword=config.get_results_per_keyword(),
    )


@app.route("/run", methods=["POST"])
def run():
    # The control panel posts the final (edited) keyword list as newline- or
    # comma-separated text in a single `keywords` field.
    raw = request.form.get("keywords", "")
    keywords = [
        part.strip()
        for line in raw.splitlines()
        for part in line.split(",")
        if part.strip()
    ]

    # Upload-date window: one of config.DATE_RANGES keys ("0"/"1"/"7"/"30").
    date_raw = request.form.get("date_range", "")
    try:
        date_range_days = int(date_raw) if date_raw else None
    except ValueError:
        date_range_days = None

    # Primary filters: minimum likes / views (control panel inputs, default to config).
    def _to_int(name: str) -> int | None:
        raw = request.form.get(name, "")
        try:
            return int(raw) if raw.strip() else None
        except ValueError:
            return None

    min_likes = _to_int("min_likes")
    min_views = _to_int("min_views")
    results_per_keyword = _to_int("per_keyword")

    # Search mode toggle: "shorts" or "all" (engine falls back to default on junk).
    search_mode = request.form.get("search_mode", config.DEFAULT_SEARCH_MODE)

    engine = AnalyzerEngine(
        keywords=keywords,
        date_range_days=date_range_days,
        min_likes=min_likes,
        min_views=min_views,
        results_per_keyword=results_per_keyword,
        search_mode=search_mode,
    )
    df = engine.run()
    return render_template(
        "dashboard.html",
        standalone=False,
        stats=engine.stats,
        provider=engine.provider,
        **build_context(df),
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
