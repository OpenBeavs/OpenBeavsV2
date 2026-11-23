# RFC: Keep unauthenticated Chris conversations stateless

| Field | Value |
| :--- | :--- |
| Author | Jiya Pradhan |
| Original draft | 2026-10-23 |
| Revised | 2026-11-20 |
| Status | Accepted |
| Decision date | Exact discussion date not recorded; implemented by PR #25, merged 2026-11-13 |
| Deciders | OpenBeavs v2 team |
| Superseded by | None |

## Problem and Context

OpenBeavs v2 is an AI agent platform for Oregon State University. Its hub registers specialized agents, controls which agents are available, and relays messages. Chris is its conversational orchestrator: it receives a user's question, selects an eligible specialist when appropriate, and provides a direct answer when delegation is unavailable. This RFC concerns the public chat application's storage behavior, rather than the separate database needed for the agent registry [3, 4].

The decision is whether to retain conversations when the application has no verified identity for the caller. Persistence creates durable chat and message records. Authentication establishes who the caller is; authorization determines which records that caller may access. A request containing a user identifier does not establish either. Messages may contain sensitive information, so incorrect ownership checks or indefinite retention can have consequences beyond a broken interface.

Conversation continuity does not require database persistence. The browser can keep earlier successful turns in memory and send them as `history` with the next question. Chris then receives conversational context without the public chat handler retrieving a stored transcript. The tradeoff is that refreshing or closing the tab loses that local history [4, 5].

The original October draft evaluated persistence introduced through PR #2 [1]. It raised concerns about client-supplied identity and chat identifiers, ownership checks, and the difference between assigning an expiration timestamp and actually deleting expired records. Those concerns explain the original decision's urgency; they should not be read as assertions that every later version retained the same defects. The final recommendation is grounded in the implementation and regression tests named below, rather than unverified quotations from an earlier branch.

PR #2 was merged. The team subsequently decided not to save unauthenticated conversations. PR #25 removed conversation reads and writes from the public chat workflow and was merged into `dev` on November 13, 2026 [2]. Doing nothing before that removal would have retained persistence and its ownership and retention obligations. The question is now how to preserve the accepted boundary and verify that removing storage has not broken useful conversation behavior.

The choice is consequential even though code can be changed again. Already collected conversations may have been copied or exposed before deletion. Retention also creates operational expectations, cleanup responsibilities, and migration work. Removing new writes does not remove old transcripts: PR #25's documentation explicitly leaves previously stored records for the database owner to remove [2, 6].

## Options

The alternatives below describe the decision to remove public-chat persistence after its initial introduction. Existing database tables can remain under any option; keeping a schema does not require making the public endpoint use it.

**Option A: Remove public-chat persistence and use browser history.** The handler accepts a question and client-provided context, returns an answer, and neither reads nor writes conversation records. The browser keeps successful turns in memory. Costs include losing history on refresh, no database transcript for support investigations, and repeated transmission of context. This is the right choice when guest continuity within a tab is sufficient and durable history does not justify operating a guest identity and retention system. PR #25 implements this approach [2, 4, 5].

**Option B: Retain persistence behind a default-off flag until verified authentication exists.** Keep a dormant storage path and introduce a proposed `CHRIS_PERSIST_CHATS` setting. Enable saving only for a server-verified principal; guests remain unsaved. This preserves an implementation path toward authenticated history, but adds configuration combinations, dormant code, and tests for both enabled and disabled states. It is appropriate when authenticated history has a concrete requirement and the team can maintain the identity integration. The flag is an alternative in this RFC, not a claim about deployed configuration.

**Option C: Implement guest persistence with explicit protections.** Issue an unpredictable server-generated guest credential, require ownership verification for every conversation operation, and implement retention and deletion. This supports history beyond the current tab without requiring university sign-in. Costs include credential handling, expiry, cleanup monitoring, and tests against unauthorized access. It is appropriate if a confirmed partner requirement makes durable guest history necessary and the team accepts the operational burden. A two-hour timestamp alone would not satisfy this option.

