"""Main conversion orchestrator: reads MARC, looks up LC, rewrites records."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from pymarc import Record

from dewey_to_lc.lookup.base import LookupResult, LookupService
from dewey_to_lc.marc_utils import (
    RecordIdentifiers,
    apply_lc_classification,
    extract_identifiers,
    has_dewey,
    has_lc_classification,
    read_marc_file,
    write_marc_file,
)
from dewey_to_lc.progress import ProgressTracker, RecordStatus

logger = logging.getLogger(__name__)


@dataclass
class ConversionStats:
    total: int = 0
    converted: int = 0
    no_match: int = 0
    skipped: int = 0
    errors: int = 0

    @property
    def processed(self) -> int:
        return self.converted + self.no_match + self.skipped + self.errors


def _cascade_lookup(
    identifiers: RecordIdentifiers,
    services: list[LookupService],
) -> LookupResult | None:
    """Try each lookup service in order and return the first successful result."""
    for service in services:
        try:
            result = service.lookup(identifiers)
            if result is not None:
                logger.debug(
                    "LC classification found via %s: %s",
                    service.name,
                    result.full_call_number,
                )
                return result
        except Exception as exc:
            logger.warning("Lookup service '%s' raised an exception: %s", service.name, exc)
    return None


_LOCAL_099_LABEL = "099 (not Dewey)"


def _safe_control_number(identifiers: RecordIdentifiers, index: int) -> str:
    """Return a stable identifier for a record, falling back to its index."""
    return identifiers.control_number or f"record-{index:06d}"


class Converter:
    """Orchestrates batch Dewey-to-LC conversion of MARC records."""

    def __init__(
        self,
        lookup_services: list[LookupService],
        tracker: ProgressTracker,
        output_dir: Path,
        resume: bool = True,
    ) -> None:
        """
        Args:
            lookup_services: Ordered list of lookup services (cascade order).
            tracker: Progress tracker for resume support.
            output_dir: Directory where converted .mrc files are written.
            resume: If True, skip records already marked as processed.
        """
        self._services = lookup_services
        self._tracker = tracker
        self._output_dir = output_dir
        self._resume = resume

    def convert_file(self, input_path: Path) -> ConversionStats:
        """Convert all Dewey-classified records in *input_path*.

        Writes a converted .mrc file to output_dir with the same filename.
        Returns stats for this file.
        """
        stats = ConversionStats()
        converted_records: list[Record] = []

        logger.info("Processing: %s", input_path)

        for index, record in enumerate(read_marc_file(input_path)):
            stats.total += 1
            ids = extract_identifiers(record)
            control_num = _safe_control_number(ids, index)

            # Register as pending (idempotent). Records with a non-Dewey 099
            # are listed with that call number so they can be reviewed.
            if ids.dewey:
                self._tracker.mark_pending(control_num, ids.title, ids.dewey, ids.dewey_field)
            elif ids.local_call_number:
                self._tracker.mark_pending(
                    control_num, ids.title, ids.local_call_number, _LOCAL_099_LABEL
                )
            else:
                self._tracker.mark_pending(control_num, ids.title, None)

            # Resume: skip already-processed records
            if self._resume and self._tracker.is_processed(control_num):
                logger.debug("Skipping already-processed record: %s", control_num)
                stats.skipped += 1
                continue

            # Records with no Dewey number are only looked up when they have a
            # non-Dewey 099 and an OCLC number, and then only by OCLC number.
            lookup_ids = ids
            if not has_dewey(record):
                if not (ids.local_call_number and ids.oclc_number):
                    logger.debug("No Dewey field on record %s — skipping", control_num)
                    self._tracker.mark_skipped(control_num)
                    stats.skipped += 1
                    continue
                lookup_ids = RecordIdentifiers(
                    oclc_number=ids.oclc_number,
                    title=ids.title,
                    control_number=ids.control_number,
                )

            # Skip records that already have an LC classification
            if has_lc_classification(record):
                logger.debug("Record %s already has 050 field — skipping", control_num)
                self._tracker.mark_skipped(control_num)
                stats.skipped += 1
                continue

            # Look up LC classification
            try:
                result = _cascade_lookup(lookup_ids, self._services)
            except Exception as exc:
                logger.error("Cascade lookup failed for %s: %s", control_num, exc)
                self._tracker.mark_error(control_num, str(exc))
                stats.errors += 1
                continue

            if result is None:
                logger.info("No LC match found for record: %s (%s)", control_num, ids.title)
                self._tracker.mark_no_match(control_num)
                stats.no_match += 1
                continue

            # Apply LC classification to the MARC record
            try:
                apply_lc_classification(record, result.lc_class, result.lc_item)
                converted_records.append(record)
                self._tracker.mark_converted(
                    control_num, result.lc_class, result.lc_item, result.source
                )
                stats.converted += 1
                logger.info(
                    "Converted %s: %s → %s (via %s)",
                    control_num,
                    ids.dewey or ids.local_call_number,
                    result.full_call_number,
                    result.source,
                )
            except Exception as exc:
                logger.error("Failed to apply LC classification to %s: %s", control_num, exc)
                self._tracker.mark_error(control_num, str(exc))
                stats.errors += 1

        # Write converted records to output file
        if converted_records:
            output_path = self._output_dir / input_path.name
            written = write_marc_file(converted_records, output_path)
            logger.info("Wrote %d converted records to %s", written, output_path)

        return stats

    def convert_files(self, input_paths: list[Path]) -> ConversionStats:
        """Convert multiple .mrc files. Returns combined stats."""
        total_stats = ConversionStats()
        for path in input_paths:
            file_stats = self.convert_file(path)
            total_stats.total += file_stats.total
            total_stats.converted += file_stats.converted
            total_stats.no_match += file_stats.no_match
            total_stats.skipped += file_stats.skipped
            total_stats.errors += file_stats.errors
        return total_stats
