"""Anthropic adapter — uses tool-use to enforce the JSON Schema.

The trick: define a single tool whose ``input_schema`` is the
schema we want enforced. Force the model to call that tool by setting
``tool_choice={"type": "tool", "name": ...}``. The tool's input is the
structured response — we never actually execute the tool.

This is the recommended way to get structured output from Claude as of
Sonnet 4.x; ``response_format`` is not supported by Anthropic.
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

_DEFAULT_MODEL = "claude-sonnet-4-5"
_TOOL_NAME = "emit_grounded_response"

# We use the SDK lazily so that import-time costs (and import-time errors
# when the SDK isn't installed) only fire when this adapter is actually
# instantiated.
def _load_anthropic_sdk():  # pragma: no cover — trivial
    try:
        import anthropic  # type: ignore
    except ImportError as exc:
        msg = (
            "AnthropicAdapter requires the 'anthropic' package. "
            "Install it with: pip install anthropic"
        )
        raise AdapterError(msg) from exc
    return anthropic


class AnthropicAdapter:
    """``StructuredExtractor`` implementation backed by Anthropic Messages."""

    name = "anthropic"

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
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") \
            or os.environ.get("ASP_LLM_API_KEY")
        if not self._api_key:
            msg = (
                "AnthropicAdapter requires an API key. Set "
                "ANTHROPIC_API_KEY or ASP_LLM_API_KEY in the environment, "
                "or pass api_key= explicitly."
            )
            raise AdapterError(msg)
        self._max_tokens = max_tokens
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            anthropic = _load_anthropic_sdk()
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
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
        tool_def = {
            "name": _TOOL_NAME,
            "description": (
                "Emit the structured response. The tool's input IS the "
                "response payload — the platform enforces the schema by "
                "rejecting non-conforming tool inputs."
            ),
            "input_schema": schema,
        }

        try:
            response = await client.messages.create(
                model=self.model_name,
                max_tokens=self._max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[tool_def],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"Anthropic API call failed: {exc}"
            raise AdapterError(msg) from exc

        # Find the tool_use block. With ``tool_choice`` forcing this tool,
        # there must be exactly one. Anything else is a provider bug we
        # surface loudly rather than silently fall back.
        tool_uses = [
            block for block in response.content
            if getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == _TOOL_NAME
        ]
        if len(tool_uses) != 1:
            msg = (
                f"Expected exactly one tool_use block named "
                f"{_TOOL_NAME!r}; got {len(tool_uses)}. "
                f"Stop reason: {getattr(response, 'stop_reason', 'unknown')}"
            )
            raise AdapterError(msg)

        payload = tool_uses[0].input
        if not isinstance(payload, dict):
            # Anthropic SDK should already parse JSON, but guard anyway.
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError) as exc:
                msg = f"Tool input was not a JSON object: {payload!r}"
                raise AdapterError(msg) from exc

        usage = getattr(response, "usage", None)
        return AdapterCallResult(
            payload=payload,
            model_name=self.model_name,
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
        )
