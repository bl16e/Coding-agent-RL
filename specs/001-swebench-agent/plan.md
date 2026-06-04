# Implementation Plan: SWE-Bench Lite Coding Agent

**Branch**: `001-swebench-agent` | **Date**: 2026-06-04 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-swebench-agent/spec.md`

## Summary

Implement a Python CLI/library that runs one SWE-Bench Lite-style coding-agent
attempt against a prepared local workspace. The agent is limited to
`read_file`, `write_file`, `search_code`, and `run_tests`, records a complete
JSONL trajectory, generates `final.patch`, writes a run summary, and exports a
SWE-Bench-compatible prediction JSONL record.

The MVP does not provision SWE-Bench Docker environments. It assumes the task
workspace is already checked out and dependency setup is handled externally.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Standard library for filesystem, subprocess, JSONL,
argparse, difflib/subprocess, root `.env` parsing; OpenAI-compatible HTTP calls
isolated behind a model adapter; pytest for tests

**Storage**: Local filesystem artifacts under a caller-provided output
directory: `trajectory.jsonl`, `final.patch`, `summary.json`,
`prediction.jsonl`

**Testing**: pytest unit, contract, and integration tests with a deterministic
mock model backend

**Target Platform**: Local developer workstation or CI runner with a prepared
task workspace

**Project Type**: Single Python CLI/library project

**Performance Goals**: One task run must stream each accepted trajectory step to
disk before the next step starts; inspection of summary and trajectory must let
a reviewer identify outcome and error point in under 2 minutes

**Constraints**: All tool paths stay inside the task workspace; `run_tests`
executes only pre-declared commands; `write_file` accepts complete file content;
each run requires max steps, total runtime, and single-test timeout; real model
runs require `PROVIDER`, `MODEL`, `API_KEY`, and `BASE_URL` from root `.env` or
the process environment

**Scale/Scope**: One SWE-Bench Lite task per run; batch orchestration and
official Docker harness execution are out of scope for this feature

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Clarification gate: PASS. `/speckit-clarify` resolved trajectory format,
  allowed test commands, decision-summary granularity, write semantics, and run
  budgets. No unresolved clarification markers remain in the spec.
- Cohesion/coupling gate: PASS. Planned modules separate CLI parsing, run
  orchestration, model adapter, tool execution, trajectory persistence, patch
  generation, and SWE-Bench prediction export.
- Official behavior gate: PASS. Research records official SWE-Bench Lite
  dataset fields and prediction format. The MVP exports compatible predictions
  while explicitly deferring official Docker harness orchestration.

## Project Structure

### Documentation (this feature)

```text
specs/001-swebench-agent/
|-- plan.md
|-- research.md
|-- data-model.md
|-- quickstart.md
|-- contracts/
|   `-- cli-contract.md
|-- checklists/
|   `-- requirements.md
`-- spec.md
```

### Source Code (repository root)

```text
src/
`-- coding_agent/
    |-- __init__.py
    |-- cli.py
    |-- agent.py
    |-- models.py
    |-- budgets.py
    |-- workspace.py
    |-- model_backends/
    |   |-- __init__.py
    |   |-- base.py
    |   |-- mock.py
    |   `-- openai_compatible.py
    |-- tools/
    |   |-- __init__.py
    |   |-- read_file.py
    |   |-- write_file.py
    |   |-- search_code.py
    |   `-- run_tests.py
    |-- trajectory/
    |   |-- __init__.py
    |   |-- writer.py
    |   |-- patch.py
    |   `-- summary.py
    `-- swebench/
        |-- __init__.py
        `-- prediction.py

tests/
|-- contract/
|-- integration/
`-- unit/
```

**Structure Decision**: Use a single Python package with focused modules. CLI
commands delegate to services; tools do not call the model backend; trajectory
code only persists and exports run artifacts.

## Phase 0 Research

See [research.md](./research.md). All planning unknowns are resolved.

## Phase 1 Design

See [data-model.md](./data-model.md), [contracts/cli-contract.md](./contracts/cli-contract.md),
and [quickstart.md](./quickstart.md).

## Post-Design Constitution Check

- Clarification gate: PASS. Plan artifacts encode every accepted clarification.
- Cohesion/coupling gate: PASS. No planned module owns multiple unrelated
  responsibilities; no oversized file is required.
- Official behavior gate: PASS. Prediction export aligns with the official
  SWE-Bench harness prediction fields: `instance_id`, `model_name_or_path`, and
  `model_patch`.

## Complexity Tracking

No constitution violations require justification.

## Responsibility Audit

Source file audit on 2026-06-04 found the largest files are
`src/coding_agent/agent.py` at 222 lines and `src/coding_agent/models.py` at 220
lines. `agent.py` remains focused on AgentRun orchestration, tool dispatch, and
artifact finalization; concrete tool behavior stays in `src/coding_agent/tools/`.
`models.py` remains a shared data contract module with no service behavior.

No split is required now. Split triggers for future work:

- Move prompt/message construction out of `agent.py` if multi-turn model context
  grows beyond the current minimal request.
- Split `models.py` by domain if new mutable service behavior or provider-
  specific fields are added.
- Keep trajectory persistence in `trajectory/writer.py`, report rendering in
  `trajectory/summary.py`, and patch generation in `trajectory/patch.py`.
