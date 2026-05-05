# Governance

This document describes how decisions get made in the Agentic Security Platform project. It is intentionally lightweight for v0.1 and will evolve as the community grows.

## Roles

### Contributor

Anyone with at least one merged PR. Contributors may:

- Open issues and PRs
- Comment on proposals
- Participate in RFC discussions

### Connector Maintainer

A contributor with commit rights on a specific `connectors/<name>/` directory and nowhere else.

- Promoted after 3 merged PRs on a single connector and 30 days of sustained green CI for that connector
- Promotion is by majority vote of existing maintainers
- Quarterly activity review; inactive maintainers are moved to emeritus status after 2 consecutive quarters of no activity

### Maintainer

A contributor with commit rights on the core packages (`packages/asp-core`, `packages/asp-adapters`, `packages/asp-agents`, `packages/asp-api`, `packages/asp-cli`).

- Promoted by majority vote of existing maintainers
- Expected contribution: sustained, substantive contribution over at least 6 months
- Active maintainer count target: 3–7 people
- Quarterly activity review

### Emeritus

Former maintainers who have stepped back but remain in good standing. Emeritus maintainers retain read access, may vote on governance changes that were accepted during their tenure, and can be reactivated without re-election.

## Decision-making

Two modes:

### Lazy consensus (default)

Most changes follow lazy consensus with a **72-hour veto window**:

- PR opened → at least one maintainer review required → merges after 72 hours if no veto
- A maintainer veto blocks merge and requires explicit resolution (not "the timer ran out")
- Small bug fixes and documentation changes can merge immediately with one approval

### RFC process

Any of the following require an RFC (Architecture Decision Record in `docs/adr/`):

- Changes to the graph ontology that are **breaking** (bumping `v1` → `v2`)
- Changes to agent protocols (`asp_core.agents.protocols`)
- Changes to the policy engine interface
- New external trust boundaries (new adapter categories, new credential classes)
- Changes to the release signing chain
- License changes (which require community-wide discussion regardless)

RFC flow:

1. Author opens a PR adding `docs/adr/NNNN-short-title.md` using the template in `docs/adr/README.md`
2. Discussion happens on the PR for a minimum of **7 days**
3. Maintainers vote. Acceptance requires 2/3 of active maintainers in favor
4. Accepted RFCs merge with status `Accepted`. Rejected RFCs merge with status `Rejected` so the decision is discoverable
5. Superseded RFCs are not deleted; they're marked `Superseded by: ADR-NNNN`

## Conflict resolution

If consensus cannot be reached on a PR or RFC:

1. First: a synchronous maintainer discussion (video call, archived notes posted to the PR)
2. Second: if still unresolved, majority vote among active maintainers
3. Third: if the vote is tied, the decision defers (status quo wins) until more information is available

The project lead breaks ties only on truly time-critical operational decisions (e.g., responding to a live security incident). There is no appointed lead at v0.1; the role is filled at the first annual maintainer retrospective.

## Security incidents

Security incidents follow a separate process documented in `SECURITY.md`. Incident response is **not** subject to the 72-hour lazy consensus window; a maintainer may merge a security fix immediately with one other maintainer's approval, with post-hoc review on the public advisory.

## Code of Conduct enforcement

The CoC (`CODE_OF_CONDUCT.md`) is enforced by the maintainer group. Reports go to `conduct@<project-domain>` or to any individual maintainer. The maintainer group meets as needed to respond; outcomes range from a private warning to permanent bans. All decisions are logged (privately) for audit.

## Amending this document

Changes to `GOVERNANCE.md` are RFCs under the process above, with one additional constraint: an RFC that would change voting thresholds must itself pass at the higher of the current and proposed thresholds.
