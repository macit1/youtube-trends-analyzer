# Project Specification: YT-Shorts Trend Tracker & HTML Dashboard (ShortsCup AI)

## 1. Executive Summary
The goal of this project is to build a lightweight, high-performance analytical data pipeline and dynamic web interface that tracks, scores, and filters viral YouTube Shorts related to the 2026 World Cup. The system features an interactive 2-page workflow: a configuration control panel to manage keywords and trigger ingestion at runtime, and a dynamic, football-manager-style analytical dashboard leaderboard (`dashboard.html`) for instant trend evaluation.

---

## 2. Technical Stack & Architecture

### Allowed Libraries & Frameworks
* **Language:** Python 3.10+
* **Web Server Layer:** `Flask` (Lightweight Python micro-framework used to handle HTTP routing between pages, capture POST payloads, and execute the runtime scraping loop).
* **Discovery:** `Youtube-python` (Specifically using `VideosSearch` to rapidly pull raw search candidates without consuming official YouTube Data API v3 quotas).
* **Deep Metadata Extraction:** `yt-dlp` (Specifically utilizing `YoutubeDL` with configurations `{'quiet': True, 'no_warnings': True, 'extract_flat': False}` to pull real-time views, precise like counts, channel names, and upload dates).
* **Data Processing Layer:** `pandas` (For vector calculations, sorting matrices, removing duplicate records across keywords, and handling mathematical fallbacks).
* **Frontend Delivery:** Native HTML5 mixed with **Tailwind CSS via CDN** injected inside document headers. No local node packages or static CSS style assets are allowed.

---

## 3. Simplified Analytics & Color Coding Rules

The Python processing script calculates hours passed since a video was published (handling brand-new uploads safely by providing a minimum ceiling of 0.1 hours to prevent zero-division calculation crashes) and derives two core matrices:

1. **Velocity ($V$):** $$V = \frac{\text{Total Views}}{\text{Hours Since Upload}}$$
2. **Engagement ($E$):** $$E = \left( \frac{\text{Total Likes}}{\text{Total Views}} \right) \times 100$$

### Visual Classification & Threshold Rules (Tailwind Colors):
* **🔴 CRITICAL TREND (`#ef4444` / `bg-red-500`):** Velocity $> 3000$ views/hour AND Engagement $> 6\%$. (Action: Exploding exponentially. Replicate visual hook instantly).
* **🟡 POTENTIAL (`#eab308` / `bg-yellow-500`):** Velocity $> 1000$ views/hour. (Action: Strong content tier candidate for backlog batch processing).
* **⚪ SKIP (`#64748b` / `bg-slate-500`):** Anything falling below the designated thresholds. (Action: Underperforming asset. Filter out or mute).

---

## 4. Multi-Page UI/UX Design System

### Global Theme System
* **Deep Dark Mode Look & Feel:** Base Background: Slate Graphite (`#0f172a`), Component Card/Table Canvas: Dark Charcoal (`#1e293b`), Primary Text Elements: Crisp Ice White (`#f8fafc`), Supporting Analytics Muted Text: Muted Gray (`#94a3b8`).

### Page 1: Keyword Control Panel (`templates/index.html`)
* **Dynamic Form Configurator:** Text areas grouped by modular strategic categories allowing users to alter or add active lookup terms at runtime.
* **Execution Trigger:** A massive, central, pulsing action button labeled **"⚡ Launch ShortsCup AI Engine"**.
* **Loading Interceptor Overlay:** Freezes the browser interface on submission, throwing a live frontend processing spinner with text: *"Scraping & Analyzing Live YouTube Shorts... Please Wait."* before redirecting once the engine sequence is completed.

### Page 2: Analytics Leaderboard (`templates/dashboard.html`)
* **Top Metric Scoreboards:** 3 prominent numerical layout grids showing: *Total Shorts Scraped*, *Critical Trends Discovered*, and *Top Dominant Keyword Right Now*.
* **Main Standings Matrix Table:** Responsive grid display sorting results strictly from highest calculated Velocity downwards. Features a **"⬅ Back to Control Panel"** escape link to return and modify search keywords.
* **Row Customization:** Explicitly displays exact calculated Velocity, Engagement percentages, an absolute Tailwind color tag pill, and a direct click CTA element titled **"Watch Short ↗"** launching a target window into the explicit Shorts URL string.

---

## 5. Directory & Module Blueprint
```text
shorts_analyzer/
├── app.py                # Main Flask driver managing request routes, form mutations, and engine execution
├── config.py             # Default fallbacks, mathematical limit settings, and initial keyword sets
├── analyzer_engine.py    # Search query loops, yt-dlp deep metadata retrieval, and pandas mutations
├── report_generator.py   # Renders the DataFrames into structural Tailwind context layouts
├── templates/
│   ├── index.html        # Interactive control deck for keyword payload customization
│   └── dashboard.html    # Football-manager tactical grid leaderboard UI
└── requirements.txt      # Project constraints (flask, youtube-search-python, yt-dlp, pandas)