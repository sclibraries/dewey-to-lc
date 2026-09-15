"""WorldCat Metadata API lookup service using bookops-worldcat."""

from __future__ import annotations

import logging
import time
from xml.etree import ElementTree as ET

from bookops_worldcat import WorldcatAccessToken, MetadataSession

from dewey_to_lc.lookup.base import LookupResult, LookupService
from dewey_to_lc.marc_utils import RecordIdentifiers

logger = logging.getLogger(__name__)

# MARCXML namespace
_NS = {"marc": "http://www.loc.gov/MARC21/slim"}


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


def _extract_050_from_marcxml(xml_text: str) -> tuple[str, str | None] | None:
    """Parse MARCXML and extract the first 050 $a and $b subfields."""
    try:
        root = ET.fromstring(xml_text)
        records = root.findall(".//marc:record", _NS) or [root]
        for rec in records:
            for field in rec.findall("marc:datafield[@tag='050']", _NS):
                lc_a = field.find("marc:subfield[@code='a']", _NS)
                lc_b = field.find("marc:subfield[@code='b']", _NS)
                if lc_a is not None and lc_a.text:
                    return lc_a.text.strip(), (lc_b.text.strip() if lc_b is not None else None)
    except ET.ParseError as exc:
        logger.warning("Failed to parse MARCXML response: %s", exc)
    return None


class WorldCatLookup(LookupService):
    """Looks up LC classification via the OCLC WorldCat Metadata API.

    Strategy (per record):
    1. If OCLC# is available: call /search/classification-bibs/{oclcNumber}
       which returns LC classification recommendations directly (JSON).
    2. If no OCLC# (or classification endpoint returns nothing): search
       brief-bibs by LCCN or ISBN to get an OCLC#, then retry step 1.
    3. Fallback: fetch full MARCXML via /manage/bibs/{oclcNumber} and
       parse the 050 field directly.
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

    def _get_marcxml_050(self, session: MetadataSession, oclc_number: str) -> tuple[str, str | None] | None:
        """Fetch full MARCXML and extract 050 as a fallback."""
        self._throttle()
        try:
            response = session.bib_get(oclcNumber=oclc_number, responseFormat="application/marcxml+xml")
            if response.status_code == 200:
                return _extract_050_from_marcxml(response.text)
        except Exception as exc:
            logger.warning("WorldCat MARCXML fetch failed for OCLC# %s: %s", oclc_number, exc)
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
        """Try classification endpoint first, fall back to full MARCXML 050."""
        lc_full = self._get_classification(session, oclc_number)
        if lc_full:
            lc_class, lc_item = _split_lc_call_number(lc_full)
            return LookupResult(lc_class=lc_class, lc_item=lc_item, source=self.name)

        # Fallback: parse 050 from full MARCXML
        parsed = self._get_marcxml_050(session, oclc_number)
        if parsed:
            return LookupResult(lc_class=parsed[0], lc_item=parsed[1], source=self.name)

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
