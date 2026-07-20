# SWE-smith Current-Agent SFT Pipeline Design

## Summary

Build a SWE-smith training-trajectory pipeline that uses the current
`coding_agent` agent runner instead of SWE-agent, while following SWE-smith's
official dataset, runtime profile, image/container, evaluation, and
resolved-only training-data collection semantics as closely as possible.

The intended workflow is:

```text
SWE-smith subset
-> SWE-smith official profile/image/container
-> coding_agent solves the task
-> SWE-smith official evaluation determines resolved status
-> resolved trajectories are exported to SFT JSONL
```

The first version does not integrate torchtune, Modal, sglang serving, or model
training. It produces a training dataset that can be consumed by those systems.

## Goals

- Run SWE-smith generated task instances with the current `coding_agent` agent
  loop, tool executor, trajectory writer, prediction writer, and artifact
  contract.
- Use SWE-smith's official repository profiles and container assumptions for
  task runtime setup instead of translating SWE-smith metadata into the current
  SWE-Bench Lite runtime metadata.
- Use SWE-smith official evaluation semantics to determine whether a generated
  patch resolves an instance.
- Export only resolved trajectories to OpenAI-style chat JSONL for SFT.
- Support reproducible local subset files as the primary input, with optional
  helper support for creating such files from the Hugging Face
  `SWE-bench/SWE-smith` dataset.

## Non-Goals

- Do not run SWE-agent or depend on SWE-agent trajectory formats.
- Do not replace the existing `src/coding_agent/swebench/` official SWE-Bench
  Lite runtime.
- Do not copy SWE-smith profile metadata into
  `src/coding_agent/swebench/repo_specs.py`.
- Do not export unresolved trajectories for SFT.
- Do not add training execution, Modal upload, torchtune launch, or sglang
  serving in the first version.
- Do not silently fall back to guessed runtime metadata when SWE-smith profiles,
  mirrors, images, or containers are unavailable.

## Architecture

Add a new integration namespace:

```text
src/coding_agent/swesmith/
|-- __init__.py
|-- dataset.py
|-- runtime.py
|-- run.py
|-- evaluate.py
`-- export_sft.py
```

This keeps SWE-smith integration separate from the existing SWE-Bench Lite
runtime refactor. The new namespace is a bridge between SWE-smith official
harness behavior and the current `coding_agent` agent runner.

### `dataset.py`

Responsibilities:

- Load SWE-smith subset files in `.json` and `.jsonl` formats.
- Validate required instance fields, including at minimum `instance_id`,
  `problem_statement`, and the fields required by SWE-smith profile/evaluation
  code.
- Optionally create a local subset file from `SWE-bench/SWE-smith` by applying
  user-provided or built-in criteria.

The default `run-subset` path accepts only a local subset file. Hugging Face
loading is exposed through `create-subset` so actual solving runs remain
reproducible and do not depend on network access.

### `runtime.py`

Responsibilities:

- Import SWE-smith from the configured reference checkout.
- Resolve the SWE-smith profile with
  `swesmith.profiles.registry.get_from_inst(instance)`.
- Create the task container using SWE-smith's official profile/runtime path.

The preferred implementation calls `RepoProfile.get_container(instance)` from
SWE-smith where possible. If a small wrapper is needed to capture metadata, it
must preserve the same semantics: profile image, SWE-smith Docker workdir/user,
container start, and `git checkout <instance_id>`.

Missing SWE-smith imports, missing profiles, missing images, failed image
pull/build, missing mirrors, and checkout failures are input/runtime failures.
The integration must not fall back to the current project's SWE-Bench Lite
`build_adapted_testspec` path.

### `run.py`

Responsibilities:

- Run one or more SWE-smith instances with the current `coding_agent` agent.
- Connect `ContainerToolExecutor` to the SWE-smith-created container and
  official repository workdir.
- Use the SWE-smith instance `problem_statement` as the task prompt.
- Persist the existing artifact contract per instance:
  `trajectory.jsonl`, `trajectory.json`, `summary.json`, `final.patch`,
  `prediction.jsonl`, and `sandbox.json`.
- Write a batch-level predictions file suitable for SWE-smith official
  evaluation.

The agent runner remains host-owned. SWE-smith owns the repository environment
and benchmark validation semantics.

### `evaluate.py`

Responsibilities:

- Invoke SWE-smith official evaluation semantics for a subset and predictions
  file.
- Prefer the official command-compatible path:

```bash
python -m swesmith.harness.eval \
  --dataset_path <subset> \
  --predictions_path <predictions> \
  --run_id <run_id> \
  --workers <workers> \
  --timeout <timeout>
