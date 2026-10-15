# OpenBeavs Team Charter

**Project 39: OpenBeavs**  
**Team Members:**  
- Jiya Pradhan (`pradhanj@oregonstate.edu`)  
- Faith Nambasa (`nambasaf@oregonstate.edu`)  
- Dean R Leon (`leond@oregonstate.edu`)  
- Pedro P Blanco Jaramillo (`blancojp@oregonstate.edu`)  

---

## Roles

The project roles and their associated responsibilities are defined as follows:

1. **Project Manager (PM):**  
   Responsible for communicating the expectations of the project partner to the team and relaying any status changes within project deliverables between the partner and the team. The PM is the primary individual tracking project progress, managing the sprint backlog, and ensuring scheduled milestones are achieved. The PM also conducts regular check-ins with team members to ensure all contributors are aligned, up to date with meetings, and clear on their project duties.

2. **AI Coordinator:**  
   Responsible for provisioning and maintaining AI credits, keeping Google Cloud Platform (GCP) configurations up to date, and managing [`AGENTS.md`](AGENTS.md). The AI Coordinator ensures all AI coding agents configured in the repository are operational and the workflow architecture is effective.  
   **Confidentiality & Security Responsibilities:**  
   - Oversees team-wide compliance with AI confidentiality guidelines across all external AI tools (e.g., ChatGPT, Claude, Antigravity) and internal agents.  
   - Ensures that no sensitive credentials, service account tokens, or environment variables are passed to or stored within AI prompt contexts.  
   - Manages API keys, model quotas, and service accounts securely in Google Cloud Secret Manager or untracked local `.env` configurations rather than in code or prompts.  
   - Audits AI workflows and pull requests to prevent unintentional disclosure of OSU student/faculty data, SSO authentication details, or proprietary partner information.

3. **Quality Owner:**  
   Responsible for ensuring the project adheres to the quality standards defined by the project partner. The Quality Owner communicates any test or CI failures, evaluates overall software and workflow quality, maintains the Definition of Done (DoD) in [`CONTRIBUTING.md`](CONTRIBUTING.md), and verifies that all parts of the application function as intended.

4. **Documentation Owner:**  
   Responsible for maintaining comprehensive, clear, and up-to-date documentation across all aspects of the project. Ensures that documentation accurately reflects the current state of the architecture and workflow. Generates ERDs, architecture decision records (ADRs), guides, and markdown documentation across the repository, collaborating with the AI Coordinator on AI-specific documentation.

### Decision Chairing Requirement

To ensure distributed leadership, **each team member is required to chair at least one formal project decision per term** (covering architectural choices, technical stack selections, workflow policies, or design trade-offs). The decision chair leads the discovery discussion, gathers input, facilitates the vote, and **formally records the decision, rationale, and outcome in the sprint notes and GitHub project documentation**.

### Role Rotation Schedule

Roles rotate every academic term according to the following schedule:

| Term | Project Manager | AI Coordinator | Quality Owner | Documentation Owner |
| :--- | :--- | :--- | :--- | :--- |
| **Fall** | Faith Nambasa | Jiya Pradhan | Dean R Leon | Pedro P Blanco Jaramillo |
| **Winter** | Jiya Pradhan | Faith Nambasa | Pedro P Blanco Jaramillo | Dean R Leon |
| **Spring** | Pedro P Blanco Jaramillo | Dean R Leon | Jiya Pradhan | Faith Nambasa |

---

## Decision Process

All team members are encouraged to share technical and organizational ideas freely. When ideas or proposals are in contention:

1. **Discussion & Chairing:** The team discusses the merits and trade-offs of proposed options. Each member chairs at least one decision per term and guides the discussion to a vote.
2. **Voting:** The team votes on contested items. A simple majority decides the outcome.
3. **Tie-Breaking:** The project partner serves as the primary tie-breaker. If the partner cannot be reached in a timely manner, the tie-breaking responsibility falls to the current Project Manager.
4. **Documentation:** Every formal decision is recorded in the sprint notes on the shared Google Drive. Technical and code-based decisions are additionally documented in the repository via ADR markdown files or linked GitHub issues.

---

## Cadence and Tools

