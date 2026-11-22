# OpenBeavs Chat System (OCS)

The system people talk to. It relays each question to the expert that fits and returns the expert's answer under its badge.

- **Run by:** the OpenBeavs team.
- **Stores:** a user record for each person who signs in, and no conversations in MVP 0. The browser keeps the conversation and sends its history with each message. The `chat_system` schema also keeps the chat, message, and ticket tables for later use.
- **Signs in:** people with OSU's Microsoft Entra ID single sign-on. Application Services verifies the ID token Microsoft returns, creates or updates the person's user record, and issues a signed session token. A second Microsoft sign-in with Duo multi-factor authentication raises the session to the privileged tier for 30 minutes. A development login (`AUTH_BYPASS_DEV=true`) stands in for Microsoft in local testing.
- **Later:** a sign-in screen in the Web UI, which today chats without signing in; stores settings, favorites, conversations, and messages with their sources.
- **Exposes:** one HTTPS endpoint, serving both the Web UI's code and the API it calls.
- **Calls:** the Agent Registry and experts, over A2A, and Microsoft Entra ID for sign-in. It accepts no A2A calls from outside; inside it, Application Services calls the Conversation Agent over A2A.

| Component | Role | LLM |
|---|---|---|
| `web-ui/` | Presents the conversation in the browser | No |
| `application-services/` | Turn handling and sign-in; later, conversation storage | No |
| `conversation-agent/` | Asks the Registry about each message, calls the one expert it returns, relays its answer or answers itself | Yes |
