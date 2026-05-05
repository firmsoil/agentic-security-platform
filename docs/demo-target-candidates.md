# Demo target candidates — Java/Spring × 3, Node/TS × 3

> **Decided 2026-04-26: J1 + N1 locked in.**
> Java target: `langchain4j/langchain4j-examples` —
> `customer-support-agent-example`. Profile stub at
> `targets/customer-support-agent.yaml`.
> Node target: `vercel-labs/ai-sdk-preview-rag`. Profile stub at
> `targets/ai-sdk-preview-rag.yaml`.
>
> **Web verification 2026-04-28** (task #16 partial — license byte-read
> still owed, but enough to author preliminary profiles):
> - J1: Apache-2.0 (LangChain4j org default; the examples repo
>   inherits). Spring Boot multi-module Maven project, parent POM
>   version 1.8.0-beta15. Confirmed `BookingTools` component with
>   `@Tool`-annotated `getBookingDetails(bookingNumber, customerName,
>   customerSurname)` method. Integration test fixture references
>   booking `MS-777` and customer `John Doe`.
> - N1: LICENSE file present (Vercel Inc., 2024). Next.js + Vercel AI
>   SDK + DrizzleORM + PostgreSQL with pgvector. Confirmed two tools
>   in the chat route: `getInformation` (RAG retrieval) and
>   `addResource` (writes to embedded knowledge base — memory-
>   poisoning surface, lights up `MEMORY_POISONABLE_BY` for free).
>
> Final license byte-check + source-file count remain a 5-minute
> task for week 3 before merge.

End-of-week-1 deliverable for the LLM-scanner MVP. Originally pick **two**
from this list (one per stack); decision recorded above. The chosen targets
get hand-authored `targets/<repo>.yaml` profiles in week 3 and become the
multi-stack story in the launch demo. The other four candidates remain on
file as fallbacks in case verification surfaces a blocker.

**Status note:** I deep-verified one repo before GitHub rate-limited the
research session. The other five are described from search results plus
training knowledge of these specific projects. License, file count, and
exact dependency shape need a quick confirmation pass before final pick
— budgeted as a 30-minute task at the start of week 3, flagged in the
"verify before commit" column below.

## Selection criteria (for reference)

- Public, **Apache-2.0 or MIT** (check the LICENSE file).
- **< 50 source files** at the repo root or under `src/`.
- Real **RAG-with-tools shape**: model invocation, at least one tool the
  model can call, a corpus or vector index, ideally session/conversation
  memory.
- An **attack-path shape** the existing query families catch — prompt
  injection via corpus, tool abuse, memory poisoning, or all three. We
  may fork the chosen repo to add the canonical injection pattern (one
  corpus document containing `IGNORE PREVIOUS INSTRUCTIONS…`), the same
  trick `examples/vulnerable-rag-app/` uses. That fork is honest as long
  as we say so on camera.

---

## Java/Spring candidates

### J1. langchain4j/langchain4j-examples — `customer-support-agent-example` (recommended)

