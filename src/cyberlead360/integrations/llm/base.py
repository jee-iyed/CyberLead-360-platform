"""Provider-independent LLM interface.

Services depend on this Protocol only, never on a vendor SDK, so providers are
interchangeable and tests can inject a fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    output: T
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_structured(
        self, *, system: str, user: str, schema: type[T], max_tokens: int
    ) -> LLMResult[T]:
        """Return output validated against ``schema`` or raise ``AIProviderError``."""
        ...


def estimate_cost(
    input_tokens: int | None,
    output_tokens: int | None,
    input_price_per_mtok: float,
    output_price_per_mtok: float,
) -> float | None:
    """Cost in USD from configured prices; ``None`` when prices are not configured."""
    if not (input_price_per_mtok or output_price_per_mtok):
        return None
    return round(
        (input_tokens or 0) / 1e6 * input_price_per_mtok
        + (output_tokens or 0) / 1e6 * output_price_per_mtok,
        6,
    )
