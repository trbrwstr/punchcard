"""Anthropic-backed translation boundary.

The production client is injectable so tests and CI never need to touch the
real Anthropic API. If no client is supplied, construction is lazy and isolated
here instead of leaking SDK details across the codebase.
"""

from __future__ import annotations

import inspect
from typing import Any, Protocol


class AnthropicMessagesClient(Protocol):
    """Small protocol for the ``client.messages.create`` method we use."""

    def create(self, **kwargs: Any) -> Any:  # pragma: no cover - protocol only
        """Create a model message."""


class AnthropicTranslator:
    """Translate rendered prompts through Anthropic with dependency injection."""

    def __init__(self, *, client: Any | None = None, model: str = "claude-3-5-sonnet-latest") -> None:
        self._client = client
        self.model = model

    async def translate(self, prompt: str) -> str:
        """Send ``prompt`` to Anthropic and return plain text."""

        client = self._client or self._build_client()
        create = client.messages.create
        response = create(
            model=self.model,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        if inspect.isawaitable(response):
            response = await response
        return _extract_text(response)

    def _build_client(self) -> Any:
        import anthropic

        return anthropic.Anthropic()


def _extract_text(response: Any) -> str:
    """Extract text from Anthropic SDK responses and simple test doubles."""

    if isinstance(response, str):
        return response

    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text is None and isinstance(item, dict):
                text = item.get("text")
            if text:
                parts.append(str(text))
        if parts:
            return "\n".join(parts)

    text = getattr(response, "text", None)
    if text is not None:
        return str(text)

    return str(response)
