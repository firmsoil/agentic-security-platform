"""Java/Spring stack scanner.

Manifest-only in week 1: emits ``Repository``, ``Container``,
``Artifact[]`` and inferred ``Model`` nodes from ``pom.xml`` or Gradle
build files. ``Tool`` / ``PromptTemplate`` / ``RAGIndex`` / ``MemoryStore``
extraction lands in week 2 via the LLM scanner — annotation- and
DSL-driven Java semantics don't fit a pure-AST pass.
"""

from connectors.github.src.stacks.java.scanner import scan

__all__ = ["scan"]
