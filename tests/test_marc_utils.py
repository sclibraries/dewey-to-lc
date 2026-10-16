"""Tests for MARC utility functions."""

from __future__ import annotations

import pytest
from pymarc import Record, Field, Subfield

from dewey_to_lc.marc_utils import (
    RecordIdentifiers,
    apply_lc_classification,
    extract_identifiers,
    find_dewey,
    has_dewey,
    is_dewey_number,
    has_lc_classification,
)


def _make_record(
    control_num: str = "TEST001",
    dewey: str | None = "005.133",
    lccn: str | None = None,
    isbn: str | None = None,
    oclc: str | None = None,
    title: str = "Test Title",
) -> Record:
    record = Record()
    record.add_field(Field(tag="001", data=control_num))
    if lccn:
        record.add_field(Field(tag="010", indicators=[" ", " "], subfields=[Subfield("a", lccn)]))
    if isbn:
        record.add_field(Field(tag="020", indicators=[" ", " "], subfields=[Subfield("a", isbn)]))
    if oclc:
        record.add_field(Field(tag="035", indicators=[" ", " "], subfields=[Subfield("a", f"(OCoLC){oclc}")]))
    record.add_field(Field(tag="245", indicators=["1", "0"], subfields=[Subfield("a", title)]))
    if dewey:
        record.add_field(Field(tag="082", indicators=["0", "4"], subfields=[Subfield("a", dewey), Subfield("2", "23")]))
    return record


class TestExtractIdentifiers:
    def test_extracts_control_number(self):
        record = _make_record(control_num="CTL123")
        ids = extract_identifiers(record)
        assert ids.control_number == "CTL123"

    def test_extracts_dewey(self):
        record = _make_record(dewey="005.133")
        ids = extract_identifiers(record)
        assert ids.dewey == "005.133"

    def test_extracts_lccn(self):
        record = _make_record(lccn="  2005012345")
        ids = extract_identifiers(record)
        assert ids.lccn == "2005012345"

    def test_extracts_isbn_strips_qualifiers(self):
        record = _make_record(isbn="9780134444321 (hardcover)")
        ids = extract_identifiers(record)
        assert "9780134444321" in ids.isbn

    def test_extracts_oclc_number_ocolc_prefix(self):
        record = _make_record(oclc="12345678")
        ids = extract_identifiers(record)
        assert ids.oclc_number == "12345678"

    def test_extracts_oclc_ocn_prefix(self):
        record = _make_record()
        record.add_field(Field(tag="035", indicators=[" ", " "], subfields=[Subfield("a", "ocn987654321")]))
        ids = extract_identifiers(record)
        assert ids.oclc_number == "987654321"

    def test_no_identifiers_returns_empty(self):
        record = _make_record(lccn=None, isbn=None, oclc=None)
        ids = extract_identifiers(record)
        assert ids.lccn is None
        assert ids.isbn == []
        assert ids.oclc_number is None

    def test_extracts_title(self):
        record = _make_record(title="Python Programming Essentials /")
        ids = extract_identifiers(record)
        assert "Python Programming Essentials" in ids.title


class TestHasDewey:
    def test_record_with_082(self):
        record = _make_record(dewey="005.133")
        assert has_dewey(record) is True

    def test_record_without_082(self):
        record = _make_record(dewey=None)
        assert has_dewey(record) is False


def _add(record: Record, tag: str, value: str, indicators: list[str] | None = None) -> Record:
    record.add_field(Field(tag=tag, indicators=indicators or [" ", " "], subfields=[Subfield("a", value)]))
    return record


