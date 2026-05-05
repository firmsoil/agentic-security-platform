"""Back-compat re-exports of the Python-stack parsers.

The Python parsers moved under ``connectors.github.src.stacks.python.parsers``
when the connector became multi-stack. This module preserves the original
import surface so ``connectors/github/tests/test_parsers.py`` and any
external callers keep working without changes.

New code should import from the per-stack module directly.
"""

from connectors.github.src.stacks.python.parsers import (  # noqa: F401
    parse_corpus,
    parse_memory_store,
    parse_prompt_template,
    parse_requirements,
    parse_tool_schemas,
)

__all__ = [
    "parse_corpus",
    "parse_memory_store",
    "parse_prompt_template",
    "parse_requirements",
    "parse_tool_schemas",
]
