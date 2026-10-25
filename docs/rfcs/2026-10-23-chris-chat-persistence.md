<!-- docs/rfcs/0001-chris-chat-persistence.md -->

# RFC: Should Chris save chat history before authentication exists?

| Field | Value |
| :--- | :--- |
| Author | Jiya Pradhan |
| Date | 2026-10-23 |
| Status | Proposed |
| Decision Date | Pending |
| Deciders | OpenBeavs v2 team |
| Superseded By | None |

## Problem and Context

PR #2 (`feat/database-simplification`) makes Chris write every exchange to two new tables, `chats` and `messages`. OpenBeavs v2 has no authentication code yet, and the PR's router trusts what the client sends:

- `chat_id`, `user_id` and `guest_session_id` come from the request body. `_persist_turn` loads a chat by the client's `chat_id` and appends to it with no ownership check.
- Sending any `user_id` marks the chat "authenticated" and leaves `expires_at` empty, which skips the 2-hour guest limit.
- Nothing in the backend reads `expires_at`, so no guest chat is ever deleted, although `docs/chris.md` describes cascading deletion on purge.
- Message text is stored in plain text. An `encrypted_dek` column exists but nothing uses it.

This decision is hard to reverse for three reasons. Stored conversations cannot be un-stored. The schema, and especially which value identifies a user, is what every later migration must preserve. And PR #1 deliberately set `store: false` on Gemini requests so Google would not keep student conversations; saving them ourselves reverses that choice.

It is needed now because PR #2 is open. If the team does nothing, it merges as written.

## Options

**Option A: Stay stateless.** Do not merge persistence. Chris keeps working because the client already sends `history`. Costs: no routing audit trail, analytics or per-user history, and the schema work waits. Right if the team decides history is not needed this term.

**Option B: Schema now, saving off until SSO.** Merge the tables, add a `CHRIS_PERSIST_CHATS` flag (default off), and when on, take identity only from a verified SSO session. Guests are never saved. Costs: persistence cannot be demoed until SSO exists. Right if SSO is coming and per-user history matters later.

**Option C: Fix guest persistence now.** Keep saving guest chats, but add a server-issued random guest token, an ownership check on every access, and a scheduled purge job. Costs: four new parts, each a place for bugs. Right if the partner needs guest history this term.

**Option D: Do nothing.** Merge PR #2 as written. Costs: the exposure described above. Right only if the app never leaves a closed demo with no real student data.

## Analysis

**Option D** is cheapest today and riskiest. It is the textbook insecure direct object reference. OWASP describes it as a missing object-level authorization check and advises taking the current user from the authenticated session instead of a request parameter. It also says random identifiers such as UUIDs are only defense in depth, so our UUID chat ids do not protect us once an id leaks. Plain-text storage plus no purge means a leak exposes everything ever said.

**Option A** has the smallest attack surface and no privacy risk. It loses a routing audit trail and per-user history, but nothing planned this term needs them.

**Option B** adds a small guard (flag plus session check) and keeps the schema work. It depends on SSO, which v2 needs anyway. Privacy by Design's "privacy as the default" and data minimization point the same way: with no verified user, the default should be to collect nothing. Uncertainty: we do not yet know when SSO lands.

**Option C** protects data of low value. Guest chats last two hours by design, and the client already supplies `history`, which is how v1 gave continuity too. The benefit is small next to the exposure and the extra code.

**Our project as evidence.** The unsafe lines are in `router.py` (`expires_at = now + 7200 if not form.user_id else None`, and the lookup by client `chat_id`). Reviewing PR #2 also showed that the TTL is never enforced and that the tests run on SQLite, which hides foreign-key errors. Persistence needs more hardening than one sprint leaves room for.

## Recommendation and Verification Plan

**Recommend Option B.** Merge the schema, keep saving off by default, and enable it only when identity comes from the SSO session. Rolling back means setting the flag to off.

We will know it was the right choice if these pass in CI before the flag is ever turned on:

1. **Flag off writes nothing:** a call to `POST /chris/message` creates zero rows in `chats` and `messages`.
2. **Body identity is ignored:** with the flag on and no session, sending `user_id` does not create an "authenticated" chat or an empty `expires_at`.
3. **No cross-user access:** user B posting user A's `chat_id` gets a 404, and A's message count is unchanged. OWASP recommends testing with multiple accounts.
4. **Purge works:** a chat past `expires_at` is deleted by the job, and its messages cascade.

Acceptance criterion: all four tests pass and the team reviews the SSO identity code before the flag is enabled. Revisit the decision if the partner needs guest history; the path is then Option C with the same four tests.

## Constraints

- **Student data law:** FERPA covers information a school keeps about a student in any recorded form, and applies to contractors working for the school. Whether Chris logs count as education records is not confirmed. We will treat them as possibly covered and ask the partner, John V. Sweet, and OSU's privacy contact before saving any real conversations.
- **Partner confidentiality:** the repo is public, so no real chat data, keys or partner-internal details go into tests or docs. `CONTRIBUTING.md` already bans committed secrets.
- **Data use:** saved chats may be used only for routing and debugging, not shared or reused, and kept only as long as needed, then destroyed.
- **Licensing and IP:** the choice adds no new service, dependency or license.

## Delegation and Validation

I used Claude (Anthropic) to read the PR #2 branch, list risks, find sources, and draft this RFC. I wrote the review comments on PR #2 and chose the decision and recommendation.

Handing code reading to the tool was reasonable because every claim can be checked against the repo. Points where I stopped and validated myself:

- I opened `router.py`, `models/chat.py`, `llm.py` and `seed_agents.py` on the branch and confirmed the four behaviors in Problem and Context [VERIFY before submitting].
- I confirmed there is no authentication code in `backend/app` and no purge code reading `expires_at` [VERIFY before submitting].
- I read the OWASP, FERPA and Privacy by Design sources myself and kept only claims they support [VERIFY before submitting].
- Not yet validated: the four tests in the verification plan are a plan. I have not run them, and v2 has no CI yet, so review by a teammate is the only gate today.

## Decision

Pending. The team will vote, record the chair and date here, and change Status to Accepted or Rejected.

## References

- OWASP, Insecure Direct Object Reference Prevention Cheat Sheet. https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html
- NCES, Protecting the Privacy of Student Education Records (FERPA overview). https://nces.ed.gov/pubs97/web/97859.asp
- A. Cavoukian, Privacy by Design: The 7 Foundational Principles. https://student.cs.uwaterloo.ca/~cs492/papers/7foundationalprinciples_longer.pdf
- J. Bezos, 2015 letter to Amazon shareholders (Type 1 and Type 2 decisions), the source of the hard-to-reverse framing in the assignment.