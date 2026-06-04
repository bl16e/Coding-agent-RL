<!--
Sync Impact Report
Version change: template -> 1.0.0
Modified principles:
- Template principle slot 1 -> I. Clarify Before Committing
- Template principle slot 2 -> II. Cohesive, Decoupled Code
- Template principle slot 3 -> III. Official-Behavior Consistency
Added sections:
- Engineering Constraints
- Development Workflow
Removed sections:
- Placeholder principle slots 4 and 5
Templates requiring updates:
- ✅ .specify/templates/plan-template.md
- ✅ .specify/templates/spec-template.md
- ✅ .specify/templates/tasks-template.md
- ⚠ .specify/templates/commands/*.md not present
Follow-up TODOs:
- None
-->
# coding_agent Constitution

## Core Principles

### I. Clarify Before Committing
Requirements MUST NOT be guessed when user intent, scope, acceptance criteria,
external dependencies, or tradeoffs are unclear. Work MUST stop for a targeted
clarification question, or the uncertainty MUST be recorded as an explicit
`NEEDS CLARIFICATION` item before planning continues. Assumptions are permitted
only when they are stated, low-risk, and traceable to existing project context.

Rationale: incorrect assumptions create hidden rework and make generated specs,
plans, and tasks unreliable.

### II. Cohesive, Decoupled Code
Code MUST keep related behavior close together and separate unrelated
responsibilities behind small, explicit interfaces. Features MUST avoid
unnecessary coupling across modules, global state, broad helper layers, and
files that grow beyond a focused responsibility. Any large file or cross-module
dependency introduced by a plan MUST be justified in the complexity tracking
section with the simpler alternative considered.

Rationale: high cohesion and low coupling keep future changes local, testable,
and easier to review.

### III. Official-Behavior Consistency
Feature behavior, API usage, CLI usage, configuration semantics, and integration
patterns MUST match the relevant official documentation or upstream behavior for
the selected technology. If the official source is ambiguous or unavailable, the
plan MUST document the source checked, the uncertainty, and the user decision
before implementation proceeds.

Rationale: matching official usage reduces compatibility risk and prevents
project-specific behavior from drifting away from supported patterns.

## Engineering Constraints

- Specifications MUST mark unclear functional requirements with
  `NEEDS CLARIFICATION` instead of inventing behavior.
- Plans MUST name the official sources or existing project contracts used for
  technology decisions.
- Plans MUST identify module boundaries and note any file expected to carry more
  than one responsibility.
- Tasks MUST include refactoring, file-splitting, or boundary-cleanup work when
  a feature would otherwise create broad coupling or oversized files.

## Development Workflow

1. Start each feature by separating known requirements from open questions.
2. Ask the user for clarification before encoding unclear behavior as scope.
3. During planning, verify selected library, API, CLI, and framework usage
   against official documentation or existing project conventions.
4. During implementation, keep each module focused on one responsibility and
   record justified exceptions in the plan.
5. During review, check that generated specs, plans, and tasks comply with all
   core principles before implementation is considered ready.

## Governance

This constitution supersedes conflicting project practices for Spec Kit
generated specifications, plans, tasks, and implementation guidance.

Amendments require an explicit user request or approval, a Sync Impact Report,
and updates to affected templates or runtime guidance files in the same change.
Versioning follows semantic versioning: MAJOR for incompatible governance or
principle redefinitions, MINOR for added principles or materially expanded
guidance, and PATCH for clarifications that do not change required behavior.

Compliance review is mandatory at the plan, task, and implementation review
stages. Any violation MUST be documented in the plan's complexity tracking
section with the reason, risk, and simpler alternative considered.

**Version**: 1.0.0 | **Ratified**: 2026-06-04 | **Last Amended**: 2026-06-04
