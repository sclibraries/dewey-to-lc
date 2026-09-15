"""Tests for the WorldCat Metadata API lookup service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dewey_to_lc.lookup.worldcat import (
    WorldCatLookup,
    _extract_050_from_marcxml,
    _extract_lc_from_classification,
    _split_lc_call_number,
)
from dewey_to_lc.marc_utils import RecordIdentifiers


_MARCXML_WITH_050 = """<?xml version="1.0" encoding="UTF-8"?>
<record xmlns="http://www.loc.gov/MARC21/slim">
  <leader>00000cam a2200000 a 4500</leader>
  <datafield tag="050" ind1=" " ind2="0">
    <subfield code="a">QA76.73.P98</subfield>
    <subfield code="b">B37 2022</subfield>
  </datafield>
</record>"""

_MARCXML_NO_050 = """<?xml version="1.0" encoding="UTF-8"?>
<record xmlns="http://www.loc.gov/MARC21/slim">
  <datafield tag="082" ind1="0" ind2="4">
    <subfield code="a">005.133</subfield>
  </datafield>
</record>"""

_MARCXML_COLLECTION = """<?xml version="1.0" encoding="UTF-8"?>
<collection xmlns="http://www.loc.gov/MARC21/slim">
  <record>
    <datafield tag="050" ind1=" " ind2="4">
      <subfield code="a">PS3552.E796</subfield>
      <subfield code="b">A23 2005</subfield>
    </datafield>
  </record>