**Option D: Do nothing and retain the existing persistence path.** Avoid the removal work and preserve database-backed continuity. Its immediate benefit is avoiding another implementation change; its costs are continuing storage, access-control, and retention responsibilities. This could be acceptable temporarily in an isolated demonstration using synthetic data, with access restricted and an explicit review before real users. That condition is not a sufficient basis for the public service's long-term behavior. It is included as the baseline alternative, rather than dismissed without considering its short-term benefit.

## Analysis

**Security and ownership.** OWASP describes insecure direct object references as failures to check whether the requester may access a referenced object. It recommends deriving identity from the authenticated session and checking authorization for each object; unpredictable identifiers supplement those checks [9]. For this project, Option A removes stored-conversation lookup from the public handler entirely. In `backend/app/chat/service.py` (now `chat-system/application-services/application_services/chat/service.py`), `handle_message` constructs context from `form.history` and performs only agent-display database lookup. The legacy-ID regression test submits identifiers for existing records and checks that stored content is neither replayed nor modified [3, 4]. This evidence supports a narrow conclusion about this handler, not a claim that the whole platform has no security risks.

**Retention and purpose.** W3C's Privacy Principles recommend limiting data collection to what is necessary for the user's purpose [10]. Applied here, the available client-history mechanism supports a conversation without requiring a durable transcript. Option A therefore reduces database retention exposure. It still processes message contents and sends context between services. Browser memory, network transport, model-provider handling, and operational logging remain separate concerns; this decision does not certify them as risk-free. Option C could be justified by a durable-history requirement, but that requirement should be explicit before additional retention is introduced.

**Complexity and maintainability.** The PR #25 patch removes persistence and stored-history branches, legacy request fields, and the expired-chat maintenance route [2]. Those are concrete reductions in the public workflow's responsibilities. Option B preserves additional behavior that must remain safe as authentication evolves. Option C adds guest credential lifecycle and deletion operations. Neither is automatically wrong, but both require maintenance beyond answering a question. The project evidence supports fewer code paths under A; it does not establish an exact number of engineering hours saved.

**Performance and cost.** Option A avoids conversation database reads, inserts, and commits in the message handler [3]. This should reduce work attributable to persistence, but no latency benchmark or financial estimate is claimed. Agent registry reads still occur. Replaying history increases request traffic, and long conversations require deliberate context limits. `backend/app/history.py` (now `chat-system/application-services/application_services/history.py` and `chat-system/conversation-agent/conversation_agent/history.py`) forwards only the latest six valid history entries, truncating each to 1,000 UTF-8 bytes, while questions are limited to 4,000 bytes [4]. These bounds constrain downstream context, not necessarily the entire incoming HTTP request. Earlier details can therefore fall out of the model's context even while visible in the browser.

**Usability and observability.** Frontend tests demonstrate that successful turns are sent in order and remain available across in-app navigation; the browser test expects a reload to clear conversations [5]. This is an intentional limitation, not persistent history. Removing transcripts also reduces material available for debugging and retrospective analysis. The team should use synthetic reproduction cases and appropriately limited operational signals rather than quietly restoring message retention. If users require conversation recovery after refresh, that is evidence to revisit the decision instead of treating memory-only history as equivalent to saved history.

**Uncertainty.** This RFC does not establish whether users need cross-session recovery, whether old records have been removed, or what production provider-retention settings apply. Those questions require partner input or deployment evidence. Earlier assertions that SQLite inherently hides foreign-key errors and that no planned feature needs transcripts are omitted because they were not established by the reviewed evidence. The recommendation follows the demonstrable public workflow and its current boundary.

## Recommendation and Verification Plan

Recommend **Option A**, matching the implemented decision. The earlier draft preferred Option B, but maintaining a dormant persistence path is not necessary to preserve the schema or to support the existing browser-history workflow. Any future authenticated history should have its own ownership, retention, and verification design. Turning on a flag is not an available rollback mechanism for this implementation.

