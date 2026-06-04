# Research: SWE-Bench Lite Coding Agent

## Decision: Use a local prepared workspace for MVP

**Rationale**: The spec targets one task per run and requires four repository
tools plus trajectory output. A prepared workspace keeps the MVP focused on
agent behavior while still producing patches compatible with SWE-Bench
evaluation.

**Alternatives considered**:
- Embed official Docker harness orchestration: stronger environment parity but
  significantly larger scope and dependency surface.
- Batch runner over SWE-Bench Lite: useful later, but not required for one-run
  MVP.

## Decision: Export SWE-Bench-compatible prediction JSONL

**Rationale**: Official SWE-Bench harness predictions include
`instance_id`, `model_name_or_path`, and `model_patch`, and prediction paths may
be `.json` or `.jsonl`. The agent will write `prediction.jsonl` with one line
per run so official evaluation can consume the generated patch later.

**Official sources**:
- https://www.swebench.com/SWE-bench/guides/datasets/
- https://www.swebench.com/SWE-bench/api/harness/

**Alternatives considered**:
- Only write `final.patch`: easier to inspect but not directly compatible with
  harness prediction input.
- Write custom JSON only: richer metadata but requires an export step anyway.

## Decision: Keep run_tests limited to pre-declared commands

**Rationale**: Pre-declared commands reduce security risk, keep test behavior
auditable, and make failures reproducible. Rejected commands are still recorded
as trajectory events.

**Alternatives considered**:
- Agent-selected arbitrary commands: flexible but unsafe and hard to reproduce.
- Only official tests: too narrow for prepared local workspaces and smoke tests.

## Decision: Store trajectory as JSONL plus final patch and summary

**Rationale**: JSONL supports incremental durable writes and chronological
inspection. `final.patch` supports SWE-Bench-style evaluation, and
`summary.json` gives reviewers a compact outcome view.

**Alternatives considered**:
- Single JSON document: simpler final artifact but weaker crash durability.
- Markdown report: readable but less suitable for automated checks.

## Decision: Use complete-file writes

**Rationale**: `write_file(path, content)` has deterministic semantics and keeps
the tool interface simple. The system generates `final.patch` by comparing
before-and-after workspace state.

**Alternatives considered**:
- Tool-applied unified diffs: closer to patch workflows but harder to validate
  and recover.
- Supporting both modes: more flexible but unnecessary for MVP.

## Decision: Use OpenAI-compatible backend behind an adapter

**Rationale**: An OpenAI-compatible adapter can support hosted models or local
compatible servers while tests use a deterministic mock backend. The agent loop
depends only on a small model interface.

Configuration is loaded from root-level environment variables:
`PROVIDER`, `MODEL`, `API_KEY`, and `BASE_URL`. The adapter treats these as the
single source of truth for non-mock runs and reports missing values before an
AgentRun starts.

**Alternatives considered**:
- Provider-specific client only: faster initially but high coupling.
- Mock-only MVP: easier to test but does not satisfy real agent usage.

## Decision: Python 3.11+ CLI/library

**Rationale**: The project currently has no source code. Python keeps the CLI,
filesystem tools, subprocess test execution, and pytest coverage lightweight.

**Alternatives considered**:
- Web service: unnecessary for local benchmark runs.
- Shell scripts only: insufficient structure for trajectory and tool contracts.
