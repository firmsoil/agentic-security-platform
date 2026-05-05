"""Vulnerable RAG application — FastAPI surface.

The vulnerabilities are intentional and documented in README.md. This file
is the seam where they compose:

  - /chat receives a user question
  - rag.retrieve() pulls untrusted documents and concatenates them into the
    model context (vulnerability #1: no input filtering)
  - model.invoke_model() calls the LLM with a weak system prompt
    (vulnerability #2)
  - if the model emits tool calls, model.execute_tool_calls() runs them with
    no validation (vulnerability #3)
  - the export_data tool dumps memory to disk with no authorization
    (vulnerability #4)
  - memory.remember() accumulates state across requests (vulnerability #5)
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from memory import remember
from model import execute_tool_calls, invoke_model, render_audit
from rag import retrieve

app = FastAPI(
    title="Vulnerable RAG Demo App",
    description=(
        "Vulnerable-by-design demo target for the Agentic Security Platform. "
        "Do not deploy. See README.md."
    ),
    version="0.1.0",
)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    # Diagnostic fields. A real app would not expose these. They are here so
    # the demo can show what the model did and what tools fired.
    retrieved_documents: list[str]
    tool_calls: list[dict]
    tool_results: list[dict]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    # Track the question in conversation memory.
    remember("user", req.message)

    # Retrieve relevant context from the corpus. No filtering or sanitization.
    documents = retrieve(req.message, k=2)
    retrieved_text = "\n\n".join(
        f"### {d.name}\n{d.content}" for d in documents
    )

    # Invoke the model with the user's question and the retrieved context.
    response = invoke_model(req.message, retrieved_text)

    # Run any tool calls the model emitted. No validation step here.
    tool_results = execute_tool_calls(response.tool_calls)

    # Track the assistant's reply in conversation memory.
    remember("assistant", response.text)

    return ChatResponse(
        reply=response.text,
        retrieved_documents=[d.name for d in documents],
        tool_calls=response.tool_calls,
        tool_results=tool_results,
    )


@app.get("/_debug/trace")
def trace() -> dict:
    """Demo-only endpoint exposing the last interaction in detail.

    Real apps should not expose internal trace data. This is here to make
    the demo's "before and after" visible without rerunning the request.
    """
    # Implementation: in a real app you'd thread a span id through. For the
    # demo we just return the most recent rememberd entries.
    from memory import _memory  # noqa: PLC0415 — diagnostic only
    return {"recent": _memory["conversation_history"][-6:]}
