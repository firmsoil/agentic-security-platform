"""Two-pass verifier — re-checks each grounded node against its cited code span.

Per ADR-0005 the verifier:

1. Re-opens ``grounding.file_path`` (rejected if the file is gone).
2. Recomputes the file's SHA-256; rejects if it doesn't match
   ``grounding.file_sha256`` — that means the file changed between
   extraction and verification, so the cited line range is no longer
   reliable.
3. Validates ``[line_start, line_end]`` is within the file.
4. Calls the *same adapter* that did extraction, with a narrowly-
   scoped prompt that re-asserts the claim against the cited span,
   under the verification response schema.
5. Drops any node whose ``verified`` is False.

The verifier never modifies a node — it accepts or rejects. Modifying
would defeat the grounding contract, since the second pass's claim
about what the code says would no longer match the first pass's
file_sha256.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from connectors.github.src.llm.protocol import (
    AdapterError,
    StructuredExtractor,
)
from connectors.github.src.llm.schema import (
    GroundingValidationError,
    VERIFICATION_RESPONSE_SCHEMA,
    validate_verification_response,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerificationOutcome:
    """One verifier verdict for one node."""

    node: dict[str, Any]
    verified: bool
    reason: str
    rejection_reason: str | None = None  # None when verified is True


@dataclass
class VerificationReport:
    """Summary of a verification pass."""

    accepted: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[VerificationOutcome] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.accepted) + len(self.rejected)

    def summary(self) -> str:
        return (
            f"VerificationReport: {len(self.accepted)} accepted, "
            f"{len(self.rejected)} rejected of {self.total} candidates."
        )


# ---------------------------------------------------------------------------
# Verification prompt
# ---------------------------------------------------------------------------

# Lives inline (not in prompts/) because it's tightly coupled to the
# verification *contract*, not the extraction policy. Edits still bump the
# scanner_version cache key — see SCANNER_VERSION in __init__.py.
_VERIFY_SYSTEM_PROMPT = (
    "You verify whether a code span defines a previously claimed ontology "
    "node. You output JSON with two fields: 'verified' (boolean) and "
    "'reason' (one short sentence). Set 'verified' to true ONLY if the "
    "code span clearly defines a node of the claimed *type* — the node "
    "id's suffix is a canonical platform identifier and may be a "
    "reasonable normalization of the source variable or function name "
    "(snake_case, lowercased, leading-underscore preserved if present). "
    "Treat 'PromptTemplate:system_prompt' as valid against a code span "
    "that defines `SYSTEM_PROMPT = \"...\"`. Treat 'Tool:exportData' as "
    "valid against an `@Tool`-annotated `exportData()` method. Reject "
    "only when the cited code does not define a node of the claimed "
    "type at all.\n\n"
    "Type-specific guidance:\n"
    "- Tool: a function or method exposed for invocation by an LLM via "
    "  any framework (LangChain @tool, Spring/LangChain4j @Tool, Vercel "
    "  AI SDK tool() factory, dict literal in a tools=[...] argument, "
    "  module-level *_TOOL or TOOL_SCHEMAS literal).\n"
    "- PromptTemplate: a system prompt or instruction block sent to a "
    "  model — module-level constant, @SystemMessage annotation, "
    "  literal `system:` parameter, literal {role: 'system', ...} entry. "
    "  Including `SYSTEM_PROMPT = \"...\"` in Python.\n"
    "- RAGIndex: a vector store, embedding store, OR a corpus directory "
    "  + loader code that retrieval reads from at inference time. The "
    "  index need NOT be an explicit IndexClient or VectorStore — a "
    "  list-of-documents loaded from a directory and queried by code "
    "  also counts. Examples: `Pinecone(...)`, `Chroma.from_documents`, "
    "  Drizzle pgvector schema, OR a `_load_corpus()` function reading "
    "  `corpus/*.md` files into a list used by a `retrieve()` function.\n"
    "- MemoryStore: any module-level variable or framework object that "
    "  retains state across model calls — module-level dict named "
    "  `_memory` / `session_memory` / `chat_history`, LangChain "
    "  `ConversationBufferMemory`, LangChain4j `ChatMemory`, Drizzle "
    "  `messages` table keyed by chat_id, Redis used for session: keys. "
    "  ACCEPT a MemoryStore claim about a module-level variable whose "
    "  name suggests memory state (`_memory`, `session_memory`, "
    "  `chat_history`, `conversation_history`) EVEN WHEN the cited "
    "  span shows only the variable's initial assignment with seed or "
    "  demo data. The variable's full lifecycle (subsequent writes by "
    "  other functions elsewhere in the file) is intentionally outside "
    "  the cited span — your job is to confirm the variable exists, "
    "  is module-level, and is named consistently with memory storage. "
    "  Reject only if the variable is clearly NOT memory-shaped (e.g. "
    "  a constant config, a function, an enum).\n\n"
    "You do not extract new nodes; you only confirm or reject the one "
    "claim presented."
)


def _build_verify_user_prompt(
    *,
    node: dict[str, Any],
    code_span: str,
) -> str:
    g = node["grounding"]
    return (
        f"Claim: this code span defines a {node['node_type']} node with "
        f"id '{node['id']}'.\n"
        f"Source location: {g['file_path']} lines {g['line_start']}-"
        f"{g['line_end']}.\n"
        f"First-pass evidence: {g['evidence']!r}\n"
        f"Confidence reported: {g['confidence']}\n\n"
        "Code span:\n"
        "```\n"
        f"{code_span}\n"
        "```\n\n"
        "Verify or reject this claim."
    )


# ---------------------------------------------------------------------------
# File checks
# ---------------------------------------------------------------------------


def _read_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_span(path: Path, line_start: int, line_end: int) -> str | None:
    """Return the inclusive line range from ``path``, or None on out-of-bounds."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if line_start > len(lines) or line_end > len(lines):
        return None
    # 1-indexed -> 0-indexed slice.
    return "\n".join(lines[line_start - 1 : line_end])


