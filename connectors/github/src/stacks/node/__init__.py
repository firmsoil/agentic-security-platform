"""Node/TypeScript stack scanner.

Manifest-only in week 1 — emits ``Repository``, ``Container``,
``Artifact[]`` and inferred ``Model`` nodes from ``package.json``. Source
extraction (TS/JS AST) is the LLM scanner's job in week 2.
"""

from connectors.github.src.stacks.node.scanner import scan

__all__ = ["scan"]
