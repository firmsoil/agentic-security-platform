"""Agent protocols.

The three agent types (Red, Blue, Green) are defined as protocols here.
Concrete LangGraph/Temporal implementations land in `asp_agents/*` and
implement these. Keeping the protocols in core means:
  - Core can describe the tri-agent model without importing LangGraph
  - Adapters can mock agents for isolated testing
  - Future agent frameworks (CrewAI, Agent SDK, ...) can implement the
    same protocol without touching the rest of the platform
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID


class AgentKind(StrEnum):
    RED = "red"
    BLUE = "blue"
    GREEN = "green"


@dataclass(frozen=True)
class AgentContext:
    """Immutable context passed into every agent invocation.

    This is the *only* thing an agent should close over. Anything mutable
    belongs in the agent's state machine (LangGraph state), not here.
    """

    run_id: UUID
    trace_id: str
    started_at: datetime
    ontology_version: str
    # Scope limits — enforced at adapter layer. Declared here so every agent
    # is forced to think about what it's allowed to touch.
    allowed_node_types: frozenset[str] = field(default_factory=frozenset)
    allowed_edge_types: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class AgentResult:
    """Structured result from an agent run. Never free-form text."""

    run_id: UUID
    kind: AgentKind
    findings: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@runtime_checkable
class RedAgent(Protocol):
    """Offensive: proposes attack paths on the graph."""

    async def run(self, ctx: AgentContext) -> AgentResult: ...


@runtime_checkable
class BlueAgent(Protocol):
    """Detective: correlates runtime events to graph-derived risks."""

    async def run(self, ctx: AgentContext) -> AgentResult: ...


@runtime_checkable
class GreenAgent(Protocol):
    """Remediator: generates fixes. Writes go through human approval."""

    async def run(self, ctx: AgentContext) -> AgentResult: ...
