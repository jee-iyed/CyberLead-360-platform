"""Build the configured LLM provider, or ``None`` for deterministic template mode."""

from __future__ import annotations

from cyberlead360.config.settings import Settings
from cyberlead360.integrations.llm.base import LLMProvider


def build_provider(settings: Settings) -> LLMProvider | None:
    if not settings.llm_enabled:
        return None
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        from cyberlead360.integrations.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.anthropic_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if settings.llm_provider == "openai_compatible":
        from cyberlead360.integrations.llm.openai_compatible import OpenAICompatibleProvider

        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        return OpenAICompatibleProvider(
            api_key=key,
            model=settings.openai_model,
            timeout_seconds=settings.llm_timeout_seconds,
            base_url=settings.openai_base_url,
        )
    return None