Use the following checks with synthetic messages and an isolated test database. A null response identifier alone is insufficient: tests must examine database contents and the context forwarded to Chris.

1. **No new records.** Run `test_guest_answer_does_not_persist` and `test_claimed_existing_user_cannot_create_saved_chat` in `backend/tests/test_chris_db.py` (now `chat-system/application-services/tests/test_chris_db.py` and `tests/end-to-end/tests/test_chris_db.py`). Expect HTTP 200, `chat_id: null`, and zero chat and message records. The second test supplies an existing user's identifier, detecting a regression that mistakes a body field for authentication [4].
2. **Legacy records remain inaccessible through chat.** Run `test_legacy_ids_cannot_read_or_write_history`, including its guest/authenticated and claimed-user combinations. The fixture seeds private stored text. Expect Chris to receive only supplied browser history and the seeded record to remain unchanged. This catches accidental reintroduction of stored-history reads or appends [4].
3. **Continuity without storage.** Run `test_frontend_chat_uses_real_adk_chris` and the conversation unit tests. Expect prior successful turns to reach the mocked selection and answer functions in order, with no new transcript rows. Frontend requests must omit guest and chat identifiers, even when a legacy response returns a chat ID [4, 5].
4. **Failures remain transient.** Run the error-response and blank-message tests in `test_chris_db.py`, plus frontend failure-recovery tests. Expect failed requests to create no records; failed turns must not enter later conversation history [4, 5].
5. **Browser lifetime matches the policy.** Run the first test in `frontend/tests/frontend.spec.ts` (now `chat-system/web-ui/tests/frontend.spec.ts`). Verify navigation preserves the active conversation, a follow-up includes history, and reload clears the message list. Inspect frontend storage writes to confirm transcripts are not persisted; the unit test's fresh-instance assertion alone cannot prove every browser-storage behavior [5].

From `backend` (now `agent-registry/`, `chat-system/conversation-agent/`, `chat-system/application-services/`, and `tests/end-to-end/`), run the configured environment's `python -m pytest` and `ruff check .`; the pytest suite includes registry security tests. From `frontend` (now `chat-system/web-ui/`), run `npm run test`, `npm run lint`, and `npm run test:e2e`. CI also builds the frontend and runs pipeline browser tests [7]. Record actual results separately from this repeatable acceptance plan. Automated runs performed during this revision are agent checks, not evidence of the author's personal validation.

Acceptance requires these checks to pass and human review of the storage boundary. Live provider behavior and removal of historical records require separate operational confirmation. If a deployment regresses, stop exposing the affected path or restore the reviewed stateless implementation; do not restore unsafe storage merely to recover history.

## Constraints

**Confidentiality and test data.** Repository policy prohibits exposing credentials or real secrets to AI tools and requires human review of generated work [8]. Tests and examples must use synthetic transcripts and identities. This constrains how the verification plan is executed and what evidence may be attached to a public decision record. No production transcript is needed to demonstrate a failed ownership boundary.

**Institutional data handling.** This RFC makes no determination that a particular conversation is an education record or that this design proves legal compliance. Before adding persistence, the partner and appropriate OSU privacy authority should resolve permitted purposes, retention, access, and deletion requirements. The practical consequence is that authentication alone would not authorize unrestricted collection or reuse. Privacy uncertainty supports retaining the no-storage default while requirements are clarified.

**Existing records and external processing.** The database owner must separately assess historical transcripts and applicable deletion obligations. This RFC does not authorize deleting production data. Likewise, application statelessness does not establish model-provider retention or backup policy. Those boundaries must be checked before making broader user-facing promises about where messages are kept [2, 6].

**Licensing and IP.** The selected change removes public-chat storage behavior without introducing a new storage provider or dependency [2]. It therefore creates no new dependency-license choice within this decision. Existing project and provider obligations still apply; a future external storage option would require a fresh review of licensing, processing terms, and partner permission.

