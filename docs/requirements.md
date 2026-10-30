# OpenBeavs v2 Requirements

## Problem statement

OpenBeavs aims to give OSU users one place to find AI agents and ask questions. The questions are proposed to Chris, the orchastrator
that manages all communciation with a user. Chris then takes user messages passes them over to the agent registry which will find the most sutiable expert agent to give backa response to Chris that they can pass off to the user. An expert agent is an agent that is maintaiend to be highly specialized in one field, being able to give very accurate answers with low chances of hallucination. 

Essentially, instead of one large LLM that has potential to halluciante due to all of its knowledge, this system asks the questions to smaller models but they are highly knowlegeable in one topic, making them give very accurate resonses for that one topic.

## Functional requirements

Priorities use MoSCoW: **Must** is required for the MVP, **Should** is important
but not required for the MVP. These priorities were specified by the team.

Anonymous chat is implemented. Microsoft SSO, saving anonymous chats to an
account after sign-in, reopening saved account chats, and real A2A expert calls
are not implemented yet, and current agent selection only returns a routing preview.
Multi-agent combined replies and steering an in-progress response are also not
implemented yet.
The acceptance criteria below describe the MVP target.

- **FR-1 (Must: users need access without an account):** Users can chat
  anonymously. **Acceptance:** A user can send a message and receive a response
  without creating an account or signing in.
- **FR-2 (Should: OSU users benefit from institutional sign-in):** Users can sign
  in through Microsoft SSO. **Acceptance:** An approved OSU account can sign in;
  invalid or expired sign-in credentials are rejected.
- **FR-3 (Must: expert answers are the main service):** Users can talk with expert
  agents through Chris. **Acceptance:** A message reaches the selected expert
  agent, and that agent's response is displayed to the user. A routing preview
  alone does not pass.
- **FR-4 (Must: users need to know who answered):** Chris tells users when they
  did not connect with an expert agent. **Acceptance:** If no suitable agent is
  found or the connection fails, Chris clearly says that no expert agent was
  connected. Any direct answer is identified as coming from Chris.
- **FR-5 (Must: expert services must use the agreed protocol):** Communication
  between the hub and expert agents uses A2A. **Acceptance:** An integration test
  confirms that a message and its response are exchanged with an expert agent
  using A2A.
- **FR-6 (Should: users should not lose their chat when signing in):** Signing in
  saves the current anonymous chat to the user's account. **Acceptance:** After
  Microsoft SSO sign-in, the same conversation is available in that account with
  all earlier messages in order.
- **FR-7 (Should: users need access to past conversations):** Users with an
  account can save and reopen their chats. **Acceptance:** After signing out and
  signing back in, a user can open a saved chat and see its earlier messages in
  order. Another account cannot access that chat.
- **FR-8 (Should: one message may need several experts):** Chris sends different
  questions in one message to the appropriate expert agents and combines their
  answers. **Acceptance:** A message with questions for two different experts
  produces one reply from Chris incorporating both experts' responses.
- **FR-9 (Should: users may clarify a request before the answer is ready):** A
  follow-up sent while Chris is preparing a reply steers the current turn instead
  of starting a separate turn. **Acceptance:** Send a clarification before the
  pending reply finishes; Chris takes both inputs into account and returns one
  final reply rather than two separate replies.

## Non-functional requirements

Passing results still need verification. Items marked assumed need confirmation.

- **NFR-1 (Must, assumed: messages must be safe):** Message rendering creates
  **0 executable HTML elements**. Measure with a browser test using script tags
  and an image event handler as message content.
- **NFR-2 (Must, assumed: users need to recover):** After **1 failed request**,
  show an error, preserve input, and add **0 successful turns**. Measure by
  simulating a service failure in a browser test.
- **NFR-3 (Should, assumed: users may use phones):** At **390 × 844 pixels**, the
  page has **0 horizontal overflow**. Measure page width against viewport width
  in a browser test.
- **NFR-4 (Should: users need quick answers):** A complete chat response appears
  in **less than 3 seconds**, including any expert-agent work. Measure from
  sending the message until the complete reply is displayed in an end-to-end
  test. For a follow-up that steers an in-progress turn, measure from the latest
  input. This is a target, not verified current performance.

## Constraints

- **C-1:** Project rules prohibit real credentials in tracked source, submitted
  documents, or AI conversations.
- **C-2:** Inherited OpenBeavs/Open WebUI code as a starter implementation
- **C-3:** Original Bakcend and dataase all need to be redone, most of the code will not be inherreted and will be started from scratch.

## Success metrics

Proposed targets, results have not been collected.

- **Discovery:** 3 reviewers find a named registered agent without help.
  Pass if **3/3 succeed**, record demo results.
- **Chat:** Run 3 guest sessions, each with a greeting and follow-up.
  Pass if **3/3 return both replies and store turns in order**, check the
  interface as resposne should be visible a buble pointing towards what expert agent responded.

## Non-goals

- Supporting voice, images, or file uploads in the MVP.
- Building a native mobile app for the MVP.
- Recreating the full Open WebUI feature set.

## Open questions

Owners below are proposed roles for the team to assign.

- What privacy and retention rules apply for user chats?
