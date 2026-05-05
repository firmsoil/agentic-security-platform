# Announcing the Agentic Security Platform: graph-native security for AI-native applications

*Draft only. Written for internal review, not for publication this week.*

AI-native applications create a security problem that conventional tooling does not answer very well.

We already know how to find vulnerable packages, risky cloud permissions, exposed services, and misconfigurations. What gets much harder in an AI system is answering the operational question that matters most: *is there an actual path from an untrusted input to a model, from that model to a tool, and from that tool to sensitive data or a privileged action?*

That is not a static-code question. It is not only a cloud-permissions question. It is not only an observability question. It is a relationship question. And relationship questions are graph questions.

That is why we built the Agentic Security Platform: an open-source, graph-native security platform for AI-native applications. It models the parts of modern AI systems that existing security programs struggle to reason about together in one place: code, infrastructure, identities, runtime events, models, prompts, tools, memory, retrieval, and data sensitivity. Then it asks a security question over the whole system: what attack paths exist, which ones are reachable, and which ones map to the taxonomies security leaders are beginning to standardize around?

Today, the platform maps findings to the OWASP Top 10 for LLM Applications (2025) and the OWASP Agentic Top 10 (2026). It is Apache 2.0 licensed, intentionally built in the open, and designed to be legible both to contributors and to the teams who may eventually rely on it in regulated environments.

## Why this exists

Security teams are under pressure from both sides of the AI adoption curve.

On one side, product and platform teams are shipping fast: agentic workflows, RAG systems, tool-using assistants, internal copilots, and automation layers that blur the line between application logic and decision-making runtime. On the other side, the security controls available today were mostly shaped for earlier architectures. They are good at surfacing components. They are much less good at explaining *paths*.

That gap shows up quickly in practical questions:

- Is this prompt-injectable content source actually connected to a model that can call tools?
- Does that tool execute with permissions that matter?
- Can poisoned memory influence downstream actions?
- Does a reachable path terminate in regulated data, or only in low-sensitivity content?
- Which of these paths correspond to recognized categories like the OWASP Agentic Top 10?

Those are not edge cases for AI-native software. They are the shape of the core problem.

Our view is that AI security needs a system of record that treats relationships as first-class. The security graph is that system of record. Instead of collecting disconnected findings and trying to correlate them late, we represent the environment as nodes and edges from the beginning: sources, prompts, models, tools, memory stores, identities, repositories, databases, and the relationships between them. Risk is then expressed as graph traversal.

This is familiar in other parts of security. BloodHound proved the value of graph thinking in identity attack paths. Cloud security platforms proved the value of continuously ingesting infrastructure state. What changes in AI-native applications is the ontology. We need native concepts for prompts, model invocation, tool reachability, memory poisoning, and data exposure, not just generic tags bolted onto legacy asset graphs.

## What it does today

The platform is still early, but it now has a real, end-to-end demo that makes the thesis concrete.

Today’s implementation includes a versioned ontology for AI-relevant node and edge types, a Neo4j-backed security graph, tenant-scoped graph access, a multi-stack GitHub connector, a seeded vulnerable RAG example, a live attack-path API, and a frontend graph explorer built with Cytoscape.js.

The connector scans Python, Java/Spring, and Node/TypeScript repositories. The dependency-manifest pass is fully deterministic for every stack — it parses `requirements.txt`, `pom.xml`/`build.gradle*`, or `package.json` and emits the `Repository`, `Container`, `Artifact`, and `Model` nodes with no LLM involvement. The four code-shape node types — `Tool`, `PromptTemplate`, `RAGIndex`, `MemoryStore` — come from a second pass that uses an LLM under a strict grounding contract: every emitted node carries a file path, line range, file SHA-256, and a confidence rating, and a separate verification call confirms each grounded claim against the cited code span before the node reaches the graph. Scans are cached by the tuple `(repo_commit_sha, scanner_version, adapter, model_name, prompt_sha)`, so re-runs against the same commit produce the same graph; re-scoring requires an explicit version bump. The contract is recorded in [ADR-0005](adr/0005-llm-scanner-grounding-contract.md) and the operator-facing trust posture is in [`docs/llm-scanner.md`](llm-scanner.md). The bright line is deliberate: the LLM produces *inventory*, not findings — the security-semantic edges (`PROMPT_INJECTABLE_INTO`, `TOOL_INVOKABLE_BY`, `MEMORY_POISONABLE_BY`, …) live in hand-authored per-target profiles and are not LLM-generated.

Most importantly, the current demo can answer a meaningful question against a seeded graph: *what attack paths exist that map to OWASP Agentic Top 10?*

That answer is not hardcoded in the UI. It is produced by canonical Cypher-backed query patterns in the codebase. The current query library includes:

- prompt-injection paths that traverse an explicit prompt surface before reaching a tool and a regulated-data sink
- tool-abuse paths that model tool invocability and downstream reachability
- memory-poisoning paths that capture how poisoned memory can influence model behavior and subsequent tool use

Each query returns typed attack-path objects, scoped to a tenant, with the OWASP mapping resolved at query time. The API exposes those paths at `/api/security/attack-paths`, and the frontend renders them as a graph with category-aware styling and an accompanying findings sidebar.

That makes the current demo more than a static mockup. It is a small but real proof point that the graph can connect AI-specific attack semantics to a visible operator experience.

