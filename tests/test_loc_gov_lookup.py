"""Tests for the loc.gov API lookup service."""

from __future__ import annotations

import pytest
import responses as resp_lib

from dewey_to_lc.lookup.loc_gov import LocGovLookup, _extract_050_from_loc_response
from dewey_to_lc.marc_utils import RecordIdentifiers


LOC_SEARCH_URL = "https://www.loc.gov/books/"

_LOC_RESPONSE_WITH_CALL_NUMBER = {
    "results": [
        {
            "call_number": ["QA76.73.P98 B37 2022"],
            "title": "Python programming",
            "item": {},
        }
    ]
}

_LOC_RESPONSE_NO_CALL_NUMBER = {
    "results": [
        {
            "call_number": [],
            "title": "Unknown book",
            "item": {},
        }
    ]
}

_LOC_RESPONSE_DEWEY_IN_CALL_NUMBER = {
    "results": [
        {
            "call_number": ["005.133"],  # Dewey — should be ignored (starts with digit)
            "title": "Some book",
            "item": {},
        }
    ]
}

_LOC_RESPONSE_EMPTY = {"results": []}


class TestExtract050FromLocResponse:
    def test_extracts_lc_call_number(self):
        result = _extract_050_from_loc_response(_LOC_RESPONSE_WITH_CALL_NUMBER)
        assert result is not None
        lc_class, lc_item = result
        assert lc_class == "QA76.73.P98"
        assert lc_item == "B37 2022"

    def test_ignores_dewey_call_number(self):
        result = _extract_050_from_loc_response(_LOC_RESPONSE_DEWEY_IN_CALL_NUMBER)
        assert result is None

    def test_returns_none_when_no_results(self):
        result = _extract_050_from_loc_response(_LOC_RESPONSE_EMPTY)
        assert result is None

    def test_returns_none_when_no_call_number(self):
        result = _extract_050_from_loc_response(_LOC_RESPONSE_NO_CALL_NUMBER)
        assert result is None

    def test_call_number_without_item(self):
        data = {"results": [{"call_number": ["PS3552.E796"], "item": {}}]}
        result = _extract_050_from_loc_response(data)
        assert result == ("PS3552.E796", None)


class TestLocGovLookup:
    @resp_lib.activate
    def test_lookup_by_lccn_returns_result(self):
        resp_lib.add(
            resp_lib.GET,
            LOC_SEARCH_URL,
            json=_LOC_RESPONSE_WITH_CALL_NUMBER,
            status=200,
        )
        svc = LocGovLookup(rate_limit=100.0)
        ids = RecordIdentifiers(lccn="2022012345")
        result = svc.lookup(ids)

        assert result is not None
        assert result.lc_class == "QA76.73.P98"
        assert result.lc_item == "B37 2022"
        assert result.source == "loc.gov"
        svc.close()

    @resp_lib.activate
    def test_lookup_by_isbn_fallback(self):
        resp_lib.add(
            resp_lib.GET,
            LOC_SEARCH_URL,
            json=_LOC_RESPONSE_WITH_CALL_NUMBER,
            status=200,
        )
        svc = LocGovLookup(rate_limit=100.0)
        ids = RecordIdentifiers(isbn=["9780134444321"])
        result = svc.lookup(ids)

        assert result is not None
        assert result.lc_class == "QA76.73.P98"
        svc.close()

    @resp_lib.activate
    def test_returns_none_when_no_match(self):
        resp_lib.add(
            resp_lib.GET,
            LOC_SEARCH_URL,
            json=_LOC_RESPONSE_EMPTY,
            status=200,
        )
        svc = LocGovLookup(rate_limit=100.0)
        ids = RecordIdentifiers(lccn="0000000000")
        result = svc.lookup(ids)
        assert result is None
        svc.close()

    @resp_lib.activate
    def test_returns_none_on_api_error(self):
        resp_lib.add(
            resp_lib.GET,
            LOC_SEARCH_URL,
            status=500,
        )
        svc = LocGovLookup(rate_limit=100.0)
        ids = RecordIdentifiers(lccn="2022012345")
        result = svc.lookup(ids)
        assert result is None
        svc.close()

    def test_returns_none_with_no_identifiers(self):
        svc = LocGovLookup(rate_limit=100.0)
        ids = RecordIdentifiers()
        result = svc.lookup(ids)
        assert result is None
        svc.close()
