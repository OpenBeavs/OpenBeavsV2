# OpenBeavs Chat System (OCS)

The system people talk to. It relays each question to the expert that fits and returns the expert's answer under its badge.

- **Run by:** the OpenBeavs team.
- **Stores:** a user record for each person who signs in, plus saved conversations (`chats` and `messages`) for verified authenticated users. Guest chat remains stateless: the browser keeps guest conversations and sends bounded history with each message. The `chat_system` schema also keeps the `tickets` table for later use.
- **Signs in:** people with OSU's Microsoft Entra ID single sign-on. Application Services verifies the ID token Microsoft returns, creates or updates the person's user record, issues a signed session token, and provides `POST /auth/logout` to clear session cookies. A second Microsoft sign-in with Duo multi-factor authentication raises the session to the privileged tier for 30 minutes. A development login (`AUTH_BYPASS_DEV=true`) stands in for Microsoft in local testing only and fails closed in deployments.
- **Later:** a sign-in screen and saved-chat UI wiring in the Web UI, which today operates in guest mode without signing in; stores settings and support tickets.
- **Exposes:** one HTTPS endpoint, serving both the Web UI's code and the API it calls.
- **Calls:** the Agent Registry and experts, over A2A, and Microsoft Entra ID for sign-in. It accepts no A2A calls from outside; inside it, Application Services calls the Conversation Agent over A2A.

| Component | Role | LLM |
|---|---|---|
| `web-ui/` | Presents the conversation in the browser | No |
| `application-services/` | Turn handling, sign-in, and authenticated conversation storage | No |
| `conversation-agent/` | Asks the Registry about each message, calls the one expert it returns, relays its answer or answers itself | Yes |
