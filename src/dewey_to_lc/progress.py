"""SQLite-based progress tracker for resumable batch processing."""

from __future__ import annotations

import sqlite3
from enum import Enum
from pathlib import Path


class RecordStatus(str, Enum):
    PENDING = "pending"
    CONVERTED = "converted"
    NO_MATCH = "no_match"
    ERROR = "error"
    SKIPPED = "skipped"


class ProgressTracker:
    """Tracks per-record conversion state in a local SQLite database."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                control_number TEXT PRIMARY KEY,
                title           TEXT,
                old_dewey       TEXT,
                dewey_field     TEXT,
                new_lc_class    TEXT,
                new_lc_item     TEXT,
                lookup_source   TEXT,
                status          TEXT NOT NULL DEFAULT 'pending',
                error_message   TEXT,
                processed_at    TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS run_metadata (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        # Databases created before dewey_field existed need the column added.
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(records)")}
        if "dewey_field" not in columns:
            self._conn.execute("ALTER TABLE records ADD COLUMN dewey_field TEXT")
        self._conn.commit()

    def is_processed(self, control_number: str) -> bool:
        """Return True if the record has already been processed (any non-pending status)."""
        row = self._conn.execute(
            "SELECT status FROM records WHERE control_number = ?", (control_number,)
        ).fetchone()
        return row is not None and row["status"] != RecordStatus.PENDING

    def mark_pending(
        self,
        control_number: str,
        title: str | None,
        old_dewey: str | None,
        dewey_field: str | None = None,
    ) -> None:
        """Register a record as pending (idempotent — won't overwrite a completed record)."""
        self._conn.execute(
            """INSERT OR IGNORE INTO records (control_number, title, old_dewey, dewey_field, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (control_number, title, old_dewey, dewey_field),
        )
        self._conn.commit()

    def mark_converted(
        self,
        control_number: str,
        new_lc_class: str,
        new_lc_item: str | None,
        lookup_source: str,
    ) -> None:
        self._conn.execute(
            """UPDATE records SET status=?, new_lc_class=?, new_lc_item=?,
               lookup_source=?, processed_at=datetime('now')
               WHERE control_number=?""",
            (RecordStatus.CONVERTED, new_lc_class, new_lc_item, lookup_source, control_number),
        )
        self._conn.commit()

    def mark_no_match(self, control_number: str) -> None:
        self._conn.execute(
            "UPDATE records SET status=?, processed_at=datetime('now') WHERE control_number=?",
            (RecordStatus.NO_MATCH, control_number),
        )
        self._conn.commit()

    def mark_error(self, control_number: str, message: str) -> None:
        self._conn.execute(
            """UPDATE records SET status=?, error_message=?, processed_at=datetime('now')
               WHERE control_number=?""",
            (RecordStatus.ERROR, message, control_number),
        )
        self._conn.commit()

    def mark_skipped(self, control_number: str) -> None:
        self._conn.execute(
            "UPDATE records SET status=?, processed_at=datetime('now') WHERE control_number=?",
            (RecordStatus.SKIPPED, control_number),
        )
        self._conn.commit()

    def summary(self) -> dict[str, int]:
        """Return counts by status."""
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM records GROUP BY status"
        ).fetchall()
        return {row["status"]: row["cnt"] for row in rows}

    def get_all_records(self) -> list[sqlite3.Row]:
        """Return all record rows for report generation."""
        return self._conn.execute(
            "SELECT * FROM records ORDER BY control_number"
        ).fetchall()

    def set_metadata(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO run_metadata (key, value) VALUES (?, ?)", (key, value)
        )
        self._conn.commit()

    def get_metadata(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM run_metadata WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def close(self) -> None:
        self._conn.close()
