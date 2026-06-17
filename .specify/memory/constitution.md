<!--
Sync Impact Report
Version change: 1.0.0 -> 1.1.0
Modified principles:
- III. Official-Behavior Consistency -> III. Source-Backed Behavior
- Added IV. Test Integrity, Not Test Gaming
Added sections:
- None
Removed sections:
- None
Templates requiring updates:
- UPDATED .specify/templates/plan-template.md
- UPDATED .specify/templates/spec-template.md
- UPDATED .specify/templates/tasks-template.md
- N/A .specify/templates/commands/*.md not present
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

### III. Source-Backed Behavior
Feature behavior, API usage, CLI usage, configuration semantics, and integration
patterns MUST be derived from the relevant official documentation, official
samples, upstream behavior, or existing project contracts for the selected
technology. Plans MUST name the sources used before implementation starts. If
the official source is ambiguous or unavailable, the plan MUST document the
source checked, the uncertainty, and the user decision before implementation
proceeds.

Rationale: source-backed implementation reduces compatibility risk and prevents
project-specific behavior from drifting away from supported patterns.

### IV. Test Integrity, Not Test Gaming
Implementation MUST satisfy the intended behavior, not merely the current test
fixtures. Code MUST NOT branch on known test names, instance IDs, expected
outputs, sample-only values, or hardcoded lookup tables solely to make tests
pass. Static mappings are permitted only when they represent stable domain
metadata from an official source or existing project contract, and the source
MUST be cited in the plan or code-adjacent documentation.

Rationale: tests are evidence about required behavior, not a substitute for the
behavior itself. Test-shaped implementations create false confidence and fail
outside narrow fixtures.

## Engineering Constraints

- Specifications MUST mark unclear functional requirements with
  `NEEDS CLARIFICATION` instead of inventing behavior.
- Plans MUST name the official documentation, official samples, upstream
  behavior, or existing project contracts used for technology decisions.
- Plans MUST identify module boundaries and note any file expected to carry more
  than one responsibility.
- Plans MUST identify any static mapping or fixture-like data used by the
  implementation and cite why it is domain metadata rather than a test shortcut.
- Tasks MUST include refactoring, file-splitting, or boundary-cleanup work when
  a feature would otherwise create broad coupling or oversized files.
- Tasks MUST include a review step that checks implementation for hardcoded test
  fixture logic, sample-only branches, and undocumented lookup tables.

## Development Workflow

1. Start each feature by separating known requirements from open questions.
2. Ask the user for clarification before encoding unclear behavior as scope.
3. During planning, verify selected library, API, CLI, and framework usage
   against official documentation, official samples, upstream behavior, or
   existing project conventions.
4. During planning, record static mappings and fixture-like data with their
   source and explain why each is valid domain metadata.
5. During implementation, keep each module focused on one responsibility and
   record justified exceptions in the plan.
6. During implementation, avoid test-specific branches and replace
   fixture-shaped shortcuts with general behavior derived from the cited source.
7. During review, check that generated specs, plans, tasks, and code comply with
   all core principles before implementation is considered ready.

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

**Version**: 1.1.0 | **Ratified**: 2026-06-04 | **Last Amended**: 2026-06-17
