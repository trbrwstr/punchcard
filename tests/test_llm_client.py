from types import SimpleNamespace

import pytest

from punchcard.backend.llm import (
    ANTHROPIC_TRANSLATION_MODEL,
    AnthropicTranslationClient,
    LLMClientError,
    LLMSettings,
    USER_PROMPT_TEMPLATE,
)


class FakeMessagesClient:
    def __init__(self) -> None:
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(text="def main_para():\n    print('HELLO')\n")],
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        )


def test_translate_paragraph_uses_injected_client_and_returns_metadata() -> None:
    fake = FakeMessagesClient()
    client = AnthropicTranslationClient(
        settings=LLMSettings(ANTHROPIC_API_KEY=None, PUNCHCARD_TEST_MODE=True),
        messages_client=fake,
    )

    result = client.translate_paragraph(
        target_language="Python",
        paragraph_name="MAIN-PARA",
        cobol_source="DISPLAY 'HELLO'.",
        complexity_score=2,
        suggested_function_name="main_para",
    )

    assert result.translated_code == "def main_para():\n    print('HELLO')"
    assert result.model_name == ANTHROPIC_TRANSLATION_MODEL
    assert result.token_usage.input_tokens == 11
    assert result.token_usage.output_tokens == 7
    assert fake.request["model"] == ANTHROPIC_TRANSLATION_MODEL
    assert fake.request["messages"][0]["role"] == "user"
    assert "MAIN-PARA" in fake.request["messages"][0]["content"]
    assert "DISPLAY 'HELLO'." in fake.request["messages"][0]["content"]


def test_test_mode_requires_injected_messages_client() -> None:
    with pytest.raises(LLMClientError, match="PUNCHCARD_TEST_MODE"):
        AnthropicTranslationClient(
            settings=LLMSettings(ANTHROPIC_API_KEY=None, PUNCHCARD_TEST_MODE=True)
        )


def test_user_prompt_template_accepts_required_fields() -> None:
    prompt = USER_PROMPT_TEMPLATE.format(
        target_language="TypeScript",
        paragraph_name="CALC-TAX",
        suggested_function_name="calculateTax",
        complexity_score=5,
        cobol_source="MOVE 1 TO TAX.",
    )

    assert "TypeScript" in prompt
    assert "CALC-TAX" in prompt
    assert "calculateTax" in prompt
    assert "MOVE 1 TO TAX." in prompt
