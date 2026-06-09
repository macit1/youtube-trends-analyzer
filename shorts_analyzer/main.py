"""Entry point: run discovery + scoring, then render the dashboard.

Usage:
    python -m shorts_analyzer.main
"""

from __future__ import annotations

from .analyzer_engine import AnalyzerEngine
from .report_generator import ReportGenerator


def main() -> None:
    try:
        df = AnalyzerEngine().run()
    except Exception as exc:  # noqa: BLE001 - top-level safety net
        print(f"[fatal] analysis failed: {exc}")
        return

    if df.empty:
        print("No videos found / everything filtered out. Dashboard not generated.")
        return

    try:
        ReportGenerator(df).generate()
    except Exception as exc:  # noqa: BLE001
        print(f"[fatal] report generation failed: {exc}")
        return

    print(f"Done — dashboard.html generated with {len(df)} videos.")


if __name__ == "__main__":
    main()