- **Partner Meetings:** Weekly meetings with Project Partner John V. Sweet take place on **Wednesdays at 5:00 PM (PT)** via Microsoft Teams. Meetings are transcribed and recorded so all team members have access to detailed reference notes.
- **Team Meetings:** The team meets in person every **Friday in class**, followed by an optional workload-dependent meeting at **5:00 PM (PT)** (in person or via Teams).
- **Meeting Notes & Transcripts:** For both online and in-person meetings, a designated notetaker records notes and uploads them to the shared Google Drive titled with the meeting date followed by `Meeting Notes` (e.g., `2026-10-14 Meeting Notes`). All online Teams transcripts are retained for absent members.
- **Communication:** Daily communication, quick questions, and coordination occur in the team’s dedicated Microsoft Teams group chat.

---

## Conflict and Accountability

- **Advance Notice for Missed Commitments:** Any team member expecting to miss an agreed-upon deadline or meeting must notify the team at least **24 hours in advance** with a proposed recovery plan. In the event of unforeseen emergencies, notice must be provided as soon as possible.
- **Recovery Trigger:** Two missed commitments or unnotified absences within a single sprint automatically trigger an immediate team check-in and recovery plan to redistribute tasks before deadlines lapse.
- **Conflict Resolution Path:**
  1. *Direct Resolution:* The involved parties discuss the concern within 2 days and agree upon concrete next steps, assuming positive intent.
  2. *PM Mediation:* If unresolved, the issue is escalated to the Project Manager, who arranges mediation within 2 working days.
  3. *Faculty Escalation:* If mediation fails, the recovery plan is not met, or the dispute involves the PM, the concern is formally escalated to the CS Capstone instructional team as outlined in the CS Capstone Handbook.
- **PR Review SLA:** Pull requests awaiting review for more than **two (2) working days** are flagged in the Teams channel and reassigned to another reviewer to maintain momentum.

---

## Inclusion Norms

The team recognizes and respects diverse working habits, schedules, and backgrounds. To foster an inclusive, equitable, and psychologically safe environment:

- Consistent meeting times (Wednesdays at 5 PM with partner, Fridays at 5 PM for team) allow members to plan ahead.
- Transcripts and shared notes ensure full access to information regardless of attendance barriers.
- In-person meetings feature a designated rotating notetaker.
- Every team member is explicitly invited to voice their perspective on all decisions.
- Accommodations can be requested directly in the Teams channel or privately with the PM.
- Disputes or barriers are decided by democratic team vote, reaching out to the project partner or TA in the case of an even split.

---

## AI and Confidentiality

Team members may utilize AI tools of their choice (such as ChatGPT, Claude, Antigravity, GitHub Copilot, and custom repository agents) to accelerate development and research. The following confidentiality boundaries must be maintained:

- **What May Be Shared with AI Tools:**
  - **Project Code & Technical Assets:** General source code, schemas, unit tests, configuration templates, architectural diagrams, and documentation can be entered into and processed by AI tools.
  - **Partner Information:** High-level project requirements, feature requests, user stories, technical architecture, and feedback from project partner John V. Sweet may be shared with AI tools for context and analysis.
  - **Meeting Content:** Meeting transcripts, notes, agendas, and action items may be entered into AI tools for summarization and ticket drafting, provided any personal or sensitive personal information about team members is redacted.
- **Strict Prohibitions (Secrets & Credentials):**
  - **Secrets such as environment variables (`.env`, `.env.local`), private API keys, signing secrets, service account credentials, database passwords, and auth tokens must NEVER be explicitly given or pasted into AI tools or committed to GitHub.**
  - **Microsoft SSO & OSU Account Credentials:** OpenBeavs integrates Microsoft SSO authentication for OSU accounts. Team members must never input real OSU account credentials, passwords, student/staff personally identifiable information (PII), or live session tokens into any AI tool.
  - Mock values, placeholder strings (e.g., `YOUR_API_KEY_HERE`), or variable names must be used in place of actual secrets when interacting with AI tools.
- **AI Coordinator Oversight:** The AI Coordinator monitors AI tool configurations, credit allocations, and security compliance, maintaining up-to-date instructions in [`AGENTS.md`](AGENTS.md).
- **Human Review Mandate:** AI-generated code, documentation, and tests must always be inspected, executed, and validated by a human team member before submitting a pull request or merging into `main`.

---

## Associated Project Artifacts

- **AI Agent Context & Operating Instructions:** [`AGENTS.md`](AGENTS.md)
- **Contribution Guide, Definition of Done & Code of Conduct:** [`CONTRIBUTING.md`](CONTRIBUTING.md)
