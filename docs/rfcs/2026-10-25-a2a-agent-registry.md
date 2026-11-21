# RFC: An A2A Service Boundary for the OpenBeavs Agent Registry

Project 39: OpenBeavs | Faith Nambasa

| Field | Value |
| --- | --- |
| Created | October 25, 2026 |
| Revised | November 20, 2026 |
| Status | Proposed |
| Decision Date | Formal acceptance not recorded in the evidence reviewed |
| Deciders | OpenBeavs team, with project partner review |
| Superseded By | Not applicable |

## Problem and Context

OpenBeavs gives Oregon State University users one place to ask questions and reach specialist AI agents. Chris coordinates the conversation, the Agent Registry maintains the catalog and finds an appropriate expert, and that expert answers within its domain. The decision concerns where the registry runs, who chooses the expert, and which checks must happen before a question leaves the hub. The requirements prioritize anonymous chat, actual expert communication, and telling users who answered. [P1]

Agent2Agent (A2A) is the protocol these services use to exchange messages. An Agent Card describes a service's capabilities and connection information; it is not proof that the service is trustworthy. Alembic is the tool that applies versioned changes to our database structure. Defining these terms matters because a communication protocol, a database migration, and an authorization rule solve different problems. [1][4]

The October draft recommended a separate registry returning eligible candidates for Chris to choose from. The implementation has since moved toward a separate registry that makes the selection itself. The November architecture review also assigns matching to the registry. Current code provides a standalone A2A service, model-assisted selection, and Chris-to-expert calls. These changes are evidence of implementation direction, not proof of formal acceptance or production readiness. [P2][P3]

The main stake is sending a question to an inappropriate or unauthorized destination. Delaying this decision lets clients depend on conflicting selection rules, response formats, and database privileges. Changing those dependencies later could break routing or existing agent references. However, separation alone does not fix permissions. Current eligibility excludes nonpublic agents and agents requiring a role; it does not yet implement access for authenticated users. This RFC keeps that restriction until verified identity and authorization are connected. [P4]

## Options

### Option A: Keep the current prototype without further boundary work

Retain the standalone selector and current public-agent restriction, while deferring production authentication and ownership changes. This is the present-day do-nothing baseline, rather than the embedded registry described in October. It avoids immediate integration work and is reasonable for isolated demonstrations with synthetic conversations. It cannot justify enabling restricted experts or exposing development authentication in deployment. Security gaps and shared database dependencies would remain. [P3][P4]

### Option B: Host the A2A registry inside the hub

Use one application deployment with an A2A registry interface and reusable registry functions. This reduces deployment, monitoring, and configuration work. It would fit a team unable to maintain another service. The cost is shared releases, failures, and potentially credentials. Because a standalone service already exists, moving back would also require integration changes. A2A would remain the communication contract, but process separation would disappear.

### Option C: Separate the catalog, but let Chris choose

Run the registry independently and return eligible candidates to Chris, which interprets the question and chooses one. This was my original recommendation. It keeps the registry deterministic and avoids a model dependency inside discovery. It is appropriate when clients need their own selection policies. However, it transfers candidate descriptions and selection maintenance to Chris, reverses the current implementation direction, and could duplicate matching across future clients. [P2][P3]

### Option D: Separate the registry and let it select

Keep the standalone registry as the owner of eligibility and expert matching. Return one selected endpoint, no match, or an error; Chris handles the conversation and expert call. This matches the current requirements and implementation. Its costs include another service, selection-model latency, model evaluation, and sending bounded conversation context into selection. It is appropriate when matching should be shared across clients and the team can maintain and secure the service. [P1][P3]

### Option E: Start embedded, then extract the registry

Implement B first using the same contract and authorization checks, then move to C when independent ownership or another client justifies extraction. This staged option could deliver A2A earlier without immediately operating another service. It adds two integration stages and risks postponing separation indefinitely. It is credible early in development or if the standalone deployment becomes impractical. Today, the existing standalone implementation reduces its advantage. A later move to D instead would also require an explicit selection-ownership decision.

## Analysis

