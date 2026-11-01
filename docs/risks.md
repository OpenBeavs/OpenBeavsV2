# OpenBeavs V2 — Project Risk Register

**Last Updated:** October 30, 2026  
**Project:** OpenBeavs V2  
**Review Frequency:** Every sprint planning meeting

## Project Objective

Develop and deploy a reliable, secure multi-agent platform where users can interact with Chris, which coordinates requests and connects users to specialized AI agents through the Agent Registry.

## Risk Assessment

Risks are ranked using three levels:

- **High (H):** Likely to occur or significantly affect the project's functionality, security, or delivery.
- **Medium (M):** Possible to occur or cause moderate disruption.
- **Low (L):** Less likely to occur or have limited impact.

Each risk includes its likelihood and impact, an assigned owner, a response, and a trigger that indicates when action is needed.

Risks are listed in priority order. Owners are proposed based on current workstream responsibilities and should be confirmed by the team.

## Active Risks

### R-1: Authentication and Unauthorized Access

- **Category:** Technical
- **Likelihood:** Medium — The platform uses authentication across multiple components, and security controls must remain consistent as development continues.
- **Impact:** High — Unauthorized access could expose user information or allow changes to protected system functionality.
- **Owner:** Jiya (proposed; authentication integration)
- **Response:** Mitigate
- **Mitigation:** Review authentication and authorization across protected APIs, enforce role-based permissions where needed, and add tests for unauthorized requests.
- **Trigger:** A protected endpoint can be accessed without the required permissions, or authentication tests fail.

### R-2: Agent Registry Security

- **Category:** Technical
- **Likelihood:** Medium — The Registry interacts with agent metadata and potentially external endpoints, creating security concerns if agents are not properly validated.
- **Impact:** High — An untrusted or malicious agent could expose information, disrupt requests, or compromise the platform.
- **Owner:** Faith (Agent Registry)
- **Response:** Mitigate
- **Mitigation:** Validate agent information and endpoints, restrict access to internal/private network addresses, and ensure only approved agents are eligible for routing.
- **Trigger:** An unapproved agent becomes routable, an unsafe endpoint passes validation, or a Registry security test fails.

### R-3: Integration Between System Components

- **Category:** Technical
- **Likelihood:** High — Chris, the Agent Registry, database, and frontend are being developed and integrated across different workstreams.
- **Impact:** High — Incompatible APIs or unexpected changes could prevent requests from reaching the correct agents or returning responses.
- **Owner:** Jiya (proposed; Chris integration)
- **Response:** Mitigate
- **Mitigation:** Define API contracts between components, test integrations before merging, and use pull request reviews to identify breaking changes.
- **Trigger:** An integration test fails, an API contract changes without coordination, or an end-to-end request cannot complete.

### R-4: Cloud Deployment and Configuration

- **Category:** Technical
- **Likelihood:** Medium — The project depends on cloud infrastructure, environment configuration, and access to external services.
- **Impact:** High — Incorrect configuration or missing permissions could prevent deployment or cause service outages.
- **Owner:** John Sweet (proposed; infrastructure coordination)
- **Response:** Mitigate
- **Mitigation:** Document deployment steps, verify required environment variables and service permissions, test changes before production deployment, and maintain a rollback procedure.
- **Trigger:** A deployment fails, required cloud resources become inaccessible, or the deployed application cannot serve requests.

### R-5: Database Changes and Data Integrity

- **Category:** Technical
- **Likelihood:** Medium — The database is being cleaned up and integrated with updated application components.
- **Impact:** High — Schema incompatibilities or incorrect migrations could break existing functionality or result in lost or inconsistent data.
- **Owner:** Dean (Database)
- **Response:** Mitigate
- **Mitigation:** Review schema changes through pull requests, test migrations against non-production data, and document backup and rollback procedures.
- **Trigger:** A migration fails, existing queries stop working, or database tests identify inconsistent data.

### R-6: Insufficient Automated Testing

