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

# Friendly labels for the control-panel category groups.
CATEGORY_LABELS = {
    "TOURNAMENT": "🏆 Tournament Keywords",
    "PLAYER_TRANSFER": "🔁 Player & Transfer Keywords",
    "ALGORITHM_HOOKS": "🎬 Algorithm Hook Keywords",
}


def _default_categories() -> dict[str, dict]:
    """Category context for the control panel, seeded from config defaults."""
    return {
        key: {"label": CATEGORY_LABELS.get(key, key), "keywords": list(keywords)}
        for key, keywords in config.KEYWORD_CATEGORIES.items()
    }


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", categories=_default_categories())


@app.route("/run", methods=["POST"])
def run():
    # Each category textarea posts newline-separated keywords as kw_<CATEGORY>.
    keywords: list[str] = []
    for key in config.KEYWORD_CATEGORIES:
        raw = request.form.get(f"kw_{key}", "")
        keywords.extend(line.strip() for line in raw.splitlines() if line.strip())

    df = AnalyzerEngine(keywords=keywords).run()
    return render_template("dashboard.html", standalone=False, **build_context(df))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
