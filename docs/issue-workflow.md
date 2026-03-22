# Issue Workflow Guide

This document explains how to use the four Issue types in this repository (**Epic → Feature → Task → Bug**), how to break work down, how to write acceptance criteria, and how to link related issues.

---

## Table of Contents

1. [Overview of Issue Types](#overview-of-issue-types)
2. [When to Use Each Type](#when-to-use-each-type)
3. [Recommended Granularity & Breakdown Method](#recommended-granularity--breakdown-method)
4. [Writing Acceptance Criteria (AC)](#writing-acceptance-criteria-ac)
5. [Definition of Done (DoD)](#definition-of-done-dod)
6. [Linking Parent–Child Issues](#linking-parentchild-issues)
7. [Labels Reference](#labels-reference)

---

## Overview of Issue Types

| Type    | Template prefix | Purpose |
|---------|----------------|---------|
| **Epic**    | `[EPIC]`   | A large strategic initiative that spans multiple sprints or milestones. |
| **Feature** | `[FEAT]`   | A user-facing or system capability that can be shipped as a unit of value. |
| **Task**    | `[TASK]`   | A concrete implementation step, completable in hours to 1–2 days. |
| **Bug**     | `[BUG]`    | Something that is broken or behaves differently from the spec. |

---

## When to Use Each Type

### Epic
Use an Epic when:
- The work is too large to deliver in a single sprint.
- Multiple features or cross-functional teams are involved.
- You need a single place to track overall progress, success metrics, and rollout plan.

**Example:** "Rewrite authentication system to support SSO"

### Feature
Use a Feature when:
- The work delivers a self-contained, demonstrable capability to a user or system.
- It can reasonably be completed within one sprint.
- It can be validated against a clear acceptance criteria checklist.

**Example:** "Add email + OTP login option"

### Task
Use a Task when:
- The work is a specific implementation step derived from a Feature or Epic.
- It can be assigned to one developer and completed in hours to a couple of days.
- It maps 1:1 to a pull request.

**Example:** "Implement `POST /auth/otp/send` endpoint"

### Bug
Use a Bug when:
- Existing behavior diverges from the documented or expected behavior.
- A regression has been introduced.
- Users are experiencing errors or incorrect output.

**Example:** "OTP verification returns 500 when email contains a `+` character"

---

## Recommended Granularity & Breakdown Method

### Epic → Feature → Task hierarchy

```
Epic: Rewrite Authentication (weeks / milestone)
│
├── Feature: Email + OTP login (days / sprint)
│   ├── Task: Implement POST /auth/otp/send
│   ├── Task: Implement POST /auth/otp/verify
│   └── Task: Add OTP rate-limiting middleware
│
└── Feature: SSO with Google OAuth (days / sprint)
    ├── Task: Register OAuth app & store client credentials
    ├── Task: Implement OAuth callback handler
    └── Task: Add user-profile sync on first login
```

### Sizing guidelines

| Type    | Typical duration | Signs it's too big |
|---------|-----------------|-------------------|
| Task    | 2 h – 2 days    | Has more than one PR's worth of changes |
| Feature | 2 – 5 days      | AC list has more than 8–10 items |
| Epic    | 2+ weeks        | Has more than 10 Features |

> **Rule of thumb:** If a Task keeps growing, split it into multiple Tasks and group them under a Feature. If a Feature keeps growing, consider promoting it to an Epic.

### How to break down an Epic

1. **Start with outcomes:** List the user-facing or system outcomes you need (these become Features).
2. **For each Feature, list implementation steps** (these become Tasks).
3. **Create the Epic issue first**, then create Feature issues and paste their numbers in the Epic's "Planned Breakdown" section.
4. **Create Task issues** from within each Feature issue and link back to the Feature.

---

## Writing Acceptance Criteria (AC)

Acceptance Criteria are the conditions that must be **verifiably true** before an issue can be closed. Good AC is:

- **Observable**: you can check it without reading code ("The page loads in < 2 s on a 4G connection").
- **Unambiguous**: only one interpretation is possible.
- **Testable**: an automated test or a manual test step can prove it.

### AC format (recommended)

Use imperative, present-tense statements as a checklist:

```markdown
## Acceptance Criteria

- [ ] `POST /auth/otp/send` returns `200 OK` and sends an email when the address is valid.
- [ ] `POST /auth/otp/send` returns `422` with a clear error message when the email is malformed.
- [ ] OTP codes expire after 10 minutes; a subsequent verify call returns `410 Gone`.
- [ ] Rate-limit: maximum 3 OTP requests per email address per 15 minutes; excess returns `429`.
- [ ] All new endpoints are covered by integration tests (≥ 90 % branch coverage).
- [ ] API documentation (OpenAPI) is updated to reflect the new endpoints.
```

### Epic-level AC example

For an Epic, AC is higher-level and focuses on business outcomes:

```markdown
## Acceptance Criteria

- [ ] All child Features are delivered and their own ACs are green.
- [ ] Existing login methods (username/password) still work with no regression.
- [ ] Error rate for the auth service < 0.1 % (measured over 7 days post-launch).
- [ ] On-call runbook is updated to cover the new authentication flow.
- [ ] Feature flag is removed; authentication is fully rolled out to 100 % of users.
```

---

## Definition of Done (DoD)

The **Definition of Done** is a shared checklist that applies to **every Task** before it can be merged or closed. It lives on the Task issue and is also enforced at PR review time.

### Recommended DoD for Tasks

```markdown
## Definition of Done

- [ ] Code implemented and self-reviewed
- [ ] Unit / integration tests added or updated (all pass in CI)
- [ ] CI pipeline is green (lint + build + test)
- [ ] No new security warnings introduced
- [ ] Documentation updated (README, API spec, inline comments) if applicable
- [ ] PR is linked to this issue (`Closes #<issue>` in the PR description)
- [ ] PR reviewed and approved by at least one peer
```

### Feature-level DoD additions

In addition to the Task DoD, a Feature is done when:

- All child Task issues are closed.
- End-to-end or acceptance tests covering the Feature's AC are passing.
- The feature has been demo'd or reviewed by a stakeholder / product owner.
- Any required feature flags, rollout config, or migration scripts are in place.

---

## Linking Parent–Child Issues

GitHub does not have a native "parent/child" relationship for issues, but you can track hierarchy effectively using the following conventions.

### 1. Reference issues by number

Mention an issue number anywhere in a comment or description to create a hyperlink:

```markdown
This task is part of #42 (Feature: OTP login).
See also: #38 (Epic: Auth rewrite).
```

### 2. Task list in the parent issue

Add a task list to the Epic or Feature's "Planned Breakdown" section. GitHub automatically tracks completion percentage:

```markdown
## Planned Breakdown

Features:
- [x] #55 Email + OTP login
- [ ] #56 SSO with Google OAuth

Tasks (under #55):
- [x] #60 Implement POST /auth/otp/send
- [x] #61 Implement POST /auth/otp/verify
- [ ] #62 Add OTP rate-limiting middleware
```

### 3. Closing keywords in Pull Requests

In the PR description, use a closing keyword so the issue is automatically closed when the PR merges:

```markdown
Closes #62
Part of #55
```

> Supported keywords: `Closes`, `Fixes`, `Resolves` (case-insensitive).

### 4. Paste full URLs for cross-repo references

When referencing issues in a different repository, paste the full URL:

```markdown
Blocked by: https://github.com/org/other-repo/issues/99
```

---

## Labels Reference

Use labels to categorize, prioritize, and track the status of issues.

### Type labels

| Label          | Color     | Usage |
|---------------|-----------|-------|
| `type:epic`    | `#6e40c9` | Applied automatically by the Epic template |
| `type:feature` | `#0075ca` | Applied automatically by the Feature template |
| `type:task`    | `#e4e669` | Applied automatically by the Task template |
| `type:bug`     | `#d73a4a` | Applied automatically by the Bug template |

### Priority labels

| Label          | Color     | Meaning |
|---------------|-----------|---------|
| `priority:p0`  | `#b60205` | Critical – must fix immediately (production down) |
| `priority:p1`  | `#e11d48` | High – fix in current sprint |
| `priority:p2`  | `#f97316` | Medium – fix in next sprint |
| `priority:p3`  | `#94a3b8` | Low – fix when capacity allows |

### Status labels

| Label                  | Color     | Meaning |
|-----------------------|-----------|---------|
| `status:blocked`       | `#ee0701` | Cannot proceed; waiting on dependency or decision |
| `status:ready`         | `#0e8a16` | Refined, estimated, and ready to be picked up |
| `status:in-progress`   | `#1d76db` | Actively being worked on |
| `status:needs-review`  | `#e4e669` | Implementation done; awaiting code review or stakeholder sign-off |
