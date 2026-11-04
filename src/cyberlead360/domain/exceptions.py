"""Domain-level exceptions. The UI catches ``CyberLeadError`` and shows its message."""

from __future__ import annotations


class CyberLeadError(Exception):
    """Base class for expected, user-presentable errors."""


class NotFoundError(CyberLeadError):
    def __init__(self, entity: str, entity_id: object) -> None:
        super().__init__(f"{entity} #{entity_id} was not found.")
        self.entity = entity
        self.entity_id = entity_id


class ValidationFailedError(CyberLeadError):
    """Input failed business validation."""


class DuplicateCompanyError(CyberLeadError):
    def __init__(self, message: str, existing_id: int | None = None) -> None:
        super().__init__(message)
        self.existing_id = existing_id


class InvalidTransitionError(CyberLeadError):
    """A pipeline stage change is not permitted by the transition rules."""


class SuppressedContactError(CyberLeadError):
    """The contact objected or is on the suppression list; outreach is blocked."""


class ImportValidationError(CyberLeadError):
    """The uploaded file cannot be processed at all (size, encoding, columns)."""


class RetrievalBlockedError(CyberLeadError):
    """A URL retrieval was refused for safety or policy reasons."""


class AIProviderError(CyberLeadError):
    """The LLM provider failed or returned unusable output."""