```

- Preserve the official output structure under
  `logs/run_evaluation/<run_id>/`, including per-instance `report.json` and the
  batch report.
- Support an in-process wrapper only if it produces equivalent report semantics
  and locations.

Resolved status is read from SWE-smith report data, not inferred from local test
commands or agent self-validation.

### `export_sft.py`

Responsibilities:

- Read run artifacts and SWE-smith eval reports.
- Select only instances whose SWE-smith report has `resolved: true`.
- Convert current `coding_agent` trajectories into OpenAI-style chat JSONL:

```json
{"messages":[{"role":"system","content":"..."},{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}
```

- Support an XML function-call style inspired by SWE-smith's
  `transform_traj_xml`, adapted to the current `coding_agent` tool schema and
  trajectory events.
- Include useful metadata fields where stable, such as `instance_id`,
  `resolved`, `model`, `traj_id`, and `patch`.

The exporter consumes current project artifacts, not SWE-agent `.traj` files.

## CLI Surface

Add a `swesmith` command group:

```bash
coding-agent swesmith create-subset \
  --out logs/experiments/subset0.json \
  --min-fail-to-pass 2 \
  --max-fail-to-pass 5 \
  --require-pr

coding-agent swesmith run-subset \
  --subset logs/experiments/subset0.json \
  --output-dir runs/swesmith/<run_id> \
  --model-name <model> \
  --workers 1

coding-agent swesmith eval \
  --subset logs/experiments/subset0.json \
  --predictions runs/swesmith/<run_id>/preds.json \
  --run-id <run_id> \
  --workers 10 \
  --timeout 240

coding-agent swesmith export-sft \
  --runs runs/swesmith/<run_id> \
  --eval-dir logs/run_evaluation/<run_id> \
  --out trajectories_sft/<run_id>.xml.jsonl \
  --style xml
```

`run-subset` should write a batch prediction file named `preds.json` or
`preds.jsonl`. The chosen format must be accepted by SWE-smith official
evaluation. The command should also write a batch summary with per-instance
status and artifact paths.

## Data Flow

1. `create-subset` optionally loads `SWE-bench/SWE-smith`, filters instances,
   and writes a local subset file.
2. `run-subset` reads the subset file and validates instance records.
3. For each instance, `runtime.py` resolves the SWE-smith profile and creates a
   SWE-smith official task container.
4. `run.py` executes current `coding_agent` against that container and writes
   per-instance artifacts.
5. `run.py` extracts the final patch and writes a prediction record.
6. `eval` calls SWE-smith official evaluation with the subset and predictions.
7. `export-sft` reads evaluation reports, keeps resolved instances only, and
   writes SFT JSONL.

## Error Handling

- If SWE-smith cannot be imported, fail with setup guidance that points to the
  configured reference checkout and `PYTHONPATH`.
- If no SWE-smith profile is registered for an instance, fail that instance
  before agent execution.
- If the profile image cannot be found or pulled, expose the SWE-smith error and
  point the user to SWE-smith environment/image preparation.
- If container creation or checkout fails, mark the instance as runtime error
  and do not run the agent.
- If the agent produces no patch, write an empty `model_patch` prediction and
  let SWE-smith evaluation mark it unresolved.
- If evaluation times out or fails, preserve SWE-smith logs and mark evaluation
  status explicitly.
- If artifact persistence fails, return the same artifact-error behavior used by
  existing benchmark runs.

## Testing

Automated tests use fakes for SWE-smith and Docker boundaries by default.

Unit coverage:

- subset loading and validation for `.json` and `.jsonl`
- profile lookup and container metadata through fake SWE-smith registry/profile
- prediction file generation in SWE-smith-compatible shape
- evaluation report reading and resolved filtering
- SFT exporter output format and unresolved exclusion

Integration coverage:

- fake end-to-end `run-subset -> eval report -> export-sft`
- artifact paths and batch summary consistency
- import/setup errors when SWE-smith is unavailable

Manual or opt-in coverage:

- real `Reference/SWE-smith` import
- real profile container creation
- real SWE-smith `python -m swesmith.harness.eval`
- one small real subset producing predictions and resolved-only SFT output

No default automated test should require Docker, Hugging Face network access,
GitHub mirrors, or SWE-smith image downloads.

## Implementation Notes

- The first implementation should add the new `swesmith` namespace and CLI
  without refactoring existing SWE-Bench Lite runtime modules.
- If the `Reference/SWE-smith` checkout remains vendored/untracked, commands
  should accept a reference path or environment variable so the integration can
  import it explicitly.
- The SFT exporter should be deterministic: stable instance ordering, stable
  JSON key order where practical, and stable `traj_id` generation from run path
  plus instance id.
- Batch solving can start with `workers=1`; parallelism may be added once
  shared SWE-smith image/container behavior is verified.
- Any future support for non-Python SWE-smith profiles should be driven by the
  official SWE-smith profile registry, not by new project-local metadata.
