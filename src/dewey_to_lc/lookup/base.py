"""Abstract base class for LC classification lookup services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from dewey_to_lc.marc_utils import RecordIdentifiers


@dataclass
class LookupResult:
    """Result from an LC classification lookup."""

    lc_class: str
    lc_item: str | None = None
    source: str = "unknown"

    @property
    def full_call_number(self) -> str:
        if self.lc_item:
            return f"{self.lc_class} {self.lc_item}"
        return self.lc_class


class LookupService(ABC):
    """Abstract interface for an LC classification lookup service."""

    @abstractmethod
    def lookup(self, identifiers: RecordIdentifiers) -> LookupResult | None:
        """Look up an LC classification for the given record identifiers.

        Returns a LookupResult if found, or None if no match.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this lookup service."""
        ...
