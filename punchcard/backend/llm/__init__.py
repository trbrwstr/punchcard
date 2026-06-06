"""LLM review helpers for Punchcard."""

from punchcard.backend.llm.client import (
    ANTHROPIC_TRANSLATION_MODEL,
    AnthropicTranslationClient,
    LLMClientError,
    LLMSettings,
    TokenUsage,
    TranslationResult,
)
from punchcard.backend.llm.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

AnthropicLLMClient = AnthropicTranslationClient

__all__ = [
    "ANTHROPIC_TRANSLATION_MODEL",
    "AnthropicLLMClient",
    "AnthropicTranslationClient",
    "LLMClientError",
    "LLMSettings",
    "SYSTEM_PROMPT",
    "TokenUsage",
    "TranslationResult",
    "USER_PROMPT_TEMPLATE",
]
"""LLM translation helpers for Punchcard.

The API depends on this tiny abstraction instead of a vendor SDK directly. That
keeps the current MVP safe and testable while leaving a clean seam for a real
provider later, when users explicitly approve sending legacy code off-box.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """Normalized result returned by any paragraph translation client."""

    translated_text: str
    confidence_score: float
    risk_flags: tuple[str, ...] = ()


class LLMClient(Protocol):
    """Minimal contract for translating one COBOL paragraph at a time."""

    def translate_paragraph(self, *, name: str, source: str) -> TranslationResult:
        """Return a proposed rewrite for a single paragraph."""


class MockLLMClient:
    """Deterministic local translator used until a real provider is configured.

    This intentionally does not call the network. In cybersecurity terms, it is
    the MVP's fence around proprietary COBOL: no source leaves the process unless
    a future client is deliberately plugged in.
    """

    def translate_paragraph(self, *, name: str, source: str) -> TranslationResult:
        """Produce a readable Python-style pseudocode rewrite."""

        body = source.strip() or "*> empty paragraph"
        translated = (
            f"# Proposed Python rewrite for COBOL paragraph {name}\n"
            "def run(context):\n"
            f"    # Original COBOL:\n"
            f"{_indent_as_comment(body)}\n"
            "    return context"
        )
        return TranslationResult(translated_text=translated, confidence_score=0.72, risk_flags=("MOCK_TRANSLATION",))


def get_llm_client() -> LLMClient:
    """Return the configured LLM client.

    The first implementation is mocked by design. A real client can be selected
    here later from settings without changing API handlers.
    """

    return MockLLMClient()


def _indent_as_comment(text: str) -> str:
    """Render source lines as indented comments inside generated code."""

    return "\n".join(f"    # {line}" for line in text.splitlines())
