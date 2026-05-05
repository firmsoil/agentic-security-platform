"""OpenAI adapter — uses Structured Outputs to enforce the JSON Schema.

OpenAI exposes ``response_format={"type": "json_schema", ...}`` which
guarantees the model returns JSON matching the schema (or refuses with a
documented refusal mechanism). We use the chat-completions API since it's
the most widely available across model versions.

Structured Outputs has constraints the Anthropic tool-use route doesn't:
- ``additionalProperties`` must be set on every object (already true in
  ``schema.py``).
- ``required`` must list every property (the schema in ``schema.py``
  follows this; if you add an optional field, you'll need a wrapper here
  to translate).
- Top-level type must be ``object`` (already true).

If a future schema change breaks these constraints, the adapter will
fail loudly at first call — that's the right behaviour.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from connectors.github.src.llm.protocol import (
    AdapterCallResult,
    AdapterError,
)

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-2024-08-06"  # First Structured-Outputs-GA model.
_SCHEMA_NAME = "grounded_response"


def _load_openai_sdk():  # pragma: no cover — trivial
    try:
        import openai  # type: ignore
    except ImportError as exc:
        msg = (
            "OpenAIAdapter requires the 'openai' package. "
            "Install it with: pip install openai"
        )
        raise AdapterError(msg) from exc
    return openai


class OpenAIAdapter:
    """``StructuredExtractor`` implementation backed by OpenAI chat-completions."""

    name = "openai"

    def __init__(
        self,
        *,
        model_name: str | None = None,
        api_key: str | None = None,
        max_tokens: int = 4096,
    ) -> None:
        self.model_name = model_name or os.environ.get(
            "ASP_LLM_MODEL", _DEFAULT_MODEL,
        )
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY") \
            or os.environ.get("ASP_LLM_API_KEY")
        if not self._api_key:
            msg = (
                "OpenAIAdapter requires an API key. Set OPENAI_API_KEY or "
                "ASP_LLM_API_KEY in the environment, or pass api_key= "
                "explicitly."
            )
            raise AdapterError(msg)
        self._max_tokens = max_tokens
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            openai = _load_openai_sdk()
            self._client = openai.AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def extract(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
    ) -> AdapterCallResult:
        return await self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
        )

    async def verify(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
    ) -> AdapterCallResult:
        return await self._call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
        )

    async def _call(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
    ) -> AdapterCallResult:
        client = self._get_client()
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": _SCHEMA_NAME,
                "schema": schema,
                "strict": True,
            },
        }
        try:
            response = await client.chat.completions.create(
                model=self.model_name,
                max_tokens=self._max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=response_format,
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"OpenAI API call failed: {exc}"
            raise AdapterError(msg) from exc

        if not response.choices:
            msg = "OpenAI response had no choices"
            raise AdapterError(msg)

        choice = response.choices[0]
        # Structured Outputs may produce a refusal instead of content.
        # Surface the refusal as an adapter error rather than silently
        # treating it as empty.
        message = choice.message
        if getattr(message, "refusal", None):
            msg = f"OpenAI refused: {message.refusal}"
            raise AdapterError(msg)

        content = message.content
        if not isinstance(content, str) or not content:
            msg = (
                "OpenAI response missing content. "
                f"finish_reason={choice.finish_reason!r}"
            )
            raise AdapterError(msg)

        try:
            payload = json.loads(content)
        except (TypeError, ValueError) as exc:
            msg = f"OpenAI returned non-JSON content: {content!r}"
            raise AdapterError(msg) from exc
        if not isinstance(payload, dict):
            msg = f"OpenAI returned a non-object JSON value: {payload!r}"
            raise AdapterError(msg)

        usage = response.usage
        return AdapterCallResult(
            payload=payload,
            model_name=self.model_name,
            input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        )