There is still meaningful work ahead. The event bus and async graph workers are planned. The AWS connector is planned. OTel-to-graph ingestion is planned. But the project now has a live surface that lets a technical and non-technical audience see the difference between “we have some security metadata” and “we can explain an attack path through an AI system.”

## The graph-first thesis

The platform’s core architectural decision is visible in the ADRs for a reason: we want design choices to be inspectable, not implied.

ADR-0001, the graph-first architecture decision record, captures the central thesis: the security graph is not an implementation detail of one service. It is the domain. API handlers, frontend views, compliance evidence, and future agent workflows all derive from the graph rather than each maintaining their own private model.

That decision matters because there were easier short-term options available. We could have built a flat findings store and correlated results later. We could have used a document-oriented shape with denormalized risk blobs. Those patterns are familiar, and they can work for narrower products. But they make the most important AI-security questions awkward to express. Attack paths become a thicket of joins, embedded context, and one-off logic scattered across services.

The graph-first choice gives us a cleaner model:

- the ontology is a versioned artifact rather than an incidental byproduct of application code
- AI-specific relationships are first-class edges rather than tags
- downstream consumers can ask type-aware questions against one shared model
- canonical attack-path queries can live in one place rather than being recreated across API handlers, demos, and notebooks

That same architectural-review process also shaped a second important decision. ADR-0003 records a reversal on tenancy: tenant scoping discipline was pulled forward into the foundation instead of being deferred. The review separated a cheap, necessary invariant from a more expensive authorization mechanism and concluded that waiting would create avoidable long-term risk. The result is a better project: every node and edge carries `tenant_id`, adapter methods require explicit tenant context, and every graph query is scoped from day one.

This is worth calling out because it says something about how the project is run. We are not using ADRs as after-the-fact documentation. We are using them as evidence that decisions can be challenged, sharpened, and, when necessary, reversed in the open.

## The OWASP Agentic Top 10 mapping

One of the reasons to build this project now is that the industry is converging on more useful language for AI risk.

OWASP’s work on LLM and Agentic Top 10 categories gives security leaders a shared way to discuss classes of failures without pretending every environment looks the same. We think open-source infrastructure should meet that taxonomy where teams already are. If a security lead asks, “Which of our observed or reachable patterns map to the Agentic Top 10?” the platform should be able to answer in a way that is concrete, inspectable, and backed by graph evidence.

That is the role of the current attack-path demo.

The seeded example is intentionally simple enough to understand and rich enough to demonstrate the idea. A source can be prompt-injectable into a prompt surface. A model uses that prompt. The model can call a tool. The tool can reach a memory store or other downstream resource. The path can terminate in a data classification labeled as regulated. When the query engine materializes that path, it attaches the OWASP mapping as part of the returned finding.

This approach is useful for two reasons.

First, it grounds taxonomy in system reality. Instead of “we believe we may be exposed to category X,” the platform can say “here is a path in your environment that matches category X, here are the nodes and edges involved, and here is the likely sink.” That is much more actionable for engineering, security, and audit conversations.

Second, it gives us a disciplined way to grow coverage over time. The OWASP mapping layer is not the ontology itself. That means we can continue expanding graph concepts and path families without entangling every schema change with every framework update. It also means coverage can become measurable. The roadmap’s eventual goal of broad adversarial coverage is not just a slogan; it can be tracked as implemented query families and tested scenarios.

## What’s next

The next chapter is about turning the current demo into a more continuously observed system.

Near-term priorities are clear in the roadmap and reflected in the capability matrix:

- land the AWS connector so the graph spans more of the real control plane
- add the Redpanda event bus and async graph workers that were moved forward after architectural review
- connect OTel telemetry into the graph ingestion path
- broaden query families and adversarial coverage beyond the current seeded scenarios
- keep tightening the frontend so it works not just as a developer tool, but as an executive and operator narrative surface

Longer term, the project is headed toward a tri-agent operating model: Red for adversarial reasoning, Blue for detection and containment, and Green for remediation. We are deliberately not overselling that future before the substrate is ready. The right order is graph first, path reasoning second, ingestion hardening third, agent orchestration after that.

That sequencing is part of the point. There is a temptation in AI infrastructure to jump straight to autonomous behavior. Our view is that autonomy without a trustworthy system model is mostly theater. The graph is what gives later automation a meaningful substrate.

## How to contribute

We are building this as an open-source project because the problem benefits from shared ontology, shared examples, and shared pressure-testing.

There are several ways contributors can help right now.

If you are an infrastructure or security engineer, connectors are a high-leverage place to contribute. If you work in application security or AI evaluation, attack-path query families and adversarial scenarios are equally valuable. If your strength is frontend or product design, the graph explorer and operator workflows have plenty of room to grow. If you live closer to governance and assurance, the mapping and evidence layers will need careful, skeptical contributors too.

Just as importantly, contributors can engage with the way decisions are made. The ADRs are public, the tradeoffs are visible, and material changes to ontology, graph behavior, and policy interfaces should go through that process. That is not bureaucracy for its own sake. It is how we keep the project coherent as it expands.

For teams evaluating whether to sponsor, amplify, or pilot the project, that openness matters. You should be able to see not only what the code does, but how the project reasons about itself when the architecture gets consequential.

The Agentic Security Platform is still early. That is precisely why now is a good time to get involved. The ontology is taking shape, the live demo is real, and the design language of AI-native security is still being written. We would like this project to help write it in public, with enough rigor that practitioners can trust what grows from here.
