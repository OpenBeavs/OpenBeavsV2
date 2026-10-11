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

List prerequisites, setup steps, environment variables/secrets handling, and how to run the app locally.

### Prerequisites

* [Docker](https://www.docker.com/)
* [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)
* [Node.js and npm](https://nodejs.org/)

### Running the app Locally

Systems from the old repo will be migrated to this repo, however, their documentation iss outdated. Running the app locally will not be possible until development work is done.

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

Automated linting and formatters are TBD, generally, code should be readable, maintainable, and follow the style of the existing codebase.

## Testing

Unit tests will be implemented using whatever testing framework is decided on. (Expanded on when tech stack is finalized.)

## Definition of Done

A change must have all of its test pass, along with review from other project members before it is merged. (This will change as the project evolves)

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

TBD (will either be done on GitHub Actions or on Google Cloud Run)

## Security & Secrets

| Policy | Standard |
| :--- | :--- |
| **Vulnerability Reporting** | Immediately report security concerns to the team and create a **private, high-priority GitHub Issue**. |
| **Prohibited Patterns** | **NEVER hard-code secrets** (API keys, credentials) directly into the code base. |
| **Secrets Management** | All secrets must be loaded via environment variables (e.g., a `.env` file in `.gitignore` or GCP Secret Manager). |
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