</collection>"""

_CLASSIFICATION_RESPONSE = {
    "lc": {"mostPopular": ["HM742 .H55 2010"]},
    "dewey": {"mostPopular": ["302.30285"]},
}

_CLASSIFICATION_NO_LC = {
    "dewey": {"mostPopular": ["302.30285"]},
}

_BRIEF_BIBS_RESPONSE = {
    "briefRecords": [
        {"oclcNumber": "12345678", "title": "Python programming essentials"}
    ]
}


def _mock_response(status_code: int, json_data: dict | None = None, text: str = ""):
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text
    mock.json.return_value = json_data or {}
    return mock


class TestExtractLcFromClassification:
    def test_extracts_most_popular(self):
        result = _extract_lc_from_classification(_CLASSIFICATION_RESPONSE)
        assert result == "HM742 .H55 2010"

    def test_returns_none_when_no_lc(self):
        result = _extract_lc_from_classification(_CLASSIFICATION_NO_LC)
        assert result is None

    def test_returns_none_on_empty_dict(self):
        assert _extract_lc_from_classification({}) is None

    def test_returns_none_on_empty_list(self):
        assert _extract_lc_from_classification({"lc": {"mostPopular": []}}) is None


class TestSplitLcCallNumber:
    def test_splits_class_and_item(self):
        assert _split_lc_call_number("HM742 .H55 2010") == ("HM742", ".H55 2010")

    def test_no_item_number(self):
        assert _split_lc_call_number("QA76.73.P98") == ("QA76.73.P98", None)

    def test_multiple_spaces_in_item(self):
        lc_class, lc_item = _split_lc_call_number("PS3552.E796 A23 2022")
        assert lc_class == "PS3552.E796"
        assert lc_item == "A23 2022"


class TestExtract050FromMarcxml:
    def test_extracts_from_bare_record(self):
        result = _extract_050_from_marcxml(_MARCXML_WITH_050)
        assert result == ("QA76.73.P98", "B37 2022")

    def test_extracts_from_collection_wrapper(self):
        result = _extract_050_from_marcxml(_MARCXML_COLLECTION)
        assert result == ("PS3552.E796", "A23 2005")

    def test_returns_none_when_no_050(self):
        result = _extract_050_from_marcxml(_MARCXML_NO_050)
        assert result is None

    def test_returns_none_on_invalid_xml(self):
        result = _extract_050_from_marcxml("not xml at all <<>>")
        assert result is None


class TestWorldCatLookup:
    def _make_lookup(self) -> WorldCatLookup:
        return WorldCatLookup(client_id="test-id", client_secret="test-secret", rate_limit=1000.0)

    @patch("dewey_to_lc.lookup.worldcat.WorldcatAccessToken")
    @patch("dewey_to_lc.lookup.worldcat.MetadataSession")
    def test_uses_classification_endpoint_for_oclc(self, MockSession, MockToken):
        session_instance = MockSession.return_value
        session_instance.bib_get_classification.return_value = _mock_response(200, _CLASSIFICATION_RESPONSE)

        svc = self._make_lookup()
        result = svc.lookup(RecordIdentifiers(oclc_number="12345678"))

        assert result is not None
        assert result.lc_class == "HM742"
        assert result.lc_item == ".H55 2010"
        assert result.source == "worldcat"
        session_instance.bib_get_classification.assert_called_once_with(oclcNumber="12345678")
        session_instance.bib_get.assert_not_called()  # no need for MARCXML
        svc.close()

    @patch("dewey_to_lc.lookup.worldcat.WorldcatAccessToken")
    @patch("dewey_to_lc.lookup.worldcat.MetadataSession")
    def test_falls_back_to_marcxml_when_no_lc_classification(self, MockSession, MockToken):
        session_instance = MockSession.return_value
        session_instance.bib_get_classification.return_value = _mock_response(200, _CLASSIFICATION_NO_LC)
        session_instance.bib_get.return_value = _mock_response(200, text=_MARCXML_WITH_050)

        svc = self._make_lookup()
        result = svc.lookup(RecordIdentifiers(oclc_number="12345678"))

        assert result is not None
        assert result.lc_class == "QA76.73.P98"
        session_instance.bib_get.assert_called_once()
        svc.close()

    @patch("dewey_to_lc.lookup.worldcat.WorldcatAccessToken")
    @patch("dewey_to_lc.lookup.worldcat.MetadataSession")
    def test_searches_by_lccn_when_no_oclc(self, MockSession, MockToken):
        session_instance = MockSession.return_value
        session_instance.brief_bibs_search.return_value = _mock_response(200, _BRIEF_BIBS_RESPONSE)
        session_instance.bib_get_classification.return_value = _mock_response(200, _CLASSIFICATION_RESPONSE)

        svc = self._make_lookup()
        result = svc.lookup(RecordIdentifiers(lccn="2022012345"))

        assert result is not None
        assert result.lc_class == "HM742"
        session_instance.brief_bibs_search.assert_called_once_with(q="ln:2022012345")
        svc.close()

    @patch("dewey_to_lc.lookup.worldcat.WorldcatAccessToken")
    @patch("dewey_to_lc.lookup.worldcat.MetadataSession")
    def test_searches_by_isbn_when_no_oclc_or_lccn(self, MockSession, MockToken):
        session_instance = MockSession.return_value
        session_instance.brief_bibs_search.return_value = _mock_response(200, _BRIEF_BIBS_RESPONSE)
        session_instance.bib_get_classification.return_value = _mock_response(200, _CLASSIFICATION_RESPONSE)

        svc = self._make_lookup()
        result = svc.lookup(RecordIdentifiers(isbn=["9780134444321"]))

        assert result is not None
        session_instance.brief_bibs_search.assert_called_once_with(q="bn:9780134444321")
        svc.close()

    @patch("dewey_to_lc.lookup.worldcat.WorldcatAccessToken")
    @patch("dewey_to_lc.lookup.worldcat.MetadataSession")
    def test_oclc_takes_priority_over_lccn_and_isbn(self, MockSession, MockToken):
        session_instance = MockSession.return_value
        session_instance.bib_get_classification.return_value = _mock_response(200, _CLASSIFICATION_RESPONSE)

        svc = self._make_lookup()
        svc.lookup(RecordIdentifiers(oclc_number="99", lccn="2022012345", isbn=["9780000000000"]))

        session_instance.bib_get_classification.assert_called_once_with(oclcNumber="99")
        session_instance.brief_bibs_search.assert_not_called()
        svc.close()

    @patch("dewey_to_lc.lookup.worldcat.WorldcatAccessToken")
    @patch("dewey_to_lc.lookup.worldcat.MetadataSession")
    def test_returns_none_with_no_identifiers(self, MockSession, MockToken):
        svc = self._make_lookup()
        result = svc.lookup(RecordIdentifiers())
        assert result is None
        svc.close()

    @patch("dewey_to_lc.lookup.worldcat.WorldcatAccessToken")
    @patch("dewey_to_lc.lookup.worldcat.MetadataSession")
    def test_returns_none_when_all_lookups_fail(self, MockSession, MockToken):
        session_instance = MockSession.return_value
        session_instance.bib_get_classification.return_value = _mock_response(404)
        session_instance.bib_get.return_value = _mock_response(404)

        svc = self._make_lookup()
        result = svc.lookup(RecordIdentifiers(oclc_number="00000000"))
        assert result is None
        svc.close()

    @patch("dewey_to_lc.lookup.worldcat.WorldcatAccessToken")
    @patch("dewey_to_lc.lookup.worldcat.MetadataSession")
    def test_handles_api_exception_gracefully(self, MockSession, MockToken):
        session_instance = MockSession.return_value
        session_instance.bib_get_classification.side_effect = RuntimeError("network error")

        svc = self._make_lookup()
        result = svc.lookup(RecordIdentifiers(oclc_number="12345678"))
        assert result is None
        svc.close()

    @patch("dewey_to_lc.lookup.worldcat.WorldcatAccessToken")
    @patch("dewey_to_lc.lookup.worldcat.MetadataSession")
    def test_close_clears_session(self, MockSession, MockToken):
        svc = self._make_lookup()
        _ = svc._get_session()
        assert svc._session is not None
        svc.close()
        assert svc._session is None
