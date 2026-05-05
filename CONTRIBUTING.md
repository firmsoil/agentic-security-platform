# Contributing

Thanks for considering a contribution. This is an open-source security platform for AI-native applications; the bar for code that lands is high, but the bar for getting *started* is low — pick a small issue and go.

## Before you write code

1. **Check `docs/adr/`** for architectural context. The most important one for new contributors is [ADR-0001: Graph-first architecture](docs/adr/0001-graph-first-architecture.md).
2. **Open an issue or comment on one** for anything non-trivial. A 5-line fix can go straight to PR; a new module should be discussed first.
3. **Read the threat model** at `docs/architecture/threat-model.md` if you're touching anything in `asp-agents`, `asp-adapters/mcp`, policy, or the release pipeline.

## Development setup

```
# Install uv (https://docs.astral.sh/uv/)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync the workspace
uv sync --all-packages --dev

# Run tests
uv run pytest packages/

# Bring the full stack up
cp .env.example .env
docker compose up --build
```

See [README.md](README.md#getting-started) for more detail.

## Architecture rules (enforced in CI)

- **`asp-core` is pure.** It must not import `neo4j`, `httpx`, `kafka`, `anthropic`, or any other I/O library. If it needs one, the abstraction is in the wrong place — put the driver in `asp-adapters` and have core depend on a protocol.
- **The ontology is the domain.** Ontology YAML changes are *not* implementation details. They are semver'd (`v1` → `v2` on breaking changes) and require an ADR for any breaking change.
- **Every PR must have a test.** Bug fixes: add a regression test. Features: add at least one unit test and one integration test if the feature crosses an adapter boundary.
- **No direct `os.environ[...]`.** Use `asp_api.config.Settings` (or equivalent in other packages). This keeps the blast radius of any env-var name change contained to one file.

## Commit and PR style

- **Conventional Commits.** Commit messages follow [conventionalcommits.org](https://www.conventionalcommits.org/). Example: `feat(core): add MEMORY_POISONABLE_BY edge to ontology v1`. The pre-commit hook enforces this.
- **One logical change per PR.** Refactors, features, and bug fixes don't mix.
- **Small PRs merge faster.** PRs over 400 lines of non-test code get extra scrutiny.
- **Describe the threat-model impact.** If your change touches anything in the threat model scope, state the effect in the PR description — even "no impact" is a useful statement.

## Review process

- Every PR needs one maintainer review before merge.
- Security-sensitive areas (agents, adapters, policy, release pipeline) need two reviewers — see `CODEOWNERS`.
- Reviewers will check: tests, typing (mypy strict on core), lint (ruff), threat-model impact, and ADR coverage for architectural decisions.
- PRs that have not passed CI are not reviewed.

## Editing LLM scanner prompts

The four extraction prompts under `prompts/` (`extract_tools.md`,
`extract_prompt_templates.md`, `extract_rag_indices.md`,
`extract_memory_stores.md`) are part of the LLM scanner's contract from
[ADR-0005](docs/adr/0005-llm-scanner-grounding-contract.md). They are
shipped Apache-2.0 so anyone can fork and improve them; the rules below
exist so the launch's determinism story stays intact.

- **Whitespace, typo fixes, and reformatting** — fine, no ADR needed.
  These edits still bump the `prompt_sha` component of the scan cache
  key (intentional — that's what invalidates stale caches), so any
  affected golden fixture under `connectors/github/tests/fixtures/`
  needs to be re-recorded with `python3 scripts/record_golden.py
  --output …`.
- **Material wording changes** — open an ADR following the ADR-0005
  template. *Material* means: changing what the model is told to
  extract, changing the negative-example list, changing the
  confidence calibration rules, changing the adversarial-input guard.
  Anything that could move the false-positive rate measurably.
- **Adding a new prompt for a new node type** — extend the ontology
  first
  (`packages/asp-core/src/asp_core/graph/ontology/v1/nodes.yaml`),
  open an ADR, then ship the prompt and update
  `connectors/github/src/llm/prompts.py::EXTRACTION_PROMPTS`.
- **Bumping `SCANNER_VERSION` in `connectors/github/src/llm/__init__.py`**
  — required when the orchestration logic, verification flow, or
  schema changes in a way that could legitimately produce different
  output for the same prompts and source. Like prompt edits, this
  invalidates every cached scan and every committed golden in one
  step.

The verifier's prompt is intentionally *not* under `prompts/` — it
lives inline in
`connectors/github/src/llm/verifier.py::_VERIFY_SYSTEM_PROMPT` because
it is tightly coupled to the verification *contract*, not the
extraction policy. Edits to it bump `SCANNER_VERSION` rather than
`prompt_sha`, but the same "material change → ADR" rule applies.

## Adding a connector

Each connector in `connectors/` is independently versioned and reviewed. To add one:

1. Copy `connectors/github/` as a template.
2. Implement the connector protocol (`discover`, `ingest`, optionally `enrich`).
3. Add unit tests that run without the real service.
4. Add an integration test that uses `testcontainers` or a recorded fixture.
5. Add an entry to `connectors/registry.yaml` marking the connector as `experimental` initially. Promotion to `official` happens after three merged PRs on the connector and sustained green CI for 30 days.

## Releases

Maintainers cut releases. Contributors don't need to worry about the release process, but it's documented in `docs/guides/release.md` (landing in Phase 1) for transparency. Every release is:

- Tagged with semver
- Signed with Cosign (keyless via GitHub OIDC)
- Accompanied by a CycloneDX SBOM
- Built with SLSA-L3 provenance
- Required to pass the adversarial suite on `main` within 24 hours prior

## Code of Conduct

By participating, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Be kind. Assume good faith. Critique code, not people.

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0 (see `LICENSE`). There is no CLA.
