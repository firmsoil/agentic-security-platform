"""Manifest parser for Node repositories — package.json.

Returns ``[{name, version}]`` dicts. Walks ``dependencies``,
``devDependencies``, ``peerDependencies``, and ``optionalDependencies``
unioned by package name (later entries win on version-string conflicts).

Workspaces (npm/pnpm/yarn workspace fields) are out of scope for week 1
— a monorepo's root package.json typically lists the workspace dirs but
not their per-package dependencies. The LLM scanner handles those in
week 2.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_DEP_FIELDS = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
)


def parse_package_json(path: Path) -> list[dict[str, str]]:
    """Parse a ``package.json`` into a list of ``{name, version}`` dicts."""
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Unparsable package.json at %s: %s", path, exc)
        return []
    if not isinstance(data, dict):
        log.warning("package.json at %s is not a JSON object", path)
        return []

    by_name: dict[str, str] = {}
    for field in _DEP_FIELDS:
        block = data.get(field) or {}
        if not isinstance(block, dict):
            continue
        for name, version in block.items():
            if isinstance(name, str) and isinstance(version, str):
                by_name[name] = version

    return [{"name": n, "version": v} for n, v in by_name.items()]
