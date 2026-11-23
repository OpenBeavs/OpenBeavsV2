# RFC: Implementing Microsoft SSO in OpenBeavs v2

| Field | Value |
| --- | --- |
| Author | Pedro P Blanco Jaramillo |
| Date | 2026-10-24 |
| Status | Accepted |
| Decision Date |2026-11-20|
| Deciders | Faith Nambasa, Jiya Pradhan, Dean R Leon, Pedro P Blanco Jaramillo, John V. Sweet |
| Superseded By | N/A |

## Problem and Context

OpenBeaves is an Oregon State University project that gives students a central place to ask questions and access expert AI agents. These agents focus on particular subjects, such as course scheduling, the College of Engineering, or general OSU information. The intended model allows individuals or departments to maintain the information their agents use to answer questions. The primary stakeholders are students who need useful answers for their questions, departments that maintain expert agents, the OpenBeaves development team, and project partner John V. Sweet, who provides requirements and direction.

Users interact with Chris, the platform’s orchestrator. In the intended workflow, Chris analyzes the question, selects a suitable expert agent from the registry, and returns the agent’s response. When no available expert is suitable, Chris can respond directly through its underlying language model. Accounts would let users save chats, pick up where they left off, and find answers to questions they asked in the past. The project requirements classify anonymous chat as a **Must** and Microsoft SSO and saved account chats as **Shoulds** [1].

We inherited a prototype from last year’s team that included Microsoft and Google sign-in as well as local account registration [7]. The prototype never went live, so we have no existing user accounts or conversations to migrate. At our project partner’s request, we are rebuilding the application and using the previous team’s work as a reference. Since we are redesigning the backend and database, the old authentication implementation would be difficult to transfer directly [8].

Our project partner chose Microsoft SSO as the sign-in method for eligible OSU students and faculty. Visitors who want to learn about OSU can still chat anonymously. This lets eligible users sign in with their existing OSU credentials and gives OpenBeaves a verified identity to use for account features. The backend would still need to check who can access each saved conversation [4].

With the sign-in method chosen, the team had to decide whether to implement SSO during the rebuild, prepare the architecture for later integration, or defer both. On November 20, 2026, the team decided to implement Microsoft SSO in OpenBeavs v2.

The timing matters because we are redesigning the backend and database now. The chat model already has separate fields for an account owner and a guest session [2]. If we defer both implementation and planning, we could later need to change how the backend identifies users, assigns ownership of saved conversations, and checks who can access them. The potential cost comes from reworking the new application as it grows.

## Options

### Option A: Implement Microsoft SSO

Implement working sign-in with OSU’s Microsoft accounts during the current rebuild. The backend would verify the user’s identity and establish a session that OpenBeaves can use for account features. This gives the team a verified identity to build on when adding features such as saved chat history while still anonymous chats, since if a user were then to sign in after chatting anonymously then the chats must be automatically added to their account.[1].

This option has the highest immediate cost since it requires the most amount of design, implementation, and testing, on top of the possible setbacks of not being granted authorization to use the Microsoft SSO from IT for OSU accounts. The team would need to coordinate application configuration with OSU, implement sign-in and session handling, and test that eligible users can sign in, invalid sign-ins are rejected, and anonymous chat still works [1, 6]. This work would compete with the other MVP requirements the team must complete as it adds extra work. Implementing SSO during the rebuild could reduce later changes to the database and APIs when the team adds account features. Option A works best if the team can obtain the required configuration and has time to implement and test the integration during the rebuild.

### Option B: Design for Microsoft SSO

Define how the backend will represent a verified user and how the database will associate saved conversations with an account. Keep the current chat flow anonymous and defer Microsoft sign-in until a later milestone. This gives the team a plan for adding accounts while keeping most of its current effort on anonymous chat and expert agents.

The team would spend time reviewing the identity and ownership design now and would still need to integrate and test Microsoft SSO later. Making those design choices early could reduce later backend and database changes, although testing against OSU’s configuration could reveal assumptions that need to change. Option B works best if the team expects to need accounts and has time to design for them now, but the schedule or institutional setup prevents completing the integration during the rebuild. Meaning that some time is spent now to save time later in the future.

### Option C: Do Nothing

Continue building anonymous chat and expert agent routing while deferring both Microsoft SSO and any additional design work for accounts. This keeps the current scope smallest and lets the team focus on the core experience of asking a question and getting an answer.

