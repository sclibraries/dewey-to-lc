"""Tests for the converter orchestrator."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pymarc import MARCWriter, Record, Field, Subfield

from dewey_to_lc.converter import Converter, _cascade_lookup
from dewey_to_lc.lookup.base import LookupResult, LookupService
from dewey_to_lc.marc_utils import RecordIdentifiers, has_dewey, has_lc_classification
from dewey_to_lc.progress import ProgressTracker


def _make_record(control_num: str, dewey: str | None = "005.133", oclc: str | None = None) -> Record:
    record = Record()
    record.add_field(Field(tag="001", data=control_num))
    record.add_field(Field(tag="245", indicators=["1", "0"], subfields=[Subfield("a", "Test Title")]))
    if dewey:
        record.add_field(Field(tag="082", indicators=["0", "4"], subfields=[Subfield("a", dewey)]))
    if oclc:
        record.add_field(Field(tag="035", indicators=[" ", " "], subfields=[Subfield("a", f"(OCoLC){oclc}")]))
    return record


def _write_mrc(records: list[Record], path: Path) -> None:
    with open(path, "wb") as fh:
        writer = MARCWriter(fh)
        for r in records:
            writer.write(r)
        writer.close()


class MockLookupService(LookupService):
    def __init__(self, result: LookupResult | None, name: str = "mock"):
        self._result = result
        self._name = name
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    def lookup(self, identifiers: RecordIdentifiers) -> LookupResult | None:
        self.call_count += 1
        return self._result


class TestCascadeLookup:
    def test_returns_first_success(self):
        svc1 = MockLookupService(result=None)
        svc2 = MockLookupService(result=LookupResult(lc_class="QA76", source="mock2"))
        result = _cascade_lookup(RecordIdentifiers(), [svc1, svc2])
        assert result is not None
        assert result.lc_class == "QA76"
        assert svc1.call_count == 1
        assert svc2.call_count == 1

    def test_returns_none_when_all_fail(self):
        svc1 = MockLookupService(result=None)
        svc2 = MockLookupService(result=None)
        result = _cascade_lookup(RecordIdentifiers(), [svc1, svc2])
        assert result is None

    def test_short_circuits_on_first_success(self):
        svc1 = MockLookupService(result=LookupResult(lc_class="PS3552", source="mock1"))
        svc2 = MockLookupService(result=LookupResult(lc_class="QA76", source="mock2"))
        _cascade_lookup(RecordIdentifiers(), [svc1, svc2])
        assert svc2.call_count == 0

    def test_handles_service_exception_gracefully(self):
        bad_svc = MockLookupService(result=None)
        bad_svc.lookup = MagicMock(side_effect=RuntimeError("API down"))
        good_svc = MockLookupService(result=LookupResult(lc_class="QA76", source="good"))
        result = _cascade_lookup(RecordIdentifiers(), [bad_svc, good_svc])
        assert result is not None
        assert result.lc_class == "QA76"


class TestConverter:
    def _make_converter(self, tmp_path: Path, result: LookupResult | None) -> tuple[Converter, ProgressTracker]:
        db_path = tmp_path / "progress.db"
        output_dir = tmp_path / "output"
        tracker = ProgressTracker(db_path)
        svc = MockLookupService(result=result)
        converter = Converter(
            lookup_services=[svc],
            tracker=tracker,
            output_dir=output_dir,
            resume=True,
        )
        return converter, tracker

    def test_converts_dewey_record_to_lc(self, tmp_path: Path):
        input_path = tmp_path / "input.mrc"
        _write_mrc([_make_record("CTL001", dewey="005.133")], input_path)

        result = LookupResult(lc_class="QA76.73.P98", lc_item="B37 2022", source="mock")
        converter, tracker = self._make_converter(tmp_path, result)
        stats = converter.convert_file(input_path)

        assert stats.converted == 1
        assert stats.no_match == 0

        summary = tracker.summary()
        assert summary.get("converted", 0) == 1

    def test_skips_record_without_dewey(self, tmp_path: Path):
        input_path = tmp_path / "input.mrc"
        _write_mrc([_make_record("CTL001", dewey=None)], input_path)

        converter, tracker = self._make_converter(tmp_path, None)
        stats = converter.convert_file(input_path)

        assert stats.skipped == 1
        assert stats.converted == 0

    def test_flags_record_with_no_match(self, tmp_path: Path):
        input_path = tmp_path / "input.mrc"
        _write_mrc([_make_record("CTL001", dewey="005.133")], input_path)

        converter, tracker = self._make_converter(tmp_path, None)
        stats = converter.convert_file(input_path)

        assert stats.no_match == 1
        assert stats.converted == 0
        summary = tracker.summary()
        assert summary.get("no_match", 0) == 1

    def test_resume_skips_already_processed(self, tmp_path: Path):
        input_path = tmp_path / "input.mrc"
        _write_mrc([_make_record("CTL001", dewey="005.133")], input_path)

        result = LookupResult(lc_class="QA76.73.P98", source="mock")
        converter, tracker = self._make_converter(tmp_path, result)

        # First run
        stats1 = converter.convert_file(input_path)
        assert stats1.converted == 1

        # Second run — should skip
        stats2 = converter.convert_file(input_path)
        assert stats2.skipped == 1
        assert stats2.converted == 0

    def test_converts_record_with_092_dewey(self, tmp_path: Path):
        input_path = tmp_path / "input.mrc"
        record = _make_record("CTL001", dewey=None)
        record.add_field(Field(tag="092", indicators=[" ", " "], subfields=[Subfield("a", "944.033")]))
        _write_mrc([record], input_path)

        result = LookupResult(lc_class="DC130", source="mock")
        converter, tracker = self._make_converter(tmp_path, result)
        stats = converter.convert_file(input_path)

        assert stats.converted == 1
        row = tracker.get_all_records()[0]
        assert row["old_dewey"] == "944.033"
        assert row["dewey_field"] == "092"

    def test_non_dewey_099_with_oclc_is_looked_up_by_oclc_only(self, tmp_path: Path):
        input_path = tmp_path / "input.mrc"
        record = _make_record("CTL001", dewey=None, oclc="11538750")
        record.add_field(Field(tag="010", indicators=[" ", " "], subfields=[Subfield("a", "29018845")]))
        record.add_field(Field(tag="099", indicators=[" ", " "], subfields=[Subfield("a", "FIC SMITH")]))
        _write_mrc([record], input_path)

        svc = MagicMock(spec=LookupService)
        svc.name = "mock"
        svc.lookup.return_value = LookupResult(lc_class="DC130", source="mock")
        tracker = ProgressTracker(tmp_path / "progress.db")
        converter = Converter(lookup_services=[svc], tracker=tracker, output_dir=tmp_path / "output")
        stats = converter.convert_file(input_path)

        assert stats.converted == 1
        ids = svc.lookup.call_args.args[0]
        assert ids.oclc_number == "11538750"
        assert ids.lccn is None
        assert ids.isbn == []
        row = tracker.get_all_records()[0]
        assert row["old_dewey"] == "FIC SMITH"
        assert row["dewey_field"] == "099 (not Dewey)"

    def test_non_dewey_099_without_oclc_is_skipped(self, tmp_path: Path):
        input_path = tmp_path / "input.mrc"
        record = _make_record("CTL001", dewey=None)
        record.add_field(Field(tag="099", indicators=[" ", " "], subfields=[Subfield("a", "FIC SMITH")]))
        _write_mrc([record], input_path)

        converter, tracker = self._make_converter(tmp_path, LookupResult(lc_class="DC130", source="mock"))
        stats = converter.convert_file(input_path)

        assert stats.skipped == 1
        assert stats.converted == 0

    def test_converted_output_keeps_082(self, tmp_path: Path):
        input_path = tmp_path / "input.mrc"
        _write_mrc([_make_record("CTL001", dewey="005.133")], input_path)

        converter, tracker = self._make_converter(tmp_path, LookupResult(lc_class="QA76.73.P98", source="mock"))
        converter.convert_file(input_path)

        from dewey_to_lc.marc_utils import read_marc_file
        out = list(read_marc_file(tmp_path / "output" / "input.mrc"))[0]
        assert out["082"]["a"] == "005.133"
        assert out["050"]["a"] == "QA76.73.P98"

    def test_output_mrc_file_is_written(self, tmp_path: Path):
        input_path = tmp_path / "input.mrc"
        _write_mrc([_make_record("CTL001", dewey="005.133")], input_path)

        result = LookupResult(lc_class="QA76.73.P98", source="mock")
        converter, tracker = self._make_converter(tmp_path, result)
        converter.convert_file(input_path)

        output_path = tmp_path / "output" / "input.mrc"
        assert output_path.exists()
        assert output_path.stat().st_size > 0
