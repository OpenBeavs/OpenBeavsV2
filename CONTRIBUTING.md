# Contributing Guide

How to set up, code, test, review, and release so contributions meet our Definition of Done.

## Code of Conduct
### 1. Our Professional Pledge

We are committed to making the **OpenBeavs** project a positive, harassment-free, and inclusive experience for everyone involved, regardless of technical background, personal identity, or level of experience.

### 2. Our Standards of Behavior

We expect all team members to adhere to the following professional standards:

* **Be Respectful and Inclusive:** Use welcoming, clear, and professional language. Be considerate of differing viewpoints, backgrounds, and experiences, especially when giving and receiving technical feedback.
* **Give Constructive Feedback:** Focus reviews and critiques on the code and the technical requirement, not on the person. Be graceful in accepting constructive criticism.
* **Demonstrate Empathy:** Recognize that your colleagues are also students balancing coursework and life. Support your teammates and help them find solutions.
* **Focus on the Project Goal:** All discussions and decisions should be focused on achieving the **Acceptance Criteria** and delivering a high-quality product for the stakeholder, **John V. Sweet**, and future OSU Faculty users.
* **Maintain Confidentiality:** Respect any information shared within the team or by the sponsor that is deemed sensitive or internal to OSU.

### 3. Unacceptable Behavior

Unacceptable behaviors include, but are not limited to:

* Harassment, discrimination, personal attacks, or exclusionary jokes.
* Trolling or intentionally disruptive behavior in meetings, code reviews, or digital channels.
* Insulting or derogatory comments targeting a person's identity or work.
* Any conduct that would be considered unprofessional or inappropriate in a typical business setting.

### 4. Conflict Resolution & Reporting Process

For issues that arise within the team, we recommend a simple escalation path:

1.  **Direct Communication (Preferred):** If you are comfortable, address the issue privately and respectfully with the person involved. Always **assume positive intent** first.
2.  **Team Escalation:** If the issue persists or you are not comfortable with direct communication, immediately raise the concern to the team's designated **Project Manager (PM)**. The PM is responsible for mediating the conflict.
3.  **Capstone Escalation (Official):** If the conflict involves the PM, or if the mediation process fails, the issue must be formally escalated according to the **CS Capstone Handbook**. This typically means contacting your faculty capstone instructor or advisor.

---

## Getting Started

See [Frontend setup and integration](docs/frontend.md) for the complete local
backend/frontend setup, configuration, checks, and static hosting requirements.

### Prerequisites

