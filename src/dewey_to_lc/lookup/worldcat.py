"""WorldCat Metadata API lookup service using bookops-worldcat."""

from __future__ import annotations

import logging
import re
import time

from bookops_worldcat import WorldcatAccessToken, MetadataSession

from dewey_to_lc.lookup.base import LookupResult, LookupService
from dewey_to_lc.marc_utils import RecordIdentifiers

logger = logging.getLogger(__name__)

# Start of a second call number within a string: a 2-3 letter class
# ("PR6068") or a class with an attached cutter ("E185.97.K5"). A cutter on
# its own ("C6", "H365") is a single letter, so it doesn't match.
_NEXT_CALL_NUMBER = re.compile(r"\s+(?=[A-Z]{2,3}\d|[A-Z]\d+(?:\.\d+)?\.[A-Z]\d)")

def _extract_lc_from_bib(data: dict) -> str | None:
    """Extract the record's own LC call number from a full bib response.

    Response shape: {"classification": {"lc": "PN4270 .O73 1817", ...}, ...}

    A record with more than one LC number gets them joined with spaces
    ("PZ7.R79835 Har 1999 PR6068.O93 H365 1999"); only the first is kept.
    """
    try:
        lc = data.get("classification", {}).get("lc")
        if lc and lc.strip():
            return _NEXT_CALL_NUMBER.split(lc.strip(), maxsplit=1)[0]
    except AttributeError:
        pass
    return None


def _extract_lc_from_classification(data: dict) -> str | None:
    """Extract the most popular LC call number from a classification response.

    Response shape: {"lc": {"mostPopular": ["HM742 .H55 2010"]}, ...}
    """
    try:
        popular = data.get("lc", {}).get("mostPopular", [])
        if popular:
            return popular[0].strip()
    except (AttributeError, IndexError):
        pass
    return None


def _split_lc_call_number(call_number: str) -> tuple[str, str | None]:
    """Split a full LC call number into class (050 $a) and item (050 $b).

    e.g. "HM742 .H55 2010" -> ("HM742", ".H55 2010")
         "QA76.73.P98"     -> ("QA76.73.P98", None)
    """
    parts = call_number.split(" ", 1)
    return parts[0], parts[1] if len(parts) > 1 else None


class WorldCatLookup(LookupService):
    """Looks up LC classification via the OCLC WorldCat Metadata API.

    Strategy (per record):
    1. If OCLC# is available: call /search/bibs/{oclcNumber} and use the
       record's own LC call number.
    2. If that record has none: call /search/classification-bibs/{oclcNumber}
       for the most popular LC number across the work cluster. This can come
       from another edition or format (e.g. a microform of a print book).
    3. If no OCLC# (or steps 1-2 return nothing): search brief-bibs by LCCN
       or ISBN to get an OCLC#, then retry steps 1-2.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        rate_limit: float = 1.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._min_interval = 1.0 / max(rate_limit, 0.1)
        self._last_request_time: float = 0.0
        self._session: MetadataSession | None = None

    @property
    def name(self) -> str:
        return "worldcat"

    def _get_session(self) -> MetadataSession:
        if self._session is None:
            token = WorldcatAccessToken(
                key=self._client_id,
                secret=self._client_secret,
                scopes="WorldCatMetadataAPI",
            )
            self._session = MetadataSession(authorization=token)
        return self._session

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()

    def _get_classification(self, session: MetadataSession, oclc_number: str) -> str | None:
        """Call /search/classification-bibs/{oclcNumber} and return LC call number."""
        self._throttle()
        try:
            response = session.bib_get_classification(oclcNumber=oclc_number)
            if response.status_code == 200:
                return _extract_lc_from_classification(response.json())
        except Exception as exc:
            logger.warning("WorldCat classification lookup failed for OCLC# %s: %s", oclc_number, exc)
        return None

    def _get_record_lc(self, session: MetadataSession, oclc_number: str) -> str | None:
        """Call /search/bibs/{oclcNumber} and return the record's own LC call number."""
        self._throttle()
        try:
            response = session.bib_search(oclcNumber=oclc_number)
            if response.status_code == 200:
                return _extract_lc_from_bib(response.json())
        except Exception as exc:
            logger.warning("WorldCat bib lookup failed for OCLC# %s: %s", oclc_number, exc)
        return None

    def _oclc_from_search(self, session: MetadataSession, query: str) -> str | None:
        """Search brief-bibs and return the first OCLC number found."""
        self._throttle()
        try:
            response = session.brief_bibs_search(q=query)
            if response.status_code == 200:
                records = response.json().get("briefRecords", [])
                if records:
                    return str(records[0].get("oclcNumber", ""))
        except Exception as exc:
            logger.warning("WorldCat brief-bibs search failed for '%s': %s", query, exc)
        return None

    def _lookup_by_oclc(self, session: MetadataSession, oclc_number: str) -> LookupResult | None:
        """Try the record's own LC number first, fall back to the most popular."""
        lc_full = self._get_record_lc(session, oclc_number)
        if not lc_full:
            lc_full = self._get_classification(session, oclc_number)
        if lc_full:
            lc_class, lc_item = _split_lc_call_number(lc_full)
            return LookupResult(lc_class=lc_class, lc_item=lc_item, source=self.name)
        return None

    def lookup(self, identifiers: RecordIdentifiers) -> LookupResult | None:
        """Look up LC classification, trying OCLC# → LCCN search → ISBN search."""
        try:
            session = self._get_session()
        except Exception as exc:
            logger.error("Failed to create WorldCat session: %s", exc)
            return None

        # 1. Direct OCLC# lookup (fastest, most precise)
        if identifiers.oclc_number:
            logger.debug("WorldCat classification lookup by OCLC#: %s", identifiers.oclc_number)
            result = self._lookup_by_oclc(session, identifiers.oclc_number)
            if result:
                return result

        # 2. Search by LCCN to get an OCLC#
        if identifiers.lccn:
            logger.debug("WorldCat brief-bibs search by LCCN: %s", identifiers.lccn)
            oclc = self._oclc_from_search(session, f"ln:{identifiers.lccn}")
            if oclc:
                result = self._lookup_by_oclc(session, oclc)
                if result:
                    return result

        # 3. Search by ISBN to get an OCLC#
        for isbn in identifiers.isbn:
            logger.debug("WorldCat brief-bibs search by ISBN: %s", isbn)
            oclc = self._oclc_from_search(session, f"bn:{isbn}")
            if oclc:
                result = self._lookup_by_oclc(session, oclc)
                if result:
                    return result

        return None

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