## Delegation and Validation

The original draft records Claude's involvement in reading PR #2, identifying risks, locating sources, and drafting prose. ChatGPT/Codex assisted with this revision by explaining peer feedback, inspecting current repository code and PR #25, checking external guidance, revising the alternatives, and aligning the verification plan with stateless behavior. These are delegated research and editing tasks; the tools cannot establish the author's personal judgment or completed human review.

During this revision, Codex inspected the chat service and schemas to check the highest-cost boundary: whether supplied identifiers could enable stored-conversation access. It also inspected database regression tests, browser history handling, and CI configuration. These checks explain the named evidence and replace unsupported blanket statements. They do not prove a production deployment matches the checkout or that old transcripts have been deleted.

I completed the personal validation for this revision. I reviewed the no-storage handler and legacy-ID test to confirm that caller-supplied identifiers do not enable stored-conversation access, because getting that boundary wrong could expose another conversation. I verified browser reload behavior because users must understand that in-memory history is not recoverable after refresh. I also reviewed the cited guidance and checked that it supports the recommendation. These personal checks resolved the original verification placeholders; the repeatable verification plan remains in place for future changes.

## Decision

**Accepted: unauthenticated conversations are not saved.** PR #25 implemented this policy by making public chat stateless and was merged on November 13, 2026 [2]. The exact earlier discussion date is not recorded here. The public endpoint does not retrieve or append stored transcripts, including when callers supply legacy identifiers. Browser memory supplies continuity; historical database cleanup remains separate. Reconsider persistence only with a concrete requirement and a reviewed identity, ownership, retention, and validation design.

## References

1. OpenBeavs v2, [PR #2](https://github.com/OpenBeavs/OpenBeavsV2/pull/2), historical persistence proposal. Earlier-draft findings are historical context, not newly certified line-level findings.
2. OpenBeavs v2, [PR #25](https://github.com/OpenBeavs/OpenBeavsV2/pull/25), stateless guest interactions; merge commit `fd4cca8722bbe17001fd1313a85c3e0a19a9b393`, dated 2026-11-13.
3. Current workflow: `backend/app/chat/service.py` (now `chat-system/application-services/application_services/chat/service.py`), especially `handle_message`.
4. Request and history boundaries: `backend/app/chat/schemas.py` (now `chat-system/application-services/application_services/chat/schemas.py`), `backend/app/history.py` (now `chat-system/application-services/application_services/history.py` and `chat-system/conversation-agent/conversation_agent/history.py`); regression evidence: `backend/tests/test_chris_db.py` (now `chat-system/application-services/tests/test_chris_db.py` and `tests/end-to-end/tests/test_chris_db.py`).
5. Browser behavior: `frontend/src/lib/conversation.ts` (now `chat-system/web-ui/src/lib/conversation.ts`), `frontend/src/lib/conversation.test.ts` (now `chat-system/web-ui/src/lib/conversation.test.ts`), and `frontend/tests/frontend.spec.ts` (now `chat-system/web-ui/tests/frontend.spec.ts`).
6. Retention documentation: `docs/frontend.md` (now `chat-system/web-ui/README.md`) and `docs/db_docs/database-architecture.md` (now `docs/database/database-architecture.md`), including PR #25's changes.
7. CI checks: `.github/workflows/checks.yml`; command definitions: `frontend/package.json` (now `chat-system/web-ui/package.json`) and `backend/pyproject.toml` (now `agent-registry/pyproject.toml`, `chat-system/conversation-agent/pyproject.toml`, `chat-system/application-services/pyproject.toml`, and `tests/end-to-end/pyproject.toml`).
8. Repository confidentiality and human-review requirements: `AGENTS.md`.
9. OWASP, [Insecure Direct Object Reference Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html), identifier complexity and access-control guidance, accessed 2026-11-20.
10. W3C, [Privacy Principles](https://www.w3.org/TR/privacy-principles/), section 2.2, Data Minimization, accessed 2026-11-20.