If the team adds accounts later, it may need to revise database relationships and API routes so conversations can be linked to verified users and accessed only by their owners. Option C works best if the current milestone only requires anonymous chat and the team needs its available time for that work. The team would accept the possibility of more work when account features are added. This option would effectively leave the most time for the current MVP while deferring any work dealing with accounts to the future, which has potential to cause problems.

## Analysis
**Development effort and MVP scope.** The project requirements classify anonymous chat as a Must and Microsoft SSO, saving a guest conversation to an account, and reopening saved chats as Shoulds [1]. Option A takes the most effort during the rebuild. Commit 4a0af50 added authentication configuration, routes, token verification, and tests, and changed how the chat service receives identity information [3]. Option B would spend time defining account ownership now and defer the integration and testing. Option C would leave the most time for anonymous chat and expert agent routing, with the possibility of more changes when accounts are introduced.

**Security and conversation ownership.** The earlier chat model already had separate fields for account ownership and guest sessions. The chat service in that baseline could look up a user record using an identifier supplied in the request [2]. That lookup showed that the account existed. A verified session is needed to establish who sent the request. For features like saved chat history, the backend must also check whether that user can access the requested conversation [4]. Option A gives the team a way to test the link between sign-in and ownership during the rebuild. Option B can define where those checks belong, with testing against real sign-in deferred. Option C leaves those decisions until account features are scheduled.

**Maintainability and rework.** The previous prototype never went live, so there are no legacy accounts or conversations to migrate. The main cost of waiting is that adding accounts may require changes to database relationships and API routes built during the rebuild. Option B can reduce some of that rework by deciding early how a conversation will be linked to an account. For example, Microsoft recommends using a stable identity claim because email addresses and usernames can change [5]. Option A lets the team verify that repeated sign-ins resolve to the same account before saved chats depend on that relationship. With Option B, the team would verify that behavior during later integration.

**Performance, cost, and uncertainty.** Microsoft’s sign-in flow adds a browser redirect and an exchange with the identity provider [6]. That adds work to signing in, while anonymous chat can operate without that exchange. The team has no measured sign-in latency, implementation estimate, or confirmed timeline for receiving OSU’s configuration. If the configuration is available during the rebuild, Option A lets the team validate identity with real OSU accounts sooner. If it is delayed, Option B still gives the team time to work out account ownership, while Option C preserves that time for the demo.

## Recommendation and Verification Plan

I recommend **Option B: Design for Microsoft SSO**. The demo requires anonymous chat, while Microsoft SSO and saved account chats are listed as Shoulds in the project requirements [1]. Option B lets us decide how the backend will identify a signed-in user and how the database will connect conversations to accounts while keeping time available for the demo MVP. Those decisions could reduce rework compared with Option C. The team accepted Option A, which lets us verify the integration sooner if we can obtain OSU’s configuration.

To verify the preparation proposed in Option B, review these checks before calling the design ready:

1. **Trace identity and ownership.** Walk through a guest request and a future signed-in request. The design passes if it identifies where the server will obtain the verified account identity, how that identity will map to a local user, and where the backend will check conversation ownership. A user ID supplied by the browser cannot establish ownership as this could lead to malicious actors injecting user-ids and getting access to chats that are not theirs [4].
2. **Check that anonymous chat still works.** In CI, open the app without signing in, send a question, and send a follow-up. Both requests should succeed and preserve the conversation within the active session. A sign-in prompt or loss of follow-up context fails the check.
3. **Check what the later integration would require.** Have a teammate trace the changes needed to add Microsoft sign-in and connect it to the proposed ownership model. If they find that the design requires replacing the planned account-to-chat relationship or redesigning the anonymous chat API, revise the design before accepting it.

For **Option A**, the team should also verify the working integration before enabling SSO for users. In staging, sign in twice with an approved OSU test account and confirm that both attempts resolve to the same local account. Verify that invalid or expired sign-in attempts create no authenticated session and that logout ends access to protected operations. When saved chats are enabled, use two test accounts to confirm that each can access its own chats and that neither can read or modify the other’s conversations. These are planned acceptance checks.

## Constraints

