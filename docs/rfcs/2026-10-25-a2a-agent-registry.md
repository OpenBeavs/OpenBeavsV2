# RFC: An A2A Service Boundary for the OpenBeavs Agent Registry

Project 39: OpenBeavs
Faith Nambasa <nambasaf@oregonstate.edu>

| Field | Value |
| --- | --- |
| Author | Faith Nambasa |
| Date | 2026-10-25 |
| Status | Proposed |
| Decision Date | Not decided |
| Deciders | OpenBeavs team, with project partner review |
| Superseded By | Not applicable |

## Problem and Context

OpenBeavs connects users to specialist agents through its hub, Chris. Our project partner wants Chris to communicate with the Agent Registry through Agent2Agent (A2A). This requirement is fixed; the open decision is how to implement it and divide responsibilities. Should the registry run inside Chris's application or independently, and should it return eligible experts or choose one itself?

The V2 registry already supports agent submission, listing, and administrative review. New submissions become pending and inactive; routing includes active approved or provisional agents. However, its routing filter does not consider user permissions, and Chris's expert-call path still contains a placeholder. The existing code therefore provides a review workflow, not the complete proposed A2A pipeline. [P1]

This boundary becomes expensive to reverse once clients depend on its message format and database ownership. Existing chats reference agent IDs, so migration must preserve those relationships. My read-only database checks found three agents, no duplicate non-null card URLs, zero orphaned chat references, and no public Alembic version table. These findings support planning a migration rehearsal, not declaring deployment safe. [P2]

## Options

### Option A: Do nothing for now

Keep the embedded HTTP registry and Chris's direct database lookup. This has the lowest immediate implementation cost and is reasonable while authentication and migration readiness remain unresolved. It delays the partner's A2A requirement and leaves registry changes coupled to Chris. It is a temporary baseline rather than a final solution.

### Option B: Add A2A inside the hub

Publish an Agent Card and A2A interface from the existing application, reusing registry functions. This satisfies the communication requirement without another deployment. It is appropriate if the team cannot maintain an additional service. However, Chris and the registry share releases, credentials, and failures; later separation would still require operational and database changes.

### Option C: Deploy a separate registry agent

Create a deterministic A2A service that returns permitted candidates, while Chris interprets the question and selects an expert. This supports independent maintenance and clearer ownership. It costs another deployment, authenticated network calls, monitoring, and migration work. It is appropriate if an independently maintained registry is a lasting requirement.

### Option D: Let the registry choose the expert

A separate registry receives the question and selects the expert, potentially through an LLM. This is useful if several hubs need one shared selection service. It duplicates part of Chris's responsibility and adds evaluation, privacy, and potentially model costs. The team would need to specify how disagreements and ambiguous requests are handled.

## Analysis

**Complexity and interoperability:** A2A documents curated registries but does not prescribe their application API. We must define discovery inputs, results, and errors ourselves. [1] Option B introduces fewer operational changes; C adds a service boundary without duplicating semantic selection; D adds both. Speaking A2A does not itself require an LLM.

**Performance and cost:** A avoids an additional network request. B adds protocol processing; C adds network latency and another availability dependency; D may also add model latency and usage charges. These are expectations, not benchmark results. Our three-agent inventory does not justify separation for scale alone. C's justification is responsibility and maintainability, which must be weighed against operational overhead.

**Security:** Approval, permission, and authenticity are separate. An approved record does not prove the responding service is genuine, and lifecycle filtering does not enforce user access. Current development-header authentication is forgeable and unsuitable for deployment. [P3] Every option needs real authorization. Separating services only improves isolation when credentials and database privileges are separated too.

**Data ownership:** C should initially preserve the existing agents table and stable IDs, assigning registry writes to a dedicated database role. Chris should retain only privileges necessary for chats and references. This avoids immediately breaking cross-table relationships, but remains transitional rather than complete database isolation. A later physical database split needs a separate migration design.

## Recommendation and Verification Plan

