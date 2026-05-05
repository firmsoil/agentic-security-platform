"""ASP GitHub Connector — static repository scanner.

Scans a local repository checkout and produces ontology-typed node and edge
dicts for the Security Graph.  The connector is intentionally I/O-free in its
core parsers; side effects live in ``writer`` and ``__main__``.
"""
