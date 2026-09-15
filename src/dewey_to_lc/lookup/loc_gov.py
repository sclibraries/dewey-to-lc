"""Library of Congress loc.gov API fallback lookup service."""

from __future__ import annotations

import logging
import time

import requests

from dewey_to_lc.lookup.base import LookupResult, LookupService
from dewey_to_lc.marc_utils import RecordIdentifiers

logger = logging.getLogger(__name__)

_LOC_SEARCH_URL = "https://www.loc.gov/books/"


def _extract_050_from_loc_response(data: dict) -> tuple[str, str | None] | None:
    """Parse the loc.gov JSON response and find the first 050 LC call number."""
    results = data.get("results", [])
    for result in results:
        # LC API returns MARC data under result['item']['marc'] or 'library_of_congress_number'
        # Try the structured call_number fields first
        call_numbers = result.get("call_number", [])
        for cn in call_numbers:
            cn = cn.strip()
            if cn and not cn[0].isdigit():
                # LC call numbers start with letters; Dewey starts with digits
                parts = cn.split(" ", 1)
                return parts[0], parts[1] if len(parts) > 1 else None

        # Also check the item-level 'library_of_congress_number' if present
        item = result.get("item", {})
        if isinstance(item, dict):
            lc_num = item.get("library_of_congress_number") or item.get("call_number")
            if isinstance(lc_num, list) and lc_num:
                lc_num = lc_num[0]
            if isinstance(lc_num, str) and lc_num.strip() and not lc_num.strip()[0].isdigit():
                parts = lc_num.strip().split(" ", 1)
                return parts[0], parts[1] if len(parts) > 1 else None

    return None


class LocGovLookup(LookupService):
    """Looks up LC classification via the Library of Congress loc.gov public API."""

    def __init__(
        self,
        user_agent: str = "dewey-to-lc/0.1.0",
        rate_limit: float = 2.0,
    ) -> None:
        """
        Args:
            user_agent: User-Agent header for polite API access.
            rate_limit: Maximum requests per second.
        """
        self._user_agent = user_agent
        self._min_interval = 1.0 / max(rate_limit, 0.1)
        self._last_request_time: float = 0.0
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self._user_agent})

    @property
    def name(self) -> str:
        return "loc.gov"

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()

    def _search(self, query: str) -> dict | None:
        """Execute a search against the loc.gov books API."""
        self._throttle()
        try:
            response = self._session.get(
                _LOC_SEARCH_URL,
                params={"q": query, "fo": "json", "at": "results,pagination"},
                timeout=15,
            )
            if response.status_code == 200:
                return response.json()
        except requests.RequestException as exc:
            logger.warning("loc.gov API request failed for query '%s': %s", query, exc)
        return None

    def lookup(self, identifiers: RecordIdentifiers) -> LookupResult | None:
        """Look up LC classification via loc.gov, trying LCCN → ISBN → title."""
        # Try LCCN first (most precise)
        if identifiers.lccn:
            logger.debug("loc.gov lookup by LCCN: %s", identifiers.lccn)
            data = self._search(identifiers.lccn)
            if data:
                parsed = _extract_050_from_loc_response(data)
                if parsed:
                    return LookupResult(lc_class=parsed[0], lc_item=parsed[1], source=self.name)

        # Try each ISBN
        for isbn in identifiers.isbn:
            logger.debug("loc.gov lookup by ISBN: %s", isbn)
            data = self._search(isbn)
            if data:
                parsed = _extract_050_from_loc_response(data)
                if parsed:
                    return LookupResult(lc_class=parsed[0], lc_item=parsed[1], source=self.name)

        return None

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()
