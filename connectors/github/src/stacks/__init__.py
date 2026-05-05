"""Per-stack scanners.

Each subpackage exposes ``scan(repo_path) -> ScanResult`` over the shared
``connectors.github.src.types.ScanResult`` shape, so the dispatcher can
treat them uniformly.
"""