* Python 3.12 and a project virtual environment.
* [Node.js 22 or newer and npm](https://nodejs.org/).
* Backend Gemini configuration for live answers. Docker and Google Cloud SDK
  are not required for local development.

### Running the app Locally

Start FastAPI from `backend/` on port 8000 after installing the backend and
applying Alembic migrations. In a second terminal, run `npm ci` and `npm run dev`
from `frontend/`. The frontend proxies the existing Chris API to FastAPI; the
original Open WebUI backend is not used. Follow the linked guide for commands.

### Handling secrets

- Don't store or push secrets to the codebase
- Use environment variables for secrets

## Branching & Workflow

Our workflow is GitFlow.
Default branch is `main`.
Branch naming should be simple and to the point, creating a new branch for a new feature.
* Examples: `feature/agent-registration`, `bugfix/hub-div-center`
Rebase when bringing in lots of changes at once, but try to avoid. Standard procedure is merge.
After merging a branch, close/delete the feature branch.

## Issues & Planning

To file an issue, create a ticket in our GitHub projects.

## Commit Messages

Adopting a standard convention is a great practice, especially since the **OpenBeavs** code is public. We will use a simplified version of **Conventional Commits**. This convention makes the project history clean, aids in debugging, and can even be used to automatically generate changelogs.

The simple format to follow is:

### `<type>(<scope>): <subject>`

### Core Components

| Component | Purpose | Examples |
| :--- | :--- | :--- |
| **`<type>`** (Required) | A tag that indicates *what kind* of change this is. | `feat`, `fix`, `chore`, `docs`, `style` |
| **`(<scope>)`** (Optional) | The system part that the change affects. | `(frontend)`, `(backend-registry)`, `(auth)` |
| **`<subject>`** (Required) | A short, imperative description of the change (less than 50 characters). | "add MS SSO login route", "center chat bubble text" |

### Recommended `<type>` List

| Type | When to Use |
| :--- | :--- |
| **`feat`** | A new feature for the user (e.g., implementing persistent chat history). |
| **`fix`** | A bug fix (e.g., fixing a UI button alignment). |
| **`chore`** | Routine tasks that don't change production code (e.g., updating dependencies). |
| **`docs`** | Changes to documentation (e.g., `README.md`, comments). |
| **`style`** | Code formatting changes (e.g., semicolons, white-space). |
| **`refactor`** | A change that neither fixes a bug nor adds a feature. |

### Referencing and Closing Issues

To automatically close an issue tracked on your project board or GitHub repository (e.g., Issue **#22** for RBAC), you must use one of the following keywords followed by the issue number in the commit message **body** or **footer**.

---

## Code Style, Linting & Formatting

Backend lint uses `ruff check .` from `backend/`. Frontend `npm run lint` runs
ESLint without rewriting files, followed by Svelte/TypeScript checks. Keep
changes readable and limited to the feature being implemented.

## Testing

Run `pytest` from `backend/`, including its authorization tests. From `frontend/`,
run `npm run test`, `npm run build`, and `npm run test:e2e` after installing the
Playwright Chromium browser. Browser tests use API fixtures; a live Gemini
conversation is a separate acceptance check. See the setup guide for details.

## Definition of Done

A change is ready to merge when it meets its acceptance criteria,
passes the applicable checks below, and receives approval from at
least one team member other than the author. Code contributions count
as accepted work once they are merged into `main`.

### Required Checks and Implementation Plan

| Check | Enforcement | Implementation Owner | Target Sprint |
| :--- | :--- | :--- | :--- |
| Acceptance criteria are met | The author includes testing evidence in the PR, and the reviewer verifies it against the linked issue's acceptance criteria. | Faith Nambasa (Project Manager) | Sprint 1 |
| Automated tests pass | Planned required CI job: `tests`. Runs the automated test suite on each PR and blocks merging on failure. New or changed behavior includes appropriate tests; bug fixes include regression tests where practical. | Dean R Leon (Quality Owner) | Sprint 2 |
| Linting and formatting checks pass | Planned required CI job: `lint`. Checks code against the team's agreed rules and blocks merging on failure. | Dean R Leon (Quality Owner) | Sprint 1 |
| The application builds | Planned required CI job: `build`. Builds the application and blocks merging on failure. | Jiya Pradhan (AI Coordinator) | Sprint 1 |
| Security checks pass | Planned required CI job: `security`. Runs secret scanning and dependency vulnerability checks; detected secrets or high/critical dependency findings must be resolved before merging. | Jiya Pradhan (AI Coordinator) | Sprint 2 |
| Another member approves the change | Planned branch protection requires one approval from someone other than the author, resolved review conversations, and passing required CI checks before merging into `main`. | Faith Nambasa (Project Manager) | Sprint 1 |
| Documentation is current | The PR checklist requires updated setup, usage, or configuration documentation when affected, or an explanation of why no update is needed; the reviewer verifies this. | Pedro P Blanco Jaramillo (Documentation Owner) | Sprint 1 |

### Checks Before Automation Is Available

Until each automated gate is implemented, the author runs any available
equivalent checks locally and records the commands and results in the PR.
If a check cannot yet run, the author identifies the limitation and
provides relevant manual verification for the reviewer.

Missing automation must not be reported as a passing CI check.
The implementation owner tracks each planned gate in a GitHub issue
with its target sprint and adds a link to the enforcing CI configuration
in this section once it is available.

### Ownership and Maintenance

The Quality Owner maintains this Definition of Done and tracks the
implementation of its gates. Each named implementation owner sets up
their assigned checks. Every contributor remains responsible for
meeting the requirements for their changes.

The team reviews this Definition of Done at each sprint retrospective
and records any agreed changes.

## Contribution Norm

To ensure equitable distribution of effort and accountability across all sprints, our team commits to an explicit **contribution floor**:

> **The Floor:** Every team member must land at least **one (1) piece of accepted work per sprint**. 

### Work Classification & Acceptance Criteria
| Work Type | Where It Lives | What "Accepted" Means |
| :--- | :--- | :--- |
| **Code & Unit Tests** | GitHub Repository (`OpenBeavs`) via feature branch & PR | • Meets the Definition of Done (DoD).<br>• All automated test suites and linting checks pass.<br>• Approved by at least one teammate other than the author.<br>• Successfully merged into `main`. |
| **Architecture, ADRs & Technical Docs** | GitHub Repository (`docs/`, `ADR/`, or root `.md` files) | • Accurately documents design decisions, schemas, or guides.<br>• Reviewed and approved by the Quality Owner / team via PR. |
| **Sprint Management, Spikes & User Stories** | GitHub Projects Board & GitHub Issues | • Issue contains clear acceptance criteria.<br>• Tangible deliverable attached (e.g., research findings, spiked code demo).<br>• Verified by the Project Manager (PM) and moved to **Done**. |
| **Partner Deliverables & Client Specs** | Partner Meeting Notes / Shared Drive & Demo Sessions | • Demonstrated to project sponsor (**John V. Sweet**) during sprint reviews.<br>• Confirmed to meet sponsor requirements or acknowledged in meeting notes. |

## Pull Requests & Reviews

| Requirement | Details |
| :--- | :--- |
| **PR Template** | Mandatory. Must include: **Description**, **Related Issues**, **Testing Notes**, and **Screenshots/Video** (if UI). |
| **Checklist** | Items before 'Ready for Review': `[ ] Meets acceptance criteria`, `[ ] Tests pass`, `[ ] Docs updated`, `[ ] Self-reviewed`. |
| **Size Limits** | Target a maximum of **400-500 lines of code change**. Break larger changes into smaller, logical PRs. |
| **Reviewer Expectations** | Check for **functional correctness**, adherence to the **Tech Stack**, security concerns, and code style. |
| **Approval Rules** | Requires **one (1) approval** from another team member before merging to `main`. Cannot approve your own PR. |
| **Status Checks** | Required status checks: **All Unit Tests Pass** and **Code Linter/Style Check Passes**. |

---

## CI/CD

The [Checks workflow](.github/workflows/checks.yml) runs backend Ruff and all
backend tests, plus frontend lint/type checks, unit tests, build, and browser
tests on pushes and pull requests. The table above continues to track the
broader planned gates; secret scanning, dependency policy, and branch protection
are not supplied by this workflow.

## Security & Secrets

| Policy | Standard |
| :--- | :--- |
| **Vulnerability Reporting** | Immediately report security concerns to the team and create a **private, high-priority GitHub Issue**. |
| **Prohibited Patterns** | **NEVER hard-code secrets** (API keys, credentials) directly into the code base. |
| **Secrets Management** | All secrets must be loaded via environment variables (e.g., a `.env` file in `.gitignore` or GCP Secret Manager). |
| **AI Tool Confidentiality** | Code, architecture, partner requirements, and meeting content may be entered into AI tools. **Secrets such as environment variables (`.env`), API keys, signing secrets, and service credentials must NEVER be explicitly given to AI tools.** |
| **Dependency Updates** | Review and update dependencies at the start of every sprint using tools like `npm audit` or Dependabot. |
| **Scanning Tools** | Implement a linter and static analysis tool to check for common security errors. |

## Documentation Expectations

This document, along with all other documentation for the project, should be kept up to date as the project evolves.

## Release Process

Will be expaned upon as tech stack is finalized, but main should be kept as the primirary release, with branches containing development work. Pushes and merges to main should be tagged.

## Support & Contact

| Channel | Detail |
| :--- | :--- |
| **Maintainer Contact** | Primary channel for urgent team questions and conflict resolution is the Project Manager (PM). |
| **Sponsor Contact** | For project requirements or technical specs, contact **John V. Sweet** via his Email. |
| **Response Windows** | Aim for a 4-hour response window during standard school hours for urgent team messages. |
| **Sponsor Meetings** | Prepare agenda items for **Wednesday** sponsor meetings. Reserve emails for critical follow-up. |
| **Where to Ask** | **Technical:** Private team chat. **Scope:** Wednesday Sponsor Meeting. **Process:** CS Capstone Handbook. |
