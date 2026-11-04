"""Anthropic Claude adapter using the official ``anthropic`` SDK and structured outputs."""

from __future__ import annotations

import time

import anthropic

from cyberlead360.config.logging import get_logger
from cyberlead360.domain.exceptions import AIProviderError
from cyberlead360.integrations.llm.base import LLMResult, T

log = get_logger("llm.anthropic")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds, max_retries=2)

    def generate_structured(
        self, *, system: str, user: str, schema: type[T], max_tokens: int
    ) -> LLMResult[T]:
        started = time.perf_counter()
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
        except anthropic.AuthenticationError as exc:
            raise AIProviderError("Anthropic rejected the API key.") from exc
        except anthropic.RateLimitError as exc:
            raise AIProviderError("Anthropic rate limit reached; try again later.") from exc
        except anthropic.APITimeoutError as exc:
            raise AIProviderError("The Anthropic request timed out.") from exc
        except anthropic.APIConnectionError as exc:
            raise AIProviderError("Could not reach the Anthropic API.") from exc
        except anthropic.APIStatusError as exc:
            raise AIProviderError(f"Anthropic API error (HTTP {exc.status_code}).") from exc
        except ValueError as exc:  # schema/parse problems raised by the SDK helper
            raise AIProviderError(f"Structured output could not be parsed: {exc}") from exc

        latency = int((time.perf_counter() - started) * 1000)
        if response.stop_reason == "refusal":
            raise AIProviderError("The model declined this request; template mode will be used.")
        if response.stop_reason == "max_tokens":
            raise AIProviderError("The output hit the token limit before completion.")
        parsed = response.parsed_output
        if parsed is None:
            raise AIProviderError("The model returned no structured output.")
        usage = response.usage
        log.info(
            "llm call completed",
            extra={
                "provider": self.name,
                "model": self.model,
                "latency_ms": latency,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            },
        )
        return LLMResult(
            output=parsed,
            provider=self.name,
            model=self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=latency,
        )
