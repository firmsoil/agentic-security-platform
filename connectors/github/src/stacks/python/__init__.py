"""Python stack scanner — the original ASP scanner, now stack-scoped.

Looks for ``requirements.txt`` / ``pyproject.toml`` plus a small set of
Python source files (``tools.py``, ``model.py``, ``memory.py``, ``corpus/``)
that match the bundled ``examples/vulnerable-rag-app`` shape. Repos with
different layouts need a custom profile or the LLM scanner.
"""

from connectors.github.src.stacks.python.scanner import scan

__all__ = ["scan"]