**Institutional access.** OpenBeaves needs an application registration and configuration approved for use with OSU’s Microsoft identity service before enabling institutional sign-in. Our project partner specified that accounts are for eligible OSU students and faculty, with anonymous chat still available to visitors. Under Option A, the team must confirm which accounts are eligible and verify in staging that an eligible account can sign in, an ineligible account cannot, and visitors can still chat without an account. Option B can proceed with design work while the configuration is pending [1, 6].

**Conversation privacy and data use.** Saved chats may contain personal information which means that before enabling saved history, the team must define which account attributes it needs, who may access saved conversations, and how long they are retained and how they can be deleted. For saved history, the backend must check conversation ownership whenever a user reads or modifies a chat, such as deleting it or asking further questions in it. The verification plan uses two test accounts to check that each can access its own conversations. Microsoft tokens and identity attributes that expert agents do not need should be excluded from requests to those agents to preserve user privacy [4].

**Credential confidentiality.** Repository policy prohibits putting real OSU credentials, Microsoft SSO tokens, and application secrets into source control or AI tools [9]. Automated tests must use synthetic credentials and identities. Live verification should use an approved test account, and the team must check that authentication errors do not expose credentials or tokens in logs.

**Licensing and reuse.** The team is using the previous prototype as a reference. If the implementation reuses legacy code or introduces an authentication library, review its license and any notice requirements before incorporating it. This RFC does not select a specific authentication library [7, 8].

## Delegation and Validation

**What I delegated.** For the original draft, I used generative AI to review the inherited codebase and identify parts of the authentication system that could be difficult to carry over to v2. For the final draft, I used generative AI to compare the legacy and v2 code, review Microsoft documentation, and go over the current codebase due to some SSO implementations being in the works.

**How I checked the evidence.** I limited the AI’s role to reading sources and drafting text. The legacy repository includes tests for sign-in, signup, and retrieving the current session user [10]. The v2 SSO feature branch includes tests for rejecting invalid tokens and enforcing conversation ownership [3]. These tests show which behaviors each codebase was designed to check. A live sign-in with an approved OSU test account remains a staging check in the verification plan.

**What I validated myself.** I reviewed how Microsoft SSO would fit into the redesigned backend and database. On the backend side, I checked where the application would need to establish a verified identity before treating a request as signed in. On the database side, I checked how that identity would need to connect to a local user who could own saved conversations. I focused on these two points because an error in identity or ownership could give a user access to someone else’s chat, and changing that relationship after accounts are in use could require rework. That review helped me distinguish implementing SSO now, designing for it now, and deferring both.

## Decision

**Accepted: Option A: Implement Microsoft SSO in OpenBeavs v2.**

On November 20, 2026, the team decided to implement Microsoft SSO during the v2 rebuild. **Pedro** chaired the decision discussion.

Eligible OSU students and faculty will be able to sign in with their OSU accounts, and visitors will still be able to chat anonymously [1]. Microsoft SSO will give OpenBeavs a verified identity for future account features. Saved chat history will require separate implementation and checks to ensure users can access only their own conversations as only account log in is in the works right now.

## References
1. OpenBeavs v2, `docs/requirements.md`, functional requirements FR-1, FR-2, FR-6, and FR-7.
2. OpenBeavs v2, baseline reviewed at commit `bbd1f6f`. Conversation model and chat handling in `backend/app/models/chat.py` and `backend/app/chat/service.py`.
3. OpenBeavs v2, SSO feature branch. [Microsoft SSO integration, commit `4a0af50`](https://github.com/OpenBeavs/OpenBeavsV2/commit/4a0af5032c9914a9933bd97be24c9e16e4708380).
4. OWASP, [Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).
5. Microsoft Learn, [ID token claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference).
6. Microsoft Learn, [Microsoft identity platform and OAuth 2.0 authorization code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow).
7. OpenBeavs legacy repository. Microsoft and Google sign-in configuration in `front/backend/open_webui/config.py` and local account registration in `front/backend/open_webui/routers/auths.py`.
8. OpenBeavs v2, `docs/db_docs/database-architecture.md`, legacy architecture and v2 database redesign.
9. OpenBeavs v2, `AGENTS.md`, repository rules for credential confidentiality and AI use.
10. OpenBeavs legacy repository, `front/backend/open_webui/test/apps/webui/routers/test_auths.py`, tests for sign-in, signup, and session user retrieval.