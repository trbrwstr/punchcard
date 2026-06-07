from types import SimpleNamespace

import pytest

from punchcard.backend.llm import (
    ANTHROPIC_TRANSLATION_MODEL,
    USER_PROMPT_TEMPLATE,
    AnthropicLLMClient,
    AnthropicTranslationClient,
    LLMClientError,
    LLMSettings,
    MockLLMClient,
    get_llm_client,
    suggested_function_name,
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


def test_get_llm_client_defaults_to_mock_without_api_key() -> None:
    client = get_llm_client(LLMSettings(ANTHROPIC_API_KEY=None, PUNCHCARD_TEST_MODE=False))
    assert isinstance(client, MockLLMClient)


def test_get_llm_client_stays_mock_in_test_mode_even_with_key() -> None:
    client = get_llm_client(LLMSettings(ANTHROPIC_API_KEY="sk-test", PUNCHCARD_TEST_MODE=True))
    assert isinstance(client, MockLLMClient)


def test_get_llm_client_uses_real_client_when_key_present_outside_tests(monkeypatch) -> None:
    # The pytest env var would otherwise force mock mode; clear it to exercise
    # the production path. No network call happens at construction time.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("PUNCHCARD_TEST_MODE", "false")

    assert isinstance(get_llm_client(), AnthropicLLMClient)


def test_suggested_function_name_snake_cases_paragraph() -> None:
    assert suggested_function_name("CALCULATE-PAY") == "calculate_pay"
    assert suggested_function_name("100-INIT") == "p_100_init"


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