**Complexity and maintainability.** A2A documents several discovery strategies, including curated registries, but our application still defines its selection behavior. The current adapter advertises protocol 1.0 and a selection skill. Its successful reply contains an agent ID and endpoint, or an explicit no-match value. Errors have defined codes. D preserves that implemented contract; C would require a different candidate response and matching logic in Chris. E is useful as a delivery strategy, but not automatically simpler after extraction has already happened. [1][P3]

**Performance and cost.** D adds selection-model work before the expert can answer. The selector currently limits candidates to 50 and uses an initial confidence threshold of 0.7; exceeding the candidate limit produces an error rather than silently removing choices. Neither limit proves routing quality. C relocates selection cost rather than necessarily eliminating it. B saves a deployment but not the model computation if it retains matching. No measured latency or monetary saving is claimed here. The project's under-three-second complete-response target needs measurement across the whole chain. [P1][P3]

**Security.** Three questions must remain separate: may this service call the registry, may this user reach this agent, and is the expert genuinely operated by its claimed owner? Receiver-side Google token verification addresses the first. Public-only filtering currently limits the second. Neither establishes institutional certification of experts. The registry verifier checks tokens and allowed callers, but the inspected Chris client sends no credential. Registry management still depends on development-header authentication and refuses protected requests when that mode is disabled. These are release gaps, not benefits already obtained from separation. [P4][P5]

**Data ownership and availability.** The standalone registry still shares the agents table with the backend. Separate processes therefore do not establish separate database privileges. Dedicated database roles should restrict registry selection to catalog reads, with management writes separately controlled. Stable agent IDs must survive any migration. A shared PostgreSQL instance can remain while privileges are separated; physical database extraction is a later decision. Registry failure also adds a dependency: current Chris code can answer directly after selection failure, so explicit disclosure is required to satisfy the attribution requirement. [P1][P3][P6]

## Recommendation and Verification Plan

I recommend Option D, with a public-agent first release and explicit security gates. This changes the October recommendation because the current requirements, implementation, and supervisor's architecture place matching in the registry. Chris should not perform a second model-based choice over the same catalog. The registry must select only among records that ordinary code has already made eligible. This is a recommendation for completing the boundary, not a claim that every safeguard below exists. [P1][P2][P3]

**Caller verification.** In deployment, Chris should obtain a short-lived Google ID token for the configured registry audience and attach it to the A2A request. Google's documentation describes this service-to-service pattern. The receiver uses Google's verifier for signature, issuer, audience, and expiry validation, then requires a verified email on the configured caller allow-list. Missing or invalid tokens return 401; a valid but unapproved caller returns 403; unusable authentication configuration returns 503. The application must reject requests before selection or model work begins. Public discovery metadata does not authorize an RPC call. [2][3][P5]

**User permissions.** A service token identifies Chris, not the person chatting with it. For this release, authenticated and anonymous users must both be limited to active, public, approved or provisional agents with no required role. Before restricted agents are enabled, the hub must verify the user's session and convey a signed, short-lived authorization assertion bound to that user and the registry audience. The registry must verify its issuer, signature, expiry, and role mapping independently. Client-supplied headers or message text must never grant roles. Experts must enforce their own resource access as well. These are future requirements, not existing delegated authorization.

**Selection and review.** The model may return only an eligible ID or no match; endpoints must come from stored records. Current code rechecks eligibility before returning a selection. Add a final eligibility check immediately before dispatch, and define that revocation after an expert call has already started cannot retract that request. Default auto approval currently makes clean submissions provisional and active; manual mode leaves them pending. Use manual approval for the first external release unless the partner explicitly approves the provisional policy. Automated card checks do not certify the operator. [P3][P4]

The following checks are proposed acceptance gates. Existing tests provide starting points, but a test file's presence is not a passing deployment result. Use disposable data, record configuration and software versions, and retain the outcomes with the release evidence. [P7]