class TestFindDewey:
    def test_082(self):
        assert find_dewey(_make_record(dewey="923.244")) == ("082", "923.244")

    def test_092_with_blank_indicators(self):
        record = _add(_make_record(dewey=None), "092", "944.033")
        assert find_dewey(record) == ("092", "944.033")

    def test_092_with_non_blank_indicator_is_ignored(self):
        record = _add(_make_record(dewey=None), "092", "944.033", ["0", "4"])
        assert find_dewey(record) is None

    def test_099_dewey(self):
        record = _add(_make_record(dewey=None), "099", "944.033 C671 Zcou", [" ", "1"])
        assert find_dewey(record) == ("099", "944.033 C671 Zcou")

    def test_099_not_dewey(self):
        record = _add(_make_record(dewey=None), "099", "FIC SMITH")
        assert find_dewey(record) is None
        assert not has_dewey(record)

    def test_082_wins_over_092_and_099(self):
        record = _add(_add(_make_record(dewey="923.244"), "092", "944"), "099", "944.033")
        assert find_dewey(record) == ("082", "923.244")

    def test_092_wins_over_099(self):
        record = _add(_add(_make_record(dewey=None), "092", "944"), "099", "944.033")
        assert find_dewey(record) == ("092", "944")


class TestIsDeweyNumber:
    @pytest.mark.parametrize("value", ["944.033 C671 Zcou", "923.244", "813/.54", "500", "944.033C671"])
    def test_dewey(self, value):
        assert is_dewey_number(value)

    @pytest.mark.parametrize("value", ["FIC SMITH", "Folio 944", "B C684", "1984", "PS3552 .E796", ""])
    def test_not_dewey(self, value):
        assert not is_dewey_number(value)


class TestExtractIdentifiersCallNumbers:
    def test_records_dewey_field(self):
        ids = extract_identifiers(_add(_make_record(dewey=None), "092", "944.033"))
        assert ids.dewey == "944.033"
        assert ids.dewey_field == "092"
        assert ids.local_call_number is None

    def test_records_non_dewey_099(self):
        ids = extract_identifiers(_add(_make_record(dewey=None), "099", "FIC SMITH"))
        assert ids.dewey is None
        assert ids.local_call_number == "FIC SMITH"


class TestHasLcClassification:
    def test_record_with_050(self):
        record = _make_record()
        record.add_field(Field(tag="050", indicators=[" ", "4"], subfields=[Subfield("a", "QA76.73.P98")]))
        assert has_lc_classification(record) is True

    def test_record_without_050(self):
        record = _make_record()
        assert has_lc_classification(record) is False


class TestApplyLcClassification:
    def test_keeps_dewey_fields_and_adds_050(self):
        record = _make_record(dewey="005.133")
        record.add_field(Field(tag="092", indicators=[" ", " "], subfields=[Subfield("a", "005.133")]))
        record.add_field(Field(tag="099", indicators=[" ", " "], subfields=[Subfield("a", "005.133 B37")]))

        apply_lc_classification(record, "QA76.73.P98", "B37 2022")

        assert record["082"]["a"] == "005.133"
        assert record["092"]["a"] == "005.133"
        assert record["099"]["a"] == "005.133 B37"
        assert has_lc_classification(record)

    def test_050_subfields_correct(self):
        record = _make_record(dewey="813.54")
        apply_lc_classification(record, "PS3552.E796", "A23 2022")

        f050 = record["050"]
        assert f050["a"] == "PS3552.E796"
        assert f050["b"] == "A23 2022"

    def test_050_without_item_number(self):
        record = _make_record(dewey="509")
        apply_lc_classification(record, "Q125")

        f050 = record["050"]
        assert f050["a"] == "Q125"
        assert f050.get("b") is None

    def test_indicator_2_defaults_to_4(self):
        record = _make_record(dewey="005.133")
        apply_lc_classification(record, "QA76.73.P98")
        assert record["050"].indicator2 == "4"

    def test_removes_existing_050_before_adding(self):
        record = _make_record(dewey="005.133")
        record.add_field(Field(tag="050", indicators=[" ", "0"], subfields=[Subfield("a", "OLD")]))
        apply_lc_classification(record, "QA76.73.P98")
        fields = record.get_fields("050")
        assert len(fields) == 1
        assert fields[0]["a"] == "QA76.73.P98"
