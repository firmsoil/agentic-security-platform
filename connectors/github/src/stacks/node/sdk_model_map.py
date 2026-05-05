"""Node SDK package name → Model node properties.

Keys are matched as exact package names — npm names are stable and
namespaced, so substring matching would over-trigger on common prefixes
like ``langchain``.
"""

from __future__ import annotations

from typing import Any

SDK_MODEL_MAP: dict[str, dict[str, Any]] = {
    # Direct SDKs
    "@anthropic-ai/sdk": {
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
    "@google/generative-ai": {
        "provider": "google",
        "name": "gemini-2.0-flash",
        "version": "latest",
        "hosted": True,
    },
    "@mistralai/mistralai": {
        "provider": "mistral",
        "name": "mistral-large-latest",
        "version": "latest",
        "hosted": True,
    },

    # LangChain JS family
    "langchain": {
        "provider": "langchain-js",
        "name": "router",
        "version": "latest",
        "hosted": True,
        "note": "Provider determined at runtime; static scan emits a placeholder.",
    },
    "@langchain/anthropic": {
        "provider": "anthropic",
        "name": "claude-sonnet-4-5",
        "version": "latest",
        "hosted": True,
    },
    "@langchain/openai": {
        "provider": "openai",
        "name": "gpt-4o",
        "version": "latest",
        "hosted": True,
    },
    "@langchain/google-genai": {
        "provider": "google",
        "name": "gemini-2.0-flash",
        "version": "latest",
        "hosted": True,
    },
    "@langchain/aws": {
        "provider": "aws-bedrock",
        "name": "bedrock-runtime",
        "version": "latest",
        "hosted": True,
    },

    # Vercel AI SDK
    "ai": {
        "provider": "vercel-ai",
        "name": "router",
        "version": "latest",
        "hosted": True,
        "note": "Provider determined at runtime via @ai-sdk/* providers.",
    },
    "@ai-sdk/anthropic": {
        "provider": "anthropic",
        "name": "claude-sonnet-4-5",
        "version": "latest",
        "hosted": True,
    },
    "@ai-sdk/openai": {
        "provider": "openai",
        "name": "gpt-4o",
        "version": "latest",
        "hosted": True,
    },
    "@ai-sdk/google": {
        "provider": "google",
        "name": "gemini-2.0-flash",
        "version": "latest",
        "hosted": True,
    },

    # AWS SDK v3 — Bedrock runtime
    "@aws-sdk/client-bedrock-runtime": {
        "provider": "aws-bedrock",
        "name": "bedrock-runtime",
        "version": "latest",
        "hosted": True,
        "note": "Direct Bedrock SDK; specific model determined at runtime.",
    },
}
