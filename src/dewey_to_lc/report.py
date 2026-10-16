"""CSV report generation from the progress tracker database."""

from __future__ import annotations

import csv
from pathlib import Path

from dewey_to_lc.progress import ProgressTracker


_REPORT_COLUMNS = [
    "control_number",
    "title",
    "old_dewey",
    "dewey_field",
    "new_lc_class",
    "new_lc_item",
    "new_lc_full",
    "lookup_source",
    "status",
    "error_message",
    "processed_at",
]


def write_csv_report(tracker: ProgressTracker, output_path: Path) -> int:
    """Write a CSV conversion report. Returns the number of rows written."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = tracker.get_all_records()

    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_REPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            d = dict(row)
            # Add computed full call number column
            parts = [d.get("new_lc_class") or "", d.get("new_lc_item") or ""]
            d["new_lc_full"] = " ".join(p for p in parts if p).strip()
            writer.writerow(d)

    return len(rows)


def print_summary(tracker: ProgressTracker) -> None:
    """Print a summary table to stdout."""
    summary = tracker.summary()
    total = sum(summary.values())

    rows = [
        ("Converted", summary.get("converted", 0)),
        ("No match (needs review)", summary.get("no_match", 0)),
        ("Skipped (no Dewey / already LC)", summary.get("skipped", 0)),
        ("Errors", summary.get("error", 0)),
        ("Pending (unprocessed)", summary.get("pending", 0)),
    ]

    width = 36
    print(f"\n{'─' * width}")
    print(f"{'Conversion Summary':^{width}}")
    print(f"{'─' * width}")
    for label, count in rows:
        print(f"  {label:<30} {count:>4}")
    print(f"{'─' * width}")
    print(f"  {'Total records':<30} {total:>4}")
    print(f"{'─' * width}\n")