# ---------------------------------------------------------------------------
# Verifier entry point
# ---------------------------------------------------------------------------


async def verify_nodes(
    *,
    repo_path: Path,
    candidates: list[dict[str, Any]],
    adapter: StructuredExtractor,
) -> VerificationReport:
    """Run the verification pass over a list of grounded-node candidates.

    Static checks (file exists, SHA matches, lines in range) run first
    and reject before any LLM call — they cost nothing and surface the
    most common drift causes loudly. Only candidates that pass static
    checks reach the LLM.
    """
    report = VerificationReport()

    for node in candidates:
        try:
            outcome = await _verify_one(
                repo_path=repo_path,
                node=node,
                adapter=adapter,
            )
        except AdapterError as exc:
            # Adapter failures during verification are different from
            # rejections — a rejection means "the model said no", an
            # adapter failure means "we couldn't ask". Treat both as
            # reject-with-context so the launch demo can't silently
            # accept un-verified nodes.
            outcome = VerificationOutcome(
                node=node,
                verified=False,
                reason="",
                rejection_reason=f"adapter_error: {exc}",
            )

        if outcome.verified:
            report.accepted.append(node)
        else:
            report.rejected.append(outcome)
            log.info(
                "Verifier rejected %s: %s",
                node.get("id", "<unknown>"),
                outcome.rejection_reason or outcome.reason,
            )

    return report


async def _verify_one(
    *,
    repo_path: Path,
    node: dict[str, Any],
    adapter: StructuredExtractor,
) -> VerificationOutcome:
    g = node["grounding"]
    file_path = repo_path / g["file_path"]

    # ---- Static check 1: file exists ----
    if not file_path.is_file():
        return VerificationOutcome(
            node=node, verified=False, reason="",
            rejection_reason=f"file_missing: {g['file_path']!r}",
        )

    # ---- Static check 2: file content unchanged since extraction ----
    actual_sha = _read_file_sha256(file_path)
    if actual_sha != g["file_sha256"]:
        return VerificationOutcome(
            node=node, verified=False, reason="",
            rejection_reason=(
                f"sha_drift: expected {g['file_sha256'][:12]}…, "
                f"got {actual_sha[:12]}…"
            ),
        )

    # ---- Static check 3: line range in bounds ----
    span = _extract_span(file_path, g["line_start"], g["line_end"])
    if span is None:
        return VerificationOutcome(
            node=node, verified=False, reason="",
            rejection_reason=(
                f"line_out_of_range: lines {g['line_start']}-{g['line_end']} "
                f"in {g['file_path']!r}"
            ),
        )

    # ---- LLM check: re-confirm the claim against the span ----
    user_prompt = _build_verify_user_prompt(node=node, code_span=span)
    result = await adapter.verify(
        system_prompt=_VERIFY_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=VERIFICATION_RESPONSE_SCHEMA,
    )

    try:
        verified, reason = validate_verification_response(result.payload)
    except GroundingValidationError as exc:
        return VerificationOutcome(
            node=node, verified=False, reason="",
            rejection_reason=f"malformed_verification_response: {exc}",
        )

    return VerificationOutcome(
        node=node,
        verified=verified,
        reason=reason,
        rejection_reason=None if verified else f"llm_rejected: {reason}",
    )
