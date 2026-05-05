"""Java SDK package coordinate → Model node properties.

Keys are matched as substrings of ``"<groupId>:<artifactId>"`` so we
catch both ``langchain4j-anthropic`` (artifactId) and
``dev.langchain4j:langchain4j-anthropic`` shapes that come out of
different parsers.
"""

from __future__ import annotations

from typing import Any

SDK_MODEL_MAP: dict[str, dict[str, Any]] = {
    # LangChain4j family
    "langchain4j-anthropic": {
        "provider": "anthropic",
        "name": "claude-sonnet-4-5",
        "version": "latest",
        "hosted": True,
    },
    "langchain4j-open-ai": {
        "provider": "openai",
        "name": "gpt-4o",
        "version": "latest",
        "hosted": True,
    },
    "langchain4j-google-ai-gemini": {
        "provider": "google",
        "name": "gemini-2.0-flash",
        "version": "latest",
        "hosted": True,
    },
    "langchain4j-bedrock": {
        "provider": "aws-bedrock",
        "name": "bedrock-runtime",
        "version": "latest",
        "hosted": True,
    },

    # Spring AI family
    "spring-ai-anthropic-spring-boot-starter": {
        "provider": "anthropic",
        "name": "claude-sonnet-4-5",
        "version": "latest",
        "hosted": True,
    },
    "spring-ai-openai-spring-boot-starter": {
        "provider": "openai",
        "name": "gpt-4o",
        "version": "latest",
        "hosted": True,
    },
    "spring-ai-bedrock-ai-spring-boot-starter": {
        "provider": "aws-bedrock",
        "name": "bedrock-runtime",
        "version": "latest",
        "hosted": True,
    },
    "spring-ai-vertex-ai-gemini-spring-boot-starter": {
        "provider": "google",
        "name": "gemini-2.0-flash",
        "version": "latest",
        "hosted": True,
    },

    # Direct AWS SDK v2 — Bedrock runtime
    "bedrockruntime": {
        "provider": "aws-bedrock",
        "name": "bedrock-runtime",
        "version": "latest",
        "hosted": True,
        "note": "Direct Bedrock SDK; specific model determined at runtime.",
    },
}