I recommend Option C. Publish the registry's Agent Card at a configured address and implement versioned discovery and lookup skills. Chris supplies capability criteria and verified authorization context; the registry returns eligible agent IDs, endpoints, skills, and review status. Chris selects from that response, rechecks eligibility before dispatch, calls the expert, and identifies the answer's source.

Pending, revoked, inactive, and unauthorized agents must be excluded. Provisional agents need an explicit partner-approved policy. An unavailable registry must produce a clear failure rather than a fallback to mock or unreviewed agents. Discovery must never grant approval. Cryptographic proof that an expert is genuine remains separate work, not a capability claimed by this proposal.

Before deployment, require these checks:

1. **Functional:** demonstrate Chris-to-registry-to-math-agent communication. Test valid requests, no matches, malformed messages, unsupported versions, and preservation of endpoint paths. All cases must pass.
2. **Authorization:** test every supported role against pending, approved, provisional, inactive, and revoked agents. Require zero unauthorized results or dispatches. Revocation between discovery and dispatch must block the next pre-dispatch check.
3. **Migration:** compare the full live schema with the Alembic baseline before stamping it. Rehearse on disposable PostgreSQL, preserving agent IDs and chat references. Require zero new orphans and an individually reviewed approval list; the current migration automatically approves existing rows. [P4]
4. **Performance and failure:** propose warm p95 discovery latency below 300 milliseconds for 1,000 synthetic requests at concurrency 10. Report cold starts separately. Inject registry and database failures; require a bounded response within three seconds and no unauthorized fallback. These are proposed targets, not achieved measurements.
5. **Release:** add the A2A and PostgreSQL checks to CI, stage the full flow, and rehearse application rollback against the expanded schema without deleting review history. Disable expert routing if the previous version cannot enforce policy.

Agree on the contract first, then implement the adapter and authenticated deployment, followed by Chris integration and migration rehearsal. Reconsider B if maintaining the additional service proves impractical.

## Constraints

V2 uses the MIT license. Preserve notices and check predecessor-code and dependency licenses before reuse; V2's license does not automatically relicense imported material. Partner IP and publication permissions still depend on the project agreement. [P5]

Send minimal capability and authorization information to discovery rather than complete conversation histories. Use synthetic test prompts, exclude credentials from Agent Cards and logs, and define retention before collecting operational data.

Repository rules permit AI-assisted work with code and partner requirements but prohibit secrets and credentials. Permission to use AI is not automatically permission to disclose material to classmates. This draft excludes operational addresses and credentials; its disclosure boundary still needs human review. [P5]

## Delegation and Validation

I used Claude Code for implementation and cleanup assistance, and Codex for code inspection, architectural comparison, documentation research, and drafting. My personal validation was running and examining the read-only database queries for schema, migration tracking, duplicate URLs, orphan references, and inventory. These checks mattered because an incorrect baseline or replaced agent ID could damage chat relationships. [P2]

Registry API and migration tests exist, but their presence does not prove PostgreSQL deployment safety or the proposed A2A flow. The rehearsal, production authentication, and new acceptance tests remain unfinished gates. [P6] Human review before committing is already required. I must verify this draft and defend the recommendation; team approval, benchmarks, and production readiness are not claimed.

## Decision

**Proposed:** adopt Option C, subject to team and partner review and the verification gates. A2A is the partner's constraint; deployment boundary and selection ownership remain proposed. Record the outcome and decision date here after review.

## References and Project Evidence

[1] A2A, Agent Discovery, v0.3.0: https://a2a-protocol.org/v0.3.0/topics/agent-discovery/ . Accessed October 25, 2026.

V2 repository evidence(still on my branch working on merging to main):

- P1: `backend/app/registry/service.py`, `router.py`; `backend/app/chris/router.py`.
- P2: Author's supplied read-only Cloud SQL results; a historical snapshot, not a current production guarantee.
- P3: `backend/app/registry/auth.py`.
- P4: `backend/alembic/versions/a7c3e91d5b02_add_agent_registry_review_columns.py`.
- P5: `LICENSE`, `AGENTS.md`, `TEAM_CHARTER.md`.
- P6: `backend/tests/registry/test_registry_api.py`, `test_migration.py`.
