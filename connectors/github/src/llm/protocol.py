"""Adapter protocol — the interface both Anthropic and OpenAI implementations satisfy.

Per ADR-0005:
- ``extract`` is the first pass (find candidate grounded nodes).
- ``verify`` is the second pass (re-confirm one cited code span).
- Both passes go through the *same* adapter instance — no cross-adapter
  mixing inside a single scan.

Both methods return raw, parsed JSON. Schema validation lives in
``schema.validate_*`` so adapters stay narrowly focused on the
provider-specific call mechanics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AdapterCallResult:
    """One raw response from a structured-output call.

    ``payload`` is the parsed JSON object the model produced under
    schema enforcement. ``model_name`` is what the adapter actually
    used (resolved from env or default), recorded so the cache key
    sees the real model not a placeholder. ``input_tokens`` /
    ``output_tokens`` are best-effort — None when the provider doesn't
    surface them.
    """

    payload: dict[str, Any]
    model_name: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class StructuredExtractor(Protocol):
    """Both adapters implement this. Selected at config time, not per-request."""

    #: Stable identifier for this adapter ("anthropic" / "openai").
    #: Part of the cache key.
    name: str

    #: The model the adapter is configured to use. Part of the cache key.
    model_name: str

    async def extract(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
    ) -> AdapterCallResult:
        """Run pass 1: ask the model for grounded nodes under schema enforcement."""
        ...

    async def verify(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
    ) -> AdapterCallResult:
        """Run pass 2: ask the model to confirm one previously extracted node.

        Same wire-level mechanics as ``extract`` — the difference is in the
        schema and prompts the orchestrator passes. Adapters do not need
        to distinguish the two calls.
        """
        ...


class AdapterError(RuntimeError):
    """Raised when the adapter cannot reach the provider or parse the response."""
