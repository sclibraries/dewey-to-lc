"""MARC record reading and field manipulation utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from pymarc import MARCReader, Record, Field, Subfield


@dataclass
class RecordIdentifiers:
    """Identifiers extracted from a MARC record for external lookup."""

    lccn: str | None = None
    isbn: list[str] = field(default_factory=list)
    oclc_number: str | None = None
    dewey: str | None = None
    title: str | None = None
    control_number: str | None = None


def read_marc_file(path: Path) -> Iterator[Record]:
    """Yield MARC records from a binary .mrc file."""
    with open(path, "rb") as fh:
        reader = MARCReader(fh, to_unicode=True, force_utf8=True)
        for record in reader:
            yield record


def extract_identifiers(record: Record) -> RecordIdentifiers:
    """Extract lookup identifiers and Dewey classification from a MARC record."""
    ids = RecordIdentifiers()

    # Control number (001)
    f001 = record.get_fields("001")
    if f001:
        ids.control_number = f001[0].value().strip()

    # LCCN (010 $a)
    f010_list = record.get_fields("010")
    if f010_list:
        lccn_val = f010_list[0].get("a")
        if lccn_val:
            ids.lccn = lccn_val.strip()

    # ISBN (020 $a) — may have qualifiers like "(hardcover)", strip them
    for f020 in record.get_fields("020"):
        raw = f020.get("a")
        if raw:
            isbn = re.split(r"[\s(]", raw.strip())[0].replace("-", "")
            if isbn:
                ids.isbn.append(isbn)

    # OCLC number (035 $a) — format: (OCoLC)12345678 or ocn012345678 etc.
    for f035 in record.get_fields("035"):
        raw = f035.get("a")
        if raw:
            oclc_match = re.search(r"(?:\(OCoLC\)|OCoLC|ocn|ocm)(\d+)", raw.strip(), re.IGNORECASE)
            if oclc_match:
                ids.oclc_number = oclc_match.group(1)
                break

    # Dewey Decimal Classification (082 $a)
    f082_list = record.get_fields("082")
    if f082_list:
        dewey_val = f082_list[0].get("a")
        if dewey_val:
            ids.dewey = dewey_val.strip()

    # Title (245 $a + $b for display in report)
    f245_list = record.get_fields("245")
    if f245_list:
        f245 = f245_list[0]
        parts = [f245.get("a") or "", f245.get("b") or ""]
        ids.title = " ".join(p.strip().rstrip("/: ") for p in parts if p).strip()

    return ids


def has_dewey(record: Record) -> bool:
    """Return True if the record has a Dewey classification field (082)."""
    return bool(record.get_fields("082"))


def has_lc_classification(record: Record) -> bool:
    """Return True if the record already has an LC classification field (050)."""
    return bool(record.get_fields("050"))


def apply_lc_classification(
    record: Record,
    lc_class: str,
    lc_item: str | None = None,
    source_indicator: str = "4",
) -> Record:
    """Replace 082 (Dewey) with 050 (LC Classification) on a MARC record.

    Args:
        record: The MARC record to modify (modified in place).
        lc_class: LC classification number for 050 $a (e.g. "PS3552.E796").
        lc_item: LC item number for 050 $b (e.g. "A23 2022"). Optional.
        source_indicator: Indicator 2 — '0' = LC-assigned, '4' = other agency.

    Returns:
        The modified record.
    """
    # Remove existing 082 fields
    for f in record.get_fields("082"):
        record.remove_field(f)

    # Remove any pre-existing 050 fields to avoid duplicates
    for f in record.get_fields("050"):
        record.remove_field(f)

    # Build 050 subfields
    subfields: list[Subfield] = [Subfield(code="a", value=lc_class)]
    if lc_item:
        subfields.append(Subfield(code="b", value=lc_item))

    new_050 = Field(
        tag="050",
        indicators=[" ", source_indicator],
        subfields=subfields,
    )
    record.add_ordered_field(new_050)
    return record


def write_marc_file(records: list[Record], path: Path) -> int:
    """Write MARC records to a binary .mrc file. Returns number of records written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "wb") as fh:
        for record in records:
            fh.write(record.as_marc())
            count += 1
    return count