- **URL:** https://github.com/langchain4j/langchain4j-examples/tree/main/customer-support-agent-example
- **License:** Apache-2.0 *(verify before commit — LangChain4j main repo is Apache-2.0; this examples repo's root LICENSE was not directly fetched)*
- **Stack:** Spring Boot + LangChain4j (`@Tool` annotations, `AiService` pattern)
- **Estimated source files:** ~10–15 in this subdirectory
- **Shape match:** Strong. Customer-support agent with `@Tool`-annotated methods (booking lookup, cancellation), system prompt declared inline, conversation memory baked into the LangChain4j pattern. Adding a "knowledge base" corpus is one file's worth of work if the example doesn't already have one.
- **Attack-path that lights up:** Tool abuse via prompt injection — the booking-cancellation tool is the kind of "real action with consequences" that makes the demo land. Add a poisoned support FAQ doc into the corpus, the model reads it during retrieval, model triggers cancellation tool. Same shape as `examples/vulnerable-rag-app/`'s exfil path but with a more consequential sink.
- **Why this one first:** It's *the* official LangChain4j example. The launch demo gains credibility from showing that the platform finds the attack path in code people are *actually following as a tutorial*. That framing — "we ran ASP against the Java framework's own customer-support sample and it found the path" — is the strongest version of the multi-stack story.
- **Verify before commit:** root LICENSE on the examples repo, exact dependency shape in `customer-support-agent-example/pom.xml`, whether the example has a corpus dir or whether we add one in a fork.

### J2. kszapsza/spring-ai-rag

- **URL:** https://github.com/kszapsza/spring-ai-rag
- **License:** *Verify — search results didn't surface it. Spring AI itself is Apache-2.0, so a derivative tutorial repo is likely Apache-2.0 or MIT, but not guaranteed.*
- **Stack:** Spring Boot + Spring AI + OpenAI + function calling + RAG
- **Estimated source files:** ~15–25
- **Shape match:** Strong. Real-estate domain, combines function calling and RAG explicitly — GPT can trigger database queries via function calls and the responses feed back into the model's context. That's the textbook "tool the model can call" shape.
- **Attack-path that lights up:** RAG corpus → prompt → model → property-search tool. If the property-search tool returns customer-PII-shaped data, we have the regulated-data sink the platform's score query weights heavily. Add a poisoned property listing description and the path materializes.
- **Why second:** Spring AI is the framework Spring shop will adopt. Demoing against a Spring-AI-shaped target broadens the audience claim beyond LangChain4j users. Slightly less "official" than J1 — it's a community tutorial, not the Spring AI org's own sample.
- **Verify before commit:** license, that "function calling" is wired to a tool the model invokes (not just a static helper), whether there's session memory.

### J3. danvega/java-rag

- **URL:** https://github.com/danvega/java-rag
- **License:** *Verify*
- **Stack:** Spring AI + PGVector + OpenAI
- **Estimated source files:** ~10
- **Shape match:** Moderate. Document-querying RAG with Spring AI; it's smaller and simpler than J1/J2 — *intentionally* a tutorial. Doesn't appear to have function calling out of the box, so we'd need to fork it to add a tool the model can call. That extra forking cost is the reason this is third.
- **Attack-path that lights up:** Once we add a tool, same shape as J1/J2. Without forking, only the prompt-injection-into-prompt half of the path materializes.
- **Why third:** Smallest, cleanest code — best for the *graph close-up* shot in the recording where you want to show every node — but weakest by default since it's RAG-only without tool calling. Pick this if the demo's narrative weight is on RAG-as-attack-surface rather than tool-abuse.
- **Verify before commit:** license, that PGVector is wired up rather than a placeholder, scope of what we'd need to fork.

---

## Node/TypeScript candidates

### N1. vercel-labs/ai-sdk-preview-rag (recommended) — *deep-verified*

- **URL:** https://github.com/vercel-labs/ai-sdk-preview-rag
- **License:** Confirmed has a LICENSE file (Vercel Inc., 2024). Vercel templates are typically Apache-2.0 or MIT — *verify exact terms before commit, but the file exists and is permissive.*
- **Stack:** Next.js (App Router) + Vercel AI SDK + DrizzleORM + PostgreSQL with pgvector
- **Estimated source files:** ~15–20
- **Shape match:** Excellent — possibly the strongest of any candidate on either stack. The architecture explicitly makes **information retrieval a tool call**: the model decides whether to call the `getInformation` tool, which queries the vector store and returns documents. That means the canonical attack — prompt injection from a retrieved doc — flows through *exactly* the edge type the platform's query family looks for (`PROMPT_INJECTABLE_INTO` from `RAGIndex` → `Prompt`, then `CALLS_TOOL` from `Model` → `Tool`).
- **Attack-path that lights up:** Identical shape to `examples/vulnerable-rag-app/`, but in a real-world stack. Add a poisoned chunk to the embedded knowledge base, the model retrieves it via tool call, the injection lands. Bonus: the project also has a `addResource` tool that writes to the knowledge base — that's a memory-poisoning surface, which lights up `MEMORY_POISONABLE_BY` for free.
- **Why this one first:** Vercel AI SDK is the dominant TS agent framework right now. Demoing against a Vercel template is the highest-trust Node story, and the architecture — retrieval-as-tool-call — is the cleanest match for the platform's existing queries. Two attack paths materialize from one repo.
- **Verify before commit:** exact LICENSE terms, that pgvector is the embedding store (vs an in-memory fallback), exact tool list in the production version.

### N2. vercel/ai-sdk-rag-starter

- **URL:** https://github.com/vercel/ai-sdk-rag-starter
- **License:** *Verify — Vercel official repo, almost certainly Apache-2.0 or MIT.*
- **Stack:** Same family as N1 — Next.js + Vercel AI SDK + Drizzle + PostgreSQL. This is the *starter* version that the official "build a RAG chatbot" guide walks through.
- **Estimated source files:** ~10
- **Shape match:** Good. Smaller and more pedagogical than N1 — probably one tool (`getInformation`) instead of two, and a smaller corpus. Easier to read on screen during the recording.
- **Attack-path that lights up:** Same as N1 (corpus → tool-call retrieval → prompt) but with one fewer surface (no `addResource`, so memory-poisoning may not materialize without forking).
- **Why second:** It's the *official* Vercel starter, which inherits the trust of the framework brand more directly than N1 (which is in `vercel-labs`, the experimental org). Smaller and cleaner to demo. Pick this over N1 if you'd rather have one strong attack path on screen than two; pick N1 if you want both paths.
- **Verify before commit:** license, current state of the starter (these tutorial repos churn).

### N3. langchain-ai/rag-research-agent-template-js

- **URL:** https://github.com/langchain-ai/rag-research-agent-template-js
- **License:** MIT (LangChain templates are MIT, *verify on this specific repo*)
- **Stack:** LangGraph.js (LangChain's TS agentic framework) + tools + RAG retrieval
- **Estimated source files:** ~20–30
- **Shape match:** Moderate-to-strong — but more complex shape. This is a **multi-step research agent**, not a single-shot chatbot. The model plans, retrieves, reflects, calls tools across multiple steps. That's interesting for the demo because a multi-step agent has *more* surfaces to attack — every step is an opportunity for injection — but it's harder to fit into a 30-second narration.
- **Attack-path that lights up:** Memory poisoning is the natural one — multi-step agents accumulate state across iterations, and that state is exactly what `MEMORY_POISONABLE_BY` captures. Tool-abuse paths exist too if the research tools include anything with side effects (e.g. a `save_finding` tool).
- **Why third:** Most complex of the three. Best fit if you want the launch story to land on "we find paths in *agentic* systems, not just RAG chatbots" — that's a stronger thesis match. Trade-off: the demo narration has to do more work because the architecture is less familiar.
- **Verify before commit:** MIT license, exact tool list, complexity of the agent loop (whether it fits a one-screen graph view without scrolling).

---

## Recommendation

**Pick J1 + N1.** They both match the platform's existing query families cleanly, both come from organizations the audience already trusts (LangChain4j, Vercel), and together they cover the two ecosystems most likely to be in the launch audience's day jobs. The recording carries the same narrative shape on both — "static scan, attack path materializes, OWASP mapping, fire the attack, exfil JSON appears" — which means one demo script with stack-substitution rather than two unrelated demos.

**If you want to spread the framework story:** swap J1 for J2 (Spring AI instead of LangChain4j) so the Java demo is on a different framework family from anything Node-side.

**If the launch story should lean into "agentic, not chatbot":** swap N1 for N3.

## Verification checklist before commit (start of week 3)

For whichever two you pick:

- [ ] LICENSE file is Apache-2.0 or MIT
- [ ] Source-file count matches estimate (run `find . -type f \( -name '*.java' -o -name '*.ts' -o -name '*.tsx' \) | wc -l`)
- [ ] Manifest dependencies actually include the SDKs we expect (so the manifest parser produces the right `Model:` node)
- [ ] At least one tool is wired to the model (so `Tool` LLM extraction has something to find)
- [ ] Either a corpus directory exists OR we have a clear plan for forking it in
- [ ] Repo activity within the last 6 months (so the demo doesn't link to dead code)
