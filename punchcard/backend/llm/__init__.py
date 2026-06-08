"""LLM translation helpers for Punchcard.

The API depends on this tiny abstraction instead of a vendor SDK directly. That
keeps the current MVP safe and testable while leaving a clean seam for a real
provider. ``get_llm_client`` returns the offline :class:`MockLLMClient` unless an
``ANTHROPIC_API_KEY`` is configured and the process is not under test — only then
does proprietary COBOL leave the box, and only because someone deliberately set
the key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from punchcard.backend.llm.client import (
    ANTHROPIC_TRANSLATION_MODEL,
    AnthropicTranslationClient,
    LLMClientError,
    LLMSettings,
    TokenUsage,
)
from punchcard.backend.llm.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from punchcard.backend.parser.complexity import complexity_for_source

DEFAULT_TARGET_LANGUAGE = "Python"


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """Normalized result returned by any paragraph translation client.

    Structural confidence is owned by the review layer (see
    :func:`punchcard.backend.llm.confidence.score_paragraph`), so a translation
    result carries only the produced code and any flags the translator wants to
    attach to it.
    """

    translated_text: str
    risk_flags: tuple[str, ...] = ()


class LLMClient(Protocol):
    """Minimal contract for translating one COBOL paragraph at a time."""

    def translate_paragraph(self, *, name: str, source: str) -> TranslationResult:
        """Return a proposed rewrite for a single paragraph."""


class MockLLMClient:
    """Deterministic local translator used until a real provider is configured.

    This intentionally does not call the network. In cybersecurity terms, it is
    the MVP's fence around proprietary COBOL: no source leaves the process unless
    a real client is deliberately plugged in. The output is deliberately simple,
    but it still follows the requested target language so local demos do not
    produce misleading artifacts.
    """

    def __init__(self, *, target_language: str = DEFAULT_TARGET_LANGUAGE) -> None:
        self.target_language = target_language.strip().lower()

    def translate_paragraph(self, *, name: str, source: str) -> TranslationResult:
        """Produce a readable local pseudocode rewrite for the target language."""

        body = source.strip() or "*> empty paragraph"
        if self.target_language == "java":
            translated = (
                f"// Proposed Java rewrite for COBOL paragraph {name}\n"
                "public Object run(Object context) {\n"
                "    // Original COBOL:\n"
                f"{_indent_as_comment(body, prefix='//')}\n"
                "    return context;\n"
                "}"
            )
        else:
            translated = (
                f"# Proposed Python rewrite for COBOL paragraph {name}\n"
                "def run(context):\n"
                "    # Original COBOL:\n"
                f"{_indent_as_comment(body, prefix='#')}\n"
                "    return context"
            )
        return TranslationResult(translated_text=translated, risk_flags=("MOCK_TRANSLATION",))


class AnthropicLLMClient:
    """Adapt :class:`AnthropicTranslationClient` to the ``(name, source)`` contract.

    The route layer only knows a paragraph's name and source text, so this
    adapter fills in the richer prompt inputs the real client expects: a target
    language, a cyclomatic complexity estimate, and a suggested function name.
    """

    def __init__(
        self,
        *,
        client: AnthropicTranslationClient | None = None,
        settings: LLMSettings | None = None,
        target_language: str = DEFAULT_TARGET_LANGUAGE,
    ) -> None:
        self._client = client or AnthropicTranslationClient(settings=settings)
        self.target_language = target_language

    def translate_paragraph(self, *, name: str, source: str) -> TranslationResult:
        result = self._client.translate_paragraph(
            target_language=self.target_language,
            paragraph_name=name,
            cobol_source=source,
            complexity_score=complexity_for_source(source),
            suggested_function_name=suggested_function_name(name),
        )
        return TranslationResult(translated_text=result.translated_code, risk_flags=("LLM_TRANSLATION",))


def get_llm_client(
    settings: LLMSettings | None = None,
    *,
    target_language: str = DEFAULT_TARGET_LANGUAGE,
) -> LLMClient:
    """Return the configured LLM client.

    Falls back to the offline :class:`MockLLMClient` whenever real calls are
    blocked (tests) or no API key is present, so CI and local runs never touch
    the network by accident. ``target_language`` configures both the real client
    and the deterministic local mock output.
    """

    settings = settings or LLMSettings()
    if settings.blocks_real_api_calls or settings.anthropic_api_key is None:
        return MockLLMClient(target_language=target_language)
    return AnthropicLLMClient(settings=settings, target_language=target_language)


def suggested_function_name(paragraph_name: str) -> str:
    """Derive a snake_case function name from a COBOL paragraph name."""

    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", paragraph_name.strip().lower()).strip("_")
    if not cleaned:
        return "run"
    if cleaned[0].isdigit():
        cleaned = f"p_{cleaned}"
    return cleaned


def _indent_as_comment(text: str, *, prefix: str) -> str:
    """Render source lines as indented comments inside generated code."""

    return "\n".join(f"    {prefix} {line}" for line in text.splitlines())


AnthropicLLMTranslationClient = AnthropicTranslationClient

__all__ = [
    "ANTHROPIC_TRANSLATION_MODEL",
    "AnthropicLLMClient",
    "AnthropicLLMTranslationClient",
    "AnthropicTranslationClient",
    "LLMClient",
    "LLMClientError",
    "LLMSettings",
    "MockLLMClient",
    "SYSTEM_PROMPT",
    "TokenUsage",
    "TranslationResult",
    "USER_PROMPT_TEMPLATE",
    "get_llm_client",
    "suggested_function_name",
]
