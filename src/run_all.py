"""Run the full analysis pipeline in the correct order.

Usage (from the project root):

    python src/run_all.py

Each step is a separate script so it can also be run on its own. This runner
stops on the first failure and prints which stage failed, because a downstream
step on stale inputs is worse than no output at all.

The last step (src/generate_business_report.py) validates the KPIs against the
database, evaluates the recommendation rules and writes the executive report.
If any of those critical checks fails it exits non-zero and no report is
published.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

STEPS = [
    ("clean raw data and run 24 quality checks", "src/clean_data.py"),
    ("rebuild the SQLite database", "src/build_db.py"),
    ("run the 16 SQL analysis queries", "src/run_queries.py"),
    ("bootstrap, tests and within-listing metrics", "src/analyze.py"),
    ("render the 10 report figures", "src/make_figures.py"),
    ("generate the executive report and recommendations", "src/generate_business_report.py"),
]


def main() -> int:
    print(f"Project root: {PROJECT_ROOT}\n")
    started = time.perf_counter()

    for i, (label, script) in enumerate(STEPS, start=1):
        path = PROJECT_ROOT / script
        if not path.exists():
            print(f"[{i}/{len(STEPS)}] MISSING {script}")
            return 1

        print(f"[{i}/{len(STEPS)}] {label}")
        step_start = time.perf_counter()
        result = subprocess.run(
            [sys.executable, str(path)],
            cwd=PROJECT_ROOT,
            check=False,
        )
        elapsed = time.perf_counter() - step_start

        if result.returncode != 0:
            print(f"    FAILED after {elapsed:.1f}s — stopping.")
            return result.returncode

        print(f"    ok in {elapsed:.1f}s\n")

    total = time.perf_counter() - started
    print(f"Pipeline complete in {total:.1f}s.")
    print("Outputs: data/processed/, airbnb_queretaro.db, reports/")
    print("         reports/executive_report.md, reports/decision_recommendations.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
