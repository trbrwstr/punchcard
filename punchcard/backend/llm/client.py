"""Anthropic-backed LLM translation client for Punchcard.

The wrapper is intentionally small and injectable. Production code can construct
it with settings loaded from the environment or ``.env``; tests can pass a fake
messages client and avoid real network calls entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from anthropic import Anthropic
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from punchcard.backend.llm.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

ANTHROPIC_TRANSLATION_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 4096


class LLMClientError(RuntimeError):
    """Raised when Punchcard cannot safely call the configured LLM client."""


class MessagesClient(Protocol):
    """Protocol for Anthropic's messages API surface.

    A small protocol keeps tests lightweight: fakes only need to implement
    ``create(**kwargs)`` and can assert on the request payload.
    """

    def create(self, **kwargs: Any) -> Any:
        """Create a model message and return an Anthropic-like response."""


class LLMSettings(BaseSettings):
    """Configuration loaded from environment variables or ``.env``.

    API keys stay in settings, not business logic. In test mode, constructing a
    real Anthropic client is blocked unless a fake ``MessagesClient`` is
    dependency-injected.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    test_mode: bool = Field(default=False, alias="PUNCHCARD_TEST_MODE")
    pytest_current_test: str | None = Field(
        default=None,
        alias="PYTEST_CURRENT_TEST",
        exclude=True,
    )
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, alias="PUNCHCARD_LLM_MAX_TOKENS")

    @property
    def blocks_real_api_calls(self) -> bool:
        """Return whether this process should refuse real provider calls."""

        return self.test_mode or self.pytest_current_test is not None


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token counts reported by the model provider."""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """Translated code plus provider metadata useful for audit logging."""

    translated_code: str
    model_name: str
    token_usage: TokenUsage


class AnthropicTranslationClient:
    """Translate COBOL paragraphs through Anthropic's messages API."""

    def __init__(
        self,
        *,
        settings: LLMSettings | None = None,
        messages_client: MessagesClient | None = None,
        model: str = ANTHROPIC_TRANSLATION_MODEL,
    ) -> None:
        self.settings = settings or LLMSettings()
        self.model = model
        self._messages_client = messages_client or self._build_messages_client()

    def translate_paragraph(
        self,
        *,
        target_language: str,
        paragraph_name: str,
        cobol_source: str,
        complexity_score: int | float,
        suggested_function_name: str,
    ) -> TranslationResult:
        """Translate one COBOL paragraph and return code plus model metadata."""

        user_prompt = USER_PROMPT_TEMPLATE.format(
            target_language=_require_text(target_language, "target_language"),
            paragraph_name=_require_text(paragraph_name, "paragraph_name"),
            cobol_source=_require_text(cobol_source, "cobol_source"),
            complexity_score=complexity_score,
            suggested_function_name=_require_text(
                suggested_function_name,
                "suggested_function_name",
            ),
        )

        response = self._messages_client.create(
            model=self.model,
            max_tokens=self.settings.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        return TranslationResult(
            translated_code=_extract_text(response).strip(),
            model_name=str(getattr(response, "model", self.model)),
            token_usage=_extract_usage(response),
        )

    def translate(
        self,
        *,
        target_language: str,
        paragraph_name: str,
        cobol_source: str,
        complexity_score: int | float,
        suggested_function_name: str,
    ) -> TranslationResult:
        """Alias for callers that prefer a short verb."""

        return self.translate_paragraph(
            target_language=target_language,
            paragraph_name=paragraph_name,
            cobol_source=cobol_source,
            complexity_score=complexity_score,
            suggested_function_name=suggested_function_name,
        )

    def _build_messages_client(self) -> MessagesClient:
        if self.settings.blocks_real_api_calls:
            raise LLMClientError(
                "Test mode is enabled (PUNCHCARD_TEST_MODE or pytest); "
                "inject a fake MessagesClient instead."
            )
        if self.settings.anthropic_api_key is None:
            raise LLMClientError(
                "ANTHROPIC_API_KEY is required unless a MessagesClient is injected."
            )

        api_key = self.settings.anthropic_api_key.get_secret_value()
        return Anthropic(api_key=api_key).messages


def _require_text(value: str, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _extract_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if isinstance(block, dict):
            text = block.get("text")
        else:
            text = getattr(block, "text", None)
        if text:
            parts.append(str(text))

    if not parts:
        raise LLMClientError("Anthropic response did not include text content.")
    return "".join(parts)


def _extract_usage(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage(input_tokens=0, output_tokens=0)

    if isinstance(usage, dict):
        return TokenUsage(
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
        )

    return TokenUsage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )
