# Security Policy

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues, discussions, or pull requests.**

Instead, use **[GitHub Security Advisories](../../security/advisories/new)** to report privately. This is encrypted, goes directly to maintainers, and keeps a paper trail that works for coordinated disclosure.

If you cannot use GitHub Security Advisories, email `security@<project-domain>` (replace once DNS is set up). PGP key and Sigstore identity will be published here before v0.1 is tagged.

### What to include

- A clear description of the issue and its impact
- Reproduction steps or a proof-of-concept
- The affected version(s) / commit SHA
- Any suggested mitigation, if you have one

### What to expect

| Stage | SLA |
|---|---|
| Acknowledgement that we received the report | 48 hours |
| Triage and initial severity assessment | 5 business days |
| Status update cadence during investigation | weekly |
| Coordinated disclosure target | 90 days from triage, sooner if a fix ships |

We aim to credit reporters in the advisory unless they prefer otherwise.

## Scope

In scope:

- The core platform packages (`asp-core`, `asp-adapters`, `asp-agents`, `asp-api`, `asp-cli`)
- Official connectors under `connectors/`
- The official Docker images we publish
- The Rego policy bundle we publish
- The frontend at `frontend/`

Out of scope (report to the upstream project instead):

- Vulnerabilities in direct dependencies (Neo4j, FastAPI, LangGraph, Temporal, OPA, …)
- Vulnerabilities in demonstrations under `examples/vulnerable-rag-app/` — that app is **intentionally** vulnerable; it is the target of the self-red-team suite

If you're not sure whether something is in scope, report it privately and we'll figure it out together.

## Supported Versions

v0.1 is pre-release. Until v1.0, only the latest tagged release and `main` are supported. Once v1.0 ships, we will adopt a published support matrix covering the current major and one previous.

## Our Own Security Practice

Because this is a security project, we hold ourselves to a higher bar than we would otherwise. Concretely:

- **Threat model**: we maintain a threat model *of the platform itself* at `docs/architecture/threat-model.md`, reviewed quarterly.
- **Adversarial self-test**: `tests/adversarial/` continuously red-teams the platform against the OWASP LLM Top 10 and OWASP Agentic Top 10. Coverage is a release-gating metric.
- **Signed releases**: all published container images are Cosign-signed with GitHub-OIDC keyless signatures. SBOMs and SLSA-L3 build provenance are attached as attestations. Verification instructions ship with each release.
- **Supply chain**: dependencies are pinned with hashes via `uv.lock`; CI runs Trivy, Grype, OSV-Scanner, and gitleaks on every PR.
- **Policy as code**: the authorization rules the platform enforces are themselves Rego, tested with `opa test` on every PR, and distributed as signed OCI artifacts.

If any of these practices slips, treat it as a vulnerability in its own right and report it.
