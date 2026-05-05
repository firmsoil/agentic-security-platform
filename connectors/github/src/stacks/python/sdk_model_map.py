"""Python SDK package name → Model node properties.

Extended in week 1 to cover the most common ways a Python AI app reaches a
foundation model. ``litellm`` and ``boto3`` are heuristic — both are
unspecific by themselves (``boto3`` is generic AWS), so the scanner only
emits a Model node for them when paired with a known provider hint
elsewhere in the repo. For the manifest-only pass we accept the false
positive rather than miss the dependency.
"""

from __future__ import annotations

from typing import Any

SDK_MODEL_MAP: dict[str, dict[str, Any]] = {
    "anthropic": {
        "provider": "anthropic",
        "name": "claude-sonnet-4-5",
        "version": "latest",
        "hosted": True,
    },
    "openai": {
        "provider": "openai",
        "name": "gpt-4o",
        "version": "latest",
        "hosted": True,
    },
    "google-generativeai": {
        "provider": "google",
        "name": "gemini-2.0-flash",
        "version": "latest",
        "hosted": True,
    },
    "mistralai": {
        "provider": "mistral",
        "name": "mistral-large-latest",
        "version": "latest",
        "hosted": True,
    },
    "litellm": {
        "provider": "litellm",
        "name": "router",
        "version": "latest",
        "hosted": True,
        "note": "Provider/model determined at runtime; static scan emits a placeholder.",
    },
    "boto3": {
        "provider": "aws-bedrock",
        "name": "bedrock-runtime",
        "version": "latest",
        "hosted": True,
        "note": "boto3 is generic; this is a heuristic guess that may produce false positives.",
    },
}
