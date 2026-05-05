# vulnerable-rag-app

> ⚠️ **Vulnerable by design.** This is a security-education artifact. It contains
> intentional vulnerabilities — prompt injection through RAG, missing output
> validation, an over-privileged tool, weak system prompt. **Do not deploy.**
> **Do not connect to real cloud credentials.** Run only on your local machine
> against the bundled corpus.

A small RAG-backed chatbot used as the demo target for the Agentic Security
Platform. Its purpose is to make the OWASP Agentic Top 10 attack patterns
concrete, so that the platform's graph can find the attack paths *before*
they execute and the platform's findings can be validated by running the
attack.

## Why this exists

Security platforms claim to detect AI-specific attack paths. To demonstrate
that claim end-to-end, you need a target that actually has those paths.
This app provides one. It corresponds to a specific path in the platform's
ontology:

```
RAG corpus document  --PROMPT_INJECTABLE_INTO-->  Prompt
                                                     |
                                                  USES_PROMPT
                                                     v
                                                   Model  --CALLS_TOOL-->  export_data Tool
                                                                                |
                                                                                v
                                                                          on-disk file
                                                                          ("exfiltrated" data)
```

The platform should find this path by static graph analysis of the app's
repository. Running the attack confirms the platform's prediction.

## What is intentionally wrong

Five vulnerabilities, documented inline in the code:

1. **No input filtering on retrieved documents.** Corpus content is concatenated
   into the prompt verbatim. This is the prompt-injection root cause — see
   OWASP LLM01 (2025) / ASI-01 (2026).

2. **Weak system prompt.** Does not instruct the model to ignore instructions
   embedded in retrieved content. A real production system would have an
   "untrusted content" boundary in the prompt or use a structured-content
   approach like Anthropic's [content blocks for untrusted input].

3. **No output validation.** Whatever the model says to do, the app does. No
   guardrail (NeMo Guardrails, structured output validation, LLM-as-judge)
   sits between the model and the tool dispatcher. See OWASP LLM05 (2025).

4. **Over-privileged tool.** `export_data` writes arbitrary in-memory state to
   disk with no caller authorization, no scope check, no rate limit, and no
   audit. See OWASP LLM06 (2025) / ASI-02 (2026).

5. **Memory accumulation across requests.** Conversation history accumulates
   in process memory across requests. This is what gets exfiltrated when the
   attack fires.

## What is intentionally safe (and why)

This is a security-education artifact, not a turnkey attack tool. Several
things have been deliberately constrained so that this code cannot be lifted
and used against real targets:

- The `export_data` tool writes to a fixed local path (`./exfil/`). It does
  not accept arbitrary URLs or cloud destinations. Removing this constraint
  is the line between "vulnerable example" and "exfiltration kit"; we keep
  the constraint.
- The bundled corpus document containing the prompt injection is clearly
  labeled as such. The injection text is the OWASP-canonical pattern, not a
  novel evasion technique.
- The app does not load any real credentials, does not call any real cloud
  APIs, and does not accept production model providers without explicit
  configuration.
- All "sensitive" memory contents are synthetic data generated at startup —
  fake user records, fake account numbers — not anything resembling real PII.

## Setup

```bash
cd examples/vulnerable-rag-app
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set ANTHROPIC_API_KEY in your environment, or leave unset to use the
# built-in deterministic mock model (good for offline demo rehearsal).
export ANTHROPIC_API_KEY=sk-ant-...

uvicorn app:app --reload --port 8001
```

Then in another terminal:

```bash
# Benign question — should work normally.
curl -s http://localhost:8001/chat -H "content-type: application/json" \
  -d '{"message": "What is our refund policy?"}' | jq

# The attack — sends a question whose retrieved context contains an injection.
python attack.py
```

## File map

```
app.py              # FastAPI app — the vulnerable surface
rag.py              # Retriever (deliberately simple keyword overlap)
model.py            # Model invocation (Anthropic SDK, with a deterministic mock fallback)
tools.py            # The export_data tool — over-privileged by design
memory.py           # In-process session memory (accumulates state)
attack.py           # Reproducer for the prompt injection → exfil path
corpus/             # RAG corpus, including the injected document
  refund-policy.md
  shipping-faq.md
  injected-doc.md   # contains the prompt injection — labeled in the file
exfil/              # Created at runtime by the export_data tool. Gitignored.
tests/              # Tests that demonstrate the attack works
```

## How to use this with the platform

Once you have the platform running:

```bash
# From the platform repo root, run the seed script.
# Since the 'asp scan-repo' connector is not fully implemented in v0.1,
# this script creates both the base application components (Model, Tool,
# RAGIndex) AND the security-semantic edges (PROMPT_INJECTABLE_INTO, etc.)
# so the graph correctly reflects the attack paths.

uv run python scripts/seed_graph.py \
    --neo4j-uri bolt://localhost:7687 \
    --neo4j-user neo4j \
    --neo4j-password changeme
```

Open the platform's frontend at `localhost:3000/graph` and you'll see the
attack path highlighted, mapped to OWASP ASI-01 + LLM06 + ASI-02.

## License

Apache-2.0, same as the parent repo.
