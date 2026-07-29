# 🔍 TrendLens

**A general-purpose YouTube trend tracker & analyzer.** Enter any topic, and
TrendLens scrapes live videos, scores them by **Velocity** (views/hour) and
**Engagement** (likes/views), and presents a football-manager-style leaderboard
with a built-in word-frequency analysis of what's trending in the content.

Works for any subject — sports, music, gaming, cooking, anything.

---

## ✨ Features

- **Topic-driven search** — type a topic (e.g. `world cup 2026`, `lofi`,
  `minecraft`); it auto-generates editable keyword suggestions you can tune
  before launching.
- **Hybrid data source** — uses the official **YouTube Data API v3** when a key
  is configured (fast, exact stats, no IP-ban risk), and **automatically falls
  back to `yt-dlp` scraping** when there's no key, the quota is exhausted, or the
  API errors. The run never dies.
- **Search modes** — *Shorts Only* (≤ 3 min, biased queries) or *All Videos*
  (no duration limit).
- **Smart filters** — minimum likes/views, upload date-range presets
  (24h / 7d / 30d / all time), and scan depth per keyword.
- **Velocity & Engagement scoring** with traffic-light classification:
  🔴 Critical / 🟡 Potential / ⚪ Skip.
- **Trend word analysis** — a ranked bar panel of the most frequent words across
  the scraped titles & descriptions, plus a hashtag strip (stop-words and your
  own search terms are filtered out).
- **Filter funnel** — every run reports how many candidates were dropped and
  why, so empty results explain themselves.
- **Zero build step** — Tailwind via CDN, no Node, no static assets.

---

## 🚀 Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

(Requires Python 3.10+.)

### 2. (Optional but recommended) Add a YouTube Data API key

Without a key TrendLens still works via `yt-dlp` — just slower. With a key it's
seconds per run.

1. Go to [Google Cloud Console](https://console.cloud.google.com) → create a
   project.
2. **APIs & Services → Enable APIs → YouTube Data API v3 → Enable.**
3. **Credentials → Create credentials → API key**, then copy it.
4. Copy `.env.example` to `.env` and paste your key:

   ```
   YOUTUBE_API_KEY=your_key_here
   ```

   > `.env` is git-ignored — your key is never committed.
   > Tip: in Google Cloud, restrict the key to *YouTube Data API v3* only.

### 3. Run the web app

```bash
python -m shorts_analyzer.app
```

Open **http://localhost:5000**. A green **⚡ Fast API mode active** badge means
the key was picked up; otherwise you'll see the 🐢 yt-dlp fallback badge.

Enter a topic → **Generate** → tweak keywords/filters → **⚡ Launch TrendLens
Engine**.

### CLI mode (optional)

Render a static `dashboard.html` from the command line:

```bash
python -m shorts_analyzer.main
```

---

## 📊 How scoring works

For each video, hours-since-upload is floored at 0.1h to avoid divide-by-zero on
fresh uploads, then:

- **Velocity** = `Total Views / Hours Since Upload`
- **Engagement** = `(Total Likes / Total Views) × 100`

| Class | Rule | Meaning |
|-------|------|---------|
| 🔴 **Critical** | Velocity > 3000 **and** Engagement > 6% | Exploding — replicate the hook now |
| 🟡 **Potential** | Velocity > 1000 | Strong candidate |
| ⚪ **Skip** | below thresholds | Underperforming |

Thresholds live in `shorts_analyzer/config.py`.

---

## 🗂️ Project layout

```text
.
├── .env.example        # Environment variable template
├── .gitignore          # Git ignore file
├── Procfile            # Deployment configuration (gunicorn)
├── README.md           # Project documentation
├── requirements.txt    # Project dependencies
└── shorts_analyzer/    # Main application package
    ├── app.py              # Flask web server (control panel + dashboard)
    ├── main.py             # CLI entry point (renders static dashboard.html)
    ├── config.py           # Configuration, thresholds, and .env loader
    ├── analyzer_engine.py  # Data ingestion and metric scoring pipeline
    ├── youtube_api.py      # YouTube Data API v3 client
    ├── report_generator.py # Data processor and report compiler
    └── templates/
        ├── index.html      # Keyword control panel UI
        └── dashboard.html  # Analytical leaderboard UI
```

---

## ⚙️ Configuration highlights (`shorts_analyzer/config.py`)

- `USE_API` — master switch to force `yt-dlp` even with a key set.
- `MAX_WORKERS` — parallel metadata fetches (kept modest to stay IP-safe).
- `VELOCITY_CRITICAL` / `ENGAGEMENT_CRITICAL` / `VELOCITY_POTENTIAL` — scoring
  thresholds.
- `KEYWORD_TEMPLATES` — how a topic expands into search keywords.

---

## 📝 Notes

- The generated `dashboard.html` at the repo root is a build artifact and is
  git-ignored.
- `yt-dlp` mode is rate-limited with randomized delays between requests to avoid
  IP blocks.
