# asp-agents

LangGraph + Temporal implementations of the Red / Blue / Green agents.

## v0.1 status

This package currently ships only:
- Package scaffold (directories, `pyproject.toml`, empty `__init__.py` files)
- Agent protocols re-exported from `asp-core` for convenience

The actual LangGraph graphs and Temporal workflows land in **Phase 2** (weeks 14–26 of the roadmap). That phase introduces:
- Red Agent: offensive graph-traversal attack-path proposer
- Blue Agent: runtime correlator tying OTel spans back to graph nodes
- Green Agent: remediation workflow with human-in-the-loop PR approval via Temporal

## Why not land agents in week one

See ADR-0001. Building agents on top of an ontology that isn't yet stable produces throwaway code. The week-one goal is an ontology and an API contract; agents come after.
