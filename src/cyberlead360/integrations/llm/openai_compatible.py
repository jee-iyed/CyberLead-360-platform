"""Adapter for OpenAI and OpenAI-compatible servers (Azure gateways, vLLM, Ollama…).

Uses JSON mode plus the JSON Schema in the prompt — the most widely supported
feature across compatible servers — and validates the result with Pydantic.
"""

from __future__ import annotations

import json
import time

import openai
from pydantic import ValidationError

from cyberlead360.config.logging import get_logger
from cyberlead360.domain.exceptions import AIProviderError
from cyberlead360.integrations.llm.base import LLMResult, T

log = get_logger("llm.openai")


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(
        self, api_key: str | None, model: str, timeout_seconds: float, base_url: str | None
    ) -> None:
        self.model = model
        self._client = openai.OpenAI(
            api_key=api_key or "not-required",
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=2,
        )

    def generate_structured(
        self, *, system: str, user: str, schema: type[T], max_tokens: int
    ) -> LLMResult[T]:
        schema_json = json.dumps(schema.model_json_schema())
        system_full = (
            f"{system}\n\nRespond with a single JSON object that validates against this "
            f"JSON Schema, and nothing else:\n{schema_json}"
        )
        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_full},
                    {"role": "user", "content": user},
                ],
            )
        except openai.AuthenticationError as exc:
            raise AIProviderError("The provider rejected the API key.") from exc
        except openai.RateLimitError as exc:
            raise AIProviderError("Rate limit reached; try again later.") from exc
        except openai.APITimeoutError as exc:
            raise AIProviderError("The LLM request timed out.") from exc
        except openai.APIConnectionError as exc:
            raise AIProviderError("Could not reach the LLM endpoint.") from exc
        except openai.APIStatusError as exc:
            raise AIProviderError(f"LLM API error (HTTP {exc.status_code}).") from exc

        latency = int((time.perf_counter() - started) * 1000)
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise AIProviderError("The output hit the token limit before completion.")
        content = choice.message.content or ""
        try:
            parsed = schema.model_validate_json(content)
        except ValidationError as exc:
            raise AIProviderError("The model output did not match the expected schema.") from exc
        usage = response.usage
        log.info(
            "llm call completed",
            extra={"provider": self.name, "model": self.model, "latency_ms": latency},
        )
        return LLMResult(
            output=parsed,
            provider=self.name,
            model=self.model,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            latency_ms=latency,
        )