- **Category:** Technical
- **Likelihood:** Medium — The inherited codebase is being migrated and refactored, and test coverage may not be consistent across all components.
- **Impact:** High — Changes could introduce regressions that are not discovered until integration or deployment.
- **Owner:** Jiya (proposed; CI coordination)
- **Response:** Mitigate
- **Mitigation:** Run automated tests through CI on pull requests, add regression tests for important functionality, and verify that tests fail when covered behavior breaks.
- **Trigger:** A critical change is merged without passing CI, or a regression reaches the deployed application without being detected.

### R-7: External Services and AI Model Dependencies

- **Category:** Technical
- **Likelihood:** Medium — OpenBeavs depends on external AI services and cloud-hosted components that may experience failures, latency, or configuration changes.
- **Impact:** Medium — Users may experience slow responses or unavailable functionality.
- **Owner:** Jiya (proposed; Chris workflow)
- **Response:** Mitigate
- **Mitigation:** Handle API failures and timeouts, log service errors, and define fallback behavior when an external service is unavailable.
- **Trigger:** External service failures repeatedly prevent requests from completing or cause unacceptable response times.

### R-8: Requirements and Scope Changes

- **Category:** Business
- **Likelihood:** Medium — The project architecture and expected functionality are still being refined with the project partner.
- **Impact:** High — Major changes late in development could delay milestones or require reworking completed features.
- **Owner:** John Sweet (proposed; partner coordination)
- **Response:** Mitigate
- **Mitigation:** Confirm MVP priorities with the project partner, document agreed requirements, and evaluate the impact of proposed changes before implementation.
- **Trigger:** A newly requested feature affects the agreed MVP scope or threatens a sprint or deployment milestone.

### R-9: Team Availability and Knowledge Sharing

- **Category:** Team
- **Likelihood:** Medium — Development responsibilities are distributed across team members who also have academic and other commitments.
- **Impact:** Medium — Limited availability or knowledge concentrated in one workstream could delay integration and issue resolution.
- **Owner:** Team lead (confirm assigned person)
- **Response:** Mitigate
- **Mitigation:** Maintain documentation, review each other's pull requests, communicate blockers early, and ensure important setup and deployment procedures can be followed by more than one person.
- **Trigger:** A critical task is blocked because the responsible person is unavailable or another team member cannot reproduce the required process.

### R-10: User Experience and Agent Selection

- **Category:** Business
- **Likelihood:** Medium — The updated agent-selection workflow has not yet been fully validated with users.
- **Impact:** Medium — Users may receive irrelevant responses, experience delays, or have difficulty understanding how the platform works.
- **Owner:** Pedro (Frontend, proposed)
- **Response:** Mitigate
- **Mitigation:** Test the main user workflow, gather feedback from the project partner, and evaluate whether agent selection produces appropriate results.
- **Trigger:** User testing identifies repeated routing problems, confusing interactions, or unsuccessful requests.

## External Prerequisites and Approvals

The following dependencies need to be confirmed because they may affect deployment or integration.

| Prerequisite | Responsible person | Status / Action |
|---|---|---|
| Confirm production deployment target and infrastructure ownership | John Sweet / team lead | Confirm target and approval |
| Confirm required GCP permissions and service access | Infrastructure owner (TBD) | Verify access before deployment |
| Confirm any required institutional security or IT review | John Sweet / team lead | Determine whether approval is required |
| Confirm MVP functionality and integration expectations | John Sweet / team lead | Record agreed scope and decisions |

**Note:** Request dates have not yet been verified. For any prerequisite that requires external approval, record who made the request and the actual date once confirmed. Until then, assign a start-by date during sprint planning. Do not mark approvals as granted without confirmation.

## Risk Monitoring and Updates

The team will review this register during sprint planning and update it when project conditions change.

During each review, the team should:

1. Check whether any risk triggers have occurred.
2. Reassess likelihood and impact where necessary.
3. Update mitigation actions and owners.
4. Move risks that have become actual problems to the sprint board as issues.
5. Close risks that have been resolved, keeping a short record of their resolution.

Risks should also be updated when a pull request introduces a significant change to authentication, database schemas, agent routing, or deployment.

## Closed Risks

No risks have been formally closed in this register yet. Resolved risks will be recorded here with the resolution date and relevant issue or pull request link.