1. **Contract and routing, before integration approval.** Start the hub, Chris, registry, and a controlled expert fixture. Send a known expert question, an unmatched greeting, malformed input, an unsupported protocol request, and a valid endpoint containing a path. Require the selected question to reach only that endpoint, preserve its path, and return the expert's answer with attribution. Malformed requests must produce defined errors without dispatch. Test all three selection outcomes separately.

2. **Direct authentication, before any deployed exposure.** Call the registry RPC directly, bypassing Chris. Try no token, malformed and expired tokens, wrong audience, wrong issuer, an unauthorized service account, and forged user/admin headers. Require 401 or 403 as appropriate, zero model calls, and zero expert calls. Missing configuration must return 503. Then prove an allowed deployed caller succeeds with a genuinely issued token. Existing mocked-verifier tests cannot establish that the deployed issuer, audience, and transport configuration work together. [P5][P7]

3. **Eligibility and revocation, before enabling expert traffic.** Create fixtures covering pending, approved, provisional, revoked, and inactive agents, crossed with public, restricted, and role-required access. Exercise both Chris and direct registry requests with anonymous, ordinary-user, and claimed-admin contexts. Under the current public-only policy, only active public approved/provisional rows without roles may appear. Missing or forged context must never expand that set. Revoke a selected fixture before dispatch; require zero calls to it. Repeat with verified role assertions before any future restricted rollout.

4. **Selection quality and failure handling, before pilot use.** Build 60 synthetic labeled questions: 20 clear matches, 20 ambiguous or unmatched cases, and 20 attempts to influence routing. Freeze expected acceptable destinations before tuning and run each three times. Propose at least 90% correct clear matches and no unauthorized destinations in any run. Separately inject registry timeout, database failure, model failure, and expert failure. Require a visible statement that no expert answered whenever a direct response is used, with no fabricated expert attribution. The quality threshold is proposed for team agreement.

5. **Performance, migration, and rollback, before release.** Run 100 complete synthetic conversations at concurrency five; report median, p95, errors, and cold starts separately. Check the existing three-second response target and document any approved revision rather than inventing a pass. On disposable PostgreSQL, compare pre/post row counts, stable IDs, references, and review states. Require zero lost records or new orphan references; individually review rows that the legacy migration backfills as approved. Verify forbidden database operations fail under each runtime role. Rehearse disabling expert routing and restoring the previous application without deleting review history. [P1][P6]

## Constraints

The repository uses the MIT license. Preserve its notice and check licenses for imported predecessor code, SDKs, and dependencies before redistribution; the repository license does not override their terms. This makes license review a release condition rather than a reason to assume every component is reusable. Partner ownership and publication permissions still depend on the project agreement. [P8]

D sends question text and limited history to the registry, whose selector uses Gemini. Therefore, a public expert does not imply a non-sensitive question. Keep tests synthetic, minimize forwarded context, avoid raw conversation logging, and confirm permitted model-provider processing and retention before handling sensitive conversations. If that processing is not permitted, the proposed model-based selector must change. Bounding history reduces disclosure but does not anonymize it. [P3]

Project instructions allow code and partner requirements in AI tools but prohibit credentials and require human review of generated work. This document omits live addresses, account identifiers, keys, and database contents. Permission to use AI does not independently authorize class publication of partner material. Review the submission's disclosure boundary before uploading it. [P8]

## Delegation and Validation

I used Claude Code for earlier implementation and cleanup assistance, and Codex for repository inspection, architecture comparison, documentation research, and drafting. For this revision, Codex compared the original RFC with current source files and Benjamin's feedback. The checks distinguished receiver authentication from missing caller credentials, model selection from permission enforcement, and implemented behavior from proposed release gates. Those distinctions matter because an overstated security claim could allow restricted traffic before the required controls exist. [P3][P5][P9]

My original draft records my personal review of read-only database results covering schema, migration tracking, duplicate card URLs, and orphaned references. That was a historical checkpoint because replacing IDs or accepting an incorrect migration baseline could break relationships. It is not a fresh database inspection for this revision. I also supplied actual local launch and login-error results during subsequent troubleshooting; those observations do not establish successful production authentication. [P9]

