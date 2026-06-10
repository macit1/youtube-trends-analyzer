
Goal

The current control panel has three hardcoded keyword categories (Tournament, Player & Transfer, Algorithm Hook) tightly coupled to the World Cup theme. This makes the tool unusable for any other topic. The goal is to rebuild the input layer into a generic, topic-driven interface where the user defines the subject, gets auto-generated keyword suggestions, and sets a time range filter — making the analyzer work for any YouTube topic, not just football.

⚙️ Implementation Steps

Replace three hardcoded keyword category textareas with a single Topic text input (free text, one line)

Auto-generate keyword suggestions from topic using string templates: {topic} shorts, {topic} viral, {topic} 2026, {topic} highlights, {topic} best moments, {topic} reaction

Render generated keywords as editable chips or a textarea so user can remove/add before launching

Add date range preset selector: Last 24 hours / Last 7 days / Last 30 days

Pass selected date range to analyzer_engine.py and filter out videos uploaded outside the range

Update config.py defaults to reflect new generic input model (remove WC-specific keyword sets)

✅ Completion Checklist

User can enter any topic and get relevant keyword suggestions instantly

Keywords are editable before launch

Date filter works — videos outside selected range do not appear in dashboard

No hardcoded football/WC references remain in control panel

📦 Scope
In:

Topic input replacing category textareas

Template-based keyword auto-generation

Date range preset filter (24h / 7d / 30d)

Backend filtering by upload date in analyzer engine

Out:

AI/LLM-based keyword generation (future issue)

Custom date range picker (presets only for now)

Dashboard UI changes

📝 Notes
Keyword generation is intentionally template-based (no API calls) for MVP speed. LLM-powered suggestions can be layered on later as a separate issue. Date filtering relies on upload date returned by yt-dlp — already extracted in AND-35.

---

# Feature Request: Search Mode Toggle (Shorts vs. General Videos)

## Goal
Add a toggle or dropdown to the control panel allowing the user to choose between searching only YouTube Shorts (short videos with duration limits and a `shorts` search suffix) or general YouTube videos (without duration limits or forced suffixes). This ensures the analyzer works seamlessly for standard long-form videos as well as short-form content.

## Proposed Changes
1. **Control Panel UI (`index.html`):**
   - Add a "Search Mode" selector (e.g., Radio buttons or a Dropdown) with options:
     - **Shorts Only** (Appends "shorts" suffix to search queries, applies `MAX_DURATION` limit of 180s/3m)
     - **All Videos** (Does not append "shorts" suffix, disables or increases the duration filter limit)
2. **Backend Engine (`analyzer_engine.py` & `config.py`):**
   - Pass the chosen mode from Flask to the `AnalyzerEngine`.
   - Conditionally apply the `SEARCH_SUFFIX` and duration thresholds based on the selected mode.
   - Gracefully handle cases where the video duration is not fetched or is `None`.