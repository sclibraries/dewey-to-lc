"""MARC record reading and field manipulation utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from pymarc import MARCReader, Record, Field, Subfield

# A Dewey number starts with three digits, optionally followed by a decimal
# part (e.g. "944.033 C671", "813/.54", "923.244"). Anything else in 099 is
# treated as a local, non-Dewey call number.
_DEWEY_RE = re.compile(r"^\d{3}(?:\.\d+)?(?![\d.])")


@dataclass
class RecordIdentifiers:
    """Identifiers extracted from a MARC record for external lookup."""

    lccn: str | None = None
    isbn: list[str] = field(default_factory=list)
    oclc_number: str | None = None
    dewey: str | None = None
    dewey_field: str | None = None  # tag the Dewey number came from: 082, 092 or 099
    local_call_number: str | None = None  # 099 $a when it is not a Dewey number
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

    # Dewey Decimal Classification (082, then 092, then 099 $a)
    found = find_dewey(record)
    if found:
        ids.dewey_field, ids.dewey = found
    else:
        ids.local_call_number = _first_subfield(record, "099", "a")

    # Title (245 $a + $b for display in report)
    f245_list = record.get_fields("245")
    if f245_list:
        f245 = f245_list[0]
        parts = [f245.get("a") or "", f245.get("b") or ""]
        ids.title = " ".join(p.strip().rstrip("/: ") for p in parts if p).strip()

    return ids


def _first_subfield(record: Record, tag: str, code: str) -> str | None:
    """Return the first non-empty subfield value for a tag, stripped."""
    for f in record.get_fields(tag):
        value = f.get(code)
        if value and value.strip():
            return value.strip()
    return None


def is_dewey_number(value: str) -> bool:
    """Return True if a call number string looks like a Dewey number."""
    return bool(_DEWEY_RE.match(value.strip()))


def find_dewey(record: Record) -> tuple[str, str] | None:
    """Find the record's Dewey number. Returns (tag, value) or None.

    Checked in order:
      - 082 $a (any indicators)
      - 092 $a with both indicators blank (local Dewey)
      - 099 $a, only when the value looks like a Dewey number
    """
    value = _first_subfield(record, "082", "a")
    if value:
        return "082", value

    for f in record.get_fields("092"):
        value = f.get("a")
        if f.indicator1 == " " and f.indicator2 == " " and value and value.strip():
            return "092", value.strip()

    value = _first_subfield(record, "099", "a")
    if value and is_dewey_number(value):
        return "099", value

    return None


def has_dewey(record: Record) -> bool:
    """Return True if the record has a Dewey number in 082, 092 or 099."""
    return find_dewey(record) is not None


def has_lc_classification(record: Record) -> bool:
    """Return True if the record already has an LC classification field (050)."""
    return bool(record.get_fields("050"))


def apply_lc_classification(
    record: Record,
    lc_class: str,
    lc_item: str | None = None,
    source_indicator: str = "4",
) -> Record:
    """Add an 050 (LC Classification) to a MARC record.

    Dewey fields (082, 092, 099) are left in place.

    Args:
        record: The MARC record to modify (modified in place).
        lc_class: LC classification number for 050 $a (e.g. "PS3552.E796").
        lc_item: LC item number for 050 $b (e.g. "A23 2022"). Optional.
        source_indicator: Indicator 2 — '0' = LC-assigned, '4' = other agency.

    Returns:
        The modified record.
    """
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