AI-assisted inspection is not my personal verification of every source or proposed test. Before submission, I need to review the revised recommendation and cited evidence myself. Before release, the team must review authentication, database privileges, and migration results because errors there have the highest impact. Codex's focused rerun on November 20 passed 196 tests covering registry authentication, selection, eligibility, and pipeline behavior, using an in-memory database with environment-file loading disabled. These controlled tests do not prove live token integration or model quality. The existing CI configuration uses SQLite and does not establish a live PostgreSQL migration rehearsal. Production approval, benchmark success, and completed end-user authorization are not claimed. [P7]

## Decision

**Proposed:** complete Option D with authenticated service calls, public-only eligibility, independently enforced authorization before restricted expansion, and the acceptance gates above. Standalone registry selection and expert invocation are implemented directions; formal team acceptance and production readiness are not established by this revision. Record the decision date and reviewers when the team decides, and update this record if the recommendation is accepted, rejected, or superseded.

## References

External documentation checked November 20, 2026:

[1] A2A Project, Agent Discovery. https://a2a-protocol.org/latest/topics/agent-discovery/ . Supports Agent Cards and discovery strategies; application policy remains project-specific.

[2] Google Cloud, Authenticating service-to-service. https://docs.cloud.google.com/run/docs/authenticating/service-to-service . Supports audience-bound identity tokens for service calls.

[3] google-auth, google.oauth2.id_token reference. https://google-auth.readthedocs.io/en/latest/reference/google.oauth2.id_token.html . Supports Google token verification and issuer/audience validation.

[4] Alembic, Tutorial. https://alembic.sqlalchemy.org/en/latest/tutorial.html . Describes versioned relational database change management.

Project evidence inspected November 20, 2026 in the local OpenBeavsV2 development checkout at commit `f0dc3d5`; the cited backend source was unmodified. These references describe that checkout, not a verified production deployment:

[P1] `docs/requirements.md`, particularly FR-1, FR-3, FR-4, FR-5, and NFR-4.

[P2] Partner-supplied "OpenBeavs Architecture = WebUI+Chris Perspective - v2026-1113a - TECHNICAL REVIEW," sections "Agent Registry" and "The Conversation Agent." Supplied design guidance; not proof that every depicted boundary is implemented.

[P3] `backend/app/registry/a2a_app.py`, `a2a.py`, `selection.py`; `backend/app/chris/agent.py`, `registry_client.py`, `expert_client.py`; `docs/registry.md`.

[P4] `backend/app/registry/service.py`: `_routable_conditions`, `get_routable_agent`, `approval_mode`, and `submit_agent`.

[P5] `backend/app/registry/a2a_auth.py`, `auth.py`; `backend/app/chris/registry_client.py`. Receiver verification, management-auth gap, and absent outgoing registry credential.

[P6] `backend/alembic/versions/a7c3e91d5b02_add_agent_registry_review_columns.py`; `backend/app/registry/service.py`; `docs/registry.md`. Shared catalog and legacy approval backfill.

[P7] `backend/tests/registry/test_a2a_auth.py`, `test_selection.py`, `test_chris_gating.py`, `test_migration.py`; `backend/tests/integration/test_pipeline.py`, `test_registry_failures.py`; `.github/workflows/checks.yml`. Existing test definitions and configured CI, not a claim that all proposed gates passed.

Focused execution evidence: November 20, 2026, Python pytest with `-B -p no:cacheprovider`, environment-file loading disabled and an in-memory SQLite database. Selected suites: `test_a2a_auth.py`, `test_selection.py`, `test_chris_gating.py`, `test_pipeline.py`, and `test_registry_failures.py`. Result: 196 passed, one dependency deprecation warning, 20.03 seconds. Migration tests were inspected but were not included in this focused run; Google verification and model calls use test doubles where specified by the suites.

[P8] `LICENSE`, `AGENTS.md`. Licensing, confidentiality, and human-review requirements.

[P9] October 25 RFC, "Delegation and Validation"; author's supplied local launch/login troubleshooting observations, November 20. Historical self-reported validation and local observations, not independent production measurements.
