"""Provider adapters with the SDK client methods stubbed (no network, no API key)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from cyberlead360.config.settings import Settings
from cyberlead360.domain.exceptions import AIProviderError
from cyberlead360.domain.schemas import OutreachDraftOutput
from cyberlead360.integrations.llm.anthropic_provider import AnthropicProvider
from cyberlead360.integrations.llm.factory import build_provider
from cyberlead360.integrations.llm.openai_compatible import OpenAICompatibleProvider

DRAFT = OutreachDraftOutput(subject="Hi", body="Hello {{first_name}}, a short professional note.")


def anthropic_with(response=None, exc: Exception | None = None) -> AnthropicProvider:  # type: ignore[no-untyped-def]
    provider = AnthropicProvider(api_key="test-key", model="claude-opus-5-5", timeout_seconds=5)

    def parse(**kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["output_format"] is OutreachDraftOutput
        assert kwargs["system"] and kwargs["messages"][0]["role"] == "user"
        if exc:
            raise exc
        return response

    provider._client = SimpleNamespace(messages=SimpleNamespace(parse=parse))  # type: ignore[assignment]
    return provider


def test_anthropic_success_maps_usage() -> None:
    response = SimpleNamespace(
        stop_reason="end_turn",
        parsed_output=DRAFT,
        usage=SimpleNamespace(input_tokens=321, output_tokens=54),
    )
    result = anthropic_with(response).generate_structured(
        system="s", user="u", schema=OutreachDraftOutput, max_tokens=500
    )
    assert result.output == DRAFT
    assert (result.input_tokens, result.output_tokens) == (321, 54)
    assert result.provider == "anthropic" and result.model == "claude-opus-5-5"


@pytest.mark.parametrize(
    ("stop_reason", "parsed", "message"),
    [
        ("refusal", None, "declined"),
        ("max_tokens", None, "token limit"),
        ("end_turn", None, "no structured output"),
    ],
)
def test_anthropic_unusable_responses_raise(stop_reason: str, parsed, message: str) -> None:  # type: ignore[no-untyped-def]
    response = SimpleNamespace(
        stop_reason=stop_reason,
        parsed_output=parsed,
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    with pytest.raises(AIProviderError, match=message):
        anthropic_with(response).generate_structured(
            system="s", user="u", schema=OutreachDraftOutput, max_tokens=10
        )


def test_anthropic_parse_errors_become_provider_errors() -> None:
    with pytest.raises(AIProviderError, match="could not be parsed"):
        anthropic_with(exc=ValueError("bad json")).generate_structured(
            system="s", user="u", schema=OutreachDraftOutput, max_tokens=10
        )


def openai_with(content: str, finish_reason: str = "stop") -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider(
        api_key=None, model="local-model", timeout_seconds=5, base_url="http://localhost:9/v1"
    )
    calls: list[dict] = []

    def create(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=finish_reason, message=SimpleNamespace(content=content)
                )
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )

    provider._client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    provider.calls = calls  # type: ignore[attr-defined]
    return provider


def test_openai_compatible_validates_json_against_schema() -> None:
    provider = openai_with(DRAFT.model_dump_json())
    result = provider.generate_structured(
        system="s", user="u", schema=OutreachDraftOutput, max_tokens=200
    )
    assert result.output == DRAFT and result.input_tokens == 100
    sent = provider.calls[0]  # type: ignore[attr-defined]
    assert sent["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in sent["messages"][0]["content"]


@pytest.mark.parametrize(
    ("content", "finish", "message"),
    [('{"body": "short"}', "stop", "did not match"), ("{}", "length", "token limit")],
)
def test_openai_compatible_rejects_bad_output(content: str, finish: str, message: str) -> None:
    with pytest.raises(AIProviderError, match=message):
        openai_with(content, finish).generate_structured(
            system="s", user="u", schema=OutreachDraftOutput, max_tokens=10
        )


def test_factory_selects_provider_from_settings() -> None:
    base = {"_env_file": None, "database_url": "sqlite:///:memory:"}
    assert build_provider(Settings(**base, llm_provider="none")) is None
    assert build_provider(Settings(**base, llm_provider="anthropic")) is None  # no key
    anthropic = build_provider(
        Settings(**base, llm_provider="anthropic", anthropic_api_key=SecretStr("k"))
    )
    assert isinstance(anthropic, AnthropicProvider)
    local = build_provider(
        Settings(**base, llm_provider="openai_compatible", openai_base_url="http://localhost:1/v1")
    )
    assert isinstance(local, OpenAICompatibleProvider)


def test_settings_never_expose_secrets() -> None:
    s = Settings(
        _env_file=None, llm_provider="anthropic", anthropic_api_key=SecretStr("sk-ant-secret")
    )
    assert "sk-ant-secret" not in repr(s)
    assert "sk-ant-secret" not in str(s.public_summary())
