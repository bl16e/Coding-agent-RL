# Research: Agent Runtime Environment Refactor

## Decision: Use an adapted TestSpec as the runtime contract

Create an internal adapted task spec that captures task identity, repository,
version, base revision, repo path, environment name, validation sets,
test patch, setup scripts, eval script, image keys, platform, and runtime
lineage.

**Rationale**: The reference plan and SWE-Bench harness both center runtime
preparation around task specs. An internal adaptation keeps this project aligned
with official-style behavior without importing the local `SWE-bench/` checkout
at runtime.

**Alternatives considered**:

- Keep using repo-keyed `BaseImage` registry for benchmark runs: rejected
  because it cannot express env/instance image layering or source-backed
  repo/version metadata.
- Import `SWE-bench` harness modules directly: rejected because the local
  checkout is a reference only and must not be a runtime dependency.
- Generate behavior directly from tests: rejected by the constitution and by
  the user's no-test-gaming instruction.

## Decision: Treat source-backed metadata as required domain data

Repo/version metadata for the supported SWE-Bench Lite repository set must come
from upstream SWE-Bench harness constants, official samples, official docs, or
existing project contracts. Missing metadata fails before agent execution.

**Rationale**: Runtime setup and validation commands are benchmark semantics.
Guessing them or deriving them from current tests would create unsupported
behavior and brittle implementations.

**Alternatives considered**:

- Fill missing entries with compact test fixtures: rejected because it would
  make fixture coverage look like real support.
- Allow best-effort generated defaults: rejected because setup and validation
  commands vary by repo/version.
- Fall back to legacy registry templates: rejected because old benchmark
  runtime operations are not preserved as compatibility paths.

## Decision: First support the core SWE-Bench Lite repository set

The first supported scope is the core SWE-Bench Lite repository set with
source-backed repo/version metadata. Unknown repositories or missing metadata
produce explicit pre-agent input errors.

**Rationale**: This matches the user's requested whole-flow refactor while
keeping implementation tractable. It also gives clear acceptance tests for both
supported and unsupported paths.

**Alternatives considered**:

- One representative task only: rejected because it would not validate the
  metadata model or reusable runtime layering.
- All SWE-Bench tasks: rejected because it broadens scope beyond SWE-Bench Lite
  and increases metadata coverage risk.
- Framework only with no runnable task: rejected because it would not satisfy
  the two user-visible `prepare` and `run` operations.

## Decision: New benchmark runs use official-style image graph by default

New benchmark runtime commands resolve images through adapted task specs:
base image, environment image, and instance image. The build/check order is
base -> env -> instance.

**Rationale**: The reference plan and upstream harness image behavior both use
layered images. This lets reusable layers be shared while preserving a clean,
task-specific starting point.

**Alternatives considered**:

- One image per repository: rejected because it loses env-script hashing and
  task-specific image lineage.
- One image per task only: rejected because it prevents reuse of common runtime
  layers.
- Continue creating containers from legacy base images: rejected for default
  benchmark runs.

## Decision: Use the local SWE-Bench Lite data as the first audit scope

The first supported source-backed runtime metadata scope is the two local
SWE-Bench Lite parquet files under `data/`. Applying the upstream `TestSpec`
image-key rules to those files produces 323 supported rows, 18 repositories,
81 repo/version pairs, one base image key, 45 environment image keys, and 323
instance image keys with zero generation failures.

The detailed audit inventory is recorded in
[runtime-image-audit.md](./runtime-image-audit.md). It lists the dataset files,
source harness files, supported repo/version pairs, the base image key, all
environment image keys, and the deterministic instance image key rule.

**Rationale**: This converts the vague "core SWE-Bench Lite repository set"
scope into an auditable local dataset scope while preserving the constitution's
distinction between source-backed domain metadata and fixture-shaped shortcuts.

**Alternatives considered**:

- Embed a hand-written per-instance image table in production code: rejected
  because instance image keys are deterministically derived from `instance_id`.
- Treat all upstream SWE-Bench repositories as supported immediately: rejected
  because this feature's current data source is the local SWE-Bench Lite data.
- Store only example image keys in the plan: rejected because it would not
  satisfy the source-backed audit requirement for repo/version coverage.

## Decision: `prepare` fails on missing images unless `--build-missing` is explicit

`prepare` checks required Base/Env/Instance images before any agent execution.
Missing images fail before agent execution unless the developer supplies an
explicit build-missing option. `run` never builds images and instead requires a
matching prepared environment from the active index.

**Rationale**: Image creation is expensive and environment-changing. Explicit
opt-in keeps runtime behavior predictable and keeps pre-agent failures
actionable.

**Alternatives considered**:

- Always build missing images: rejected because it changes runtime state
  implicitly and can hide setup problems.
- Never build images: rejected because `prepare` must be able to create missing
  runtime layers when explicitly requested.

## Decision: Keep host-orchestrated agent solving

Model calls, budgets, trajectory persistence, summary writing, prediction
export, and final artifact orchestration remain on the host. Repository file
reads, edits, searches, validation attempts, and final diff extraction happen
inside the prepared task environment.

**Rationale**: This preserves the existing agent architecture and artifact
contract while moving task code execution into the prepared environment.

**Alternatives considered**:

- Move the agent controller into the container: rejected because it expands the
  trust boundary and would duplicate model/config/artifact handling.
- Let the host workspace mirror container state during solving: rejected
  because it risks divergence and weakens confinement guarantees.

## Decision: Use official-style eval semantics for validation

Validation is derived from the adapted task spec. Default validation uses
`FAIL_TO_PASS`; `PASS_TO_PASS` is included only when explicitly requested on
`run`.
Test patches are applied temporarily or isolated from final patch export.
Final eval output is parsed into fix-verification and regression results.

**Rationale**: The benchmark task metadata defines the validation target.
Validation-only files must not contaminate the model's final patch.

**Alternatives considered**:

- Continue using registered command templates by default: rejected for new
  benchmark runs because templates are not source-backed task specs.
- Accept arbitrary model-requested tests: rejected because it violates the
  allowed validation set and weakens auditability.

## Decision: Remove legacy benchmark runtime compatibility paths

The first version supports only `prepare` and `run` for SWE-Bench benchmark
runtime work. Legacy registry, legacy sandbox, and batch SWE-Bench runtime
entry points are rejected instead of retained as compatibility paths.

**Rationale**: Keeping old benchmark runtime operations available would
preserve the ambiguity the refactor is intended to remove. A two-operation
surface makes environment construction and agent execution explicit.

**Alternatives considered**:

- Keep legacy and new paths equally supported: rejected because it would make
  runtime selection ambiguous.
- Keep legacy only as explicit compatibility: rejected by the updated design;
  the benchmark runtime should expose only the current `prepare` and `run`
  operations.

## Decision: Do not implement batch benchmark orchestration in this feature

The first version supports only two user-visible benchmark operations for
selected tasks: `prepare` and `run`. `prepare` builds or reuses runtime layers
when explicitly allowed and creates the prepared task environment; `run` starts
the host-owned agent from that prepared environment. Batch benchmark
orchestration is out of scope.

**Rationale**: The user asked for an agent runtime environment refactor, not a
full benchmark runner. Avoiding batch orchestration keeps the plan focused and
reduces state-management risk.

**Alternatives considered**:

- Migrate current batch commands to the new path: deferred because it expands
  acceptance and concurrency scope.
- Keep existing batch commands as compatibility flows: rejected because the
  updated design allows only `prepare` and `run` as benchmark runtime
  operations.

## Decision: Prefer standard-library parsing unless a dependency is justified

Patch/file extraction and command parsing should use small focused helpers in
this project unless a new dependency clearly reduces real complexity.

**Rationale**: The project currently has minimal runtime dependencies. Adding a
dependency solely for simple diff filename extraction is unnecessary unless
implementation proves otherwise.

**Alternatives considered**:

- Add `unidiff`: useful, but deferred unless task implementation finds parsing
  requirements that exceed simple official-style test patch reset needs.

## Source References

- `docs/superpowers/plans/2026-06-17-official-swebench-sandbox.md`
- `docs/superpowers/specs/2026-06-17-official-swebench-sandbox-design.md`
- `specs/002-swebench-docker-sandbox/spec.md`
- `SWE-bench/swebench/harness/test_spec/test_spec.py`
- `SWE-bench/swebench/harness/test_spec/utils.py`
- `SWE-bench/swebench/harness/test_spec/python.py`
- `SWE-bench/swebench/harness/docker_build.py`
- `SWE-bench/swebench/harness/grading.py`
- `SWE-bench/swebench/harness/constants/__init__.py`
- `SWE-bench/swebench/harness/constants/python.py`
- `data/dev-00000-of-00001.parquet`
- `data/test-00000-of-00001.parquet`
- `specs/003-agent-runtime-refactor/runtime-image-audit.md`
- Docker CLI documentation for image build and container lifecycle commands

## Implementation Reference Index

Use these exact source sections while implementing the runtime refactor. They
are reference inputs only; production code must not import the local
`SWE-bench/` checkout at runtime.

| Concern | Source section to consult | Implementation use |
|---------|---------------------------|--------------------|
| Adapted task spec fields and image keys | `SWE-bench/swebench/harness/test_spec/test_spec.py`: `TestSpec`, `base_image_key`, `env_image_key`, `instance_image_key`, `make_test_spec` | Derive this project's adapted spec shape and deterministic Base/Env/Instance image keys. |
| Repo/version metadata lookup | `SWE-bench/swebench/harness/constants/__init__.py`: `MAP_REPO_VERSION_TO_SPECS`, `MAP_REPO_TO_EXT`; `SWE-bench/swebench/harness/constants/python.py`: `MAP_REPO_VERSION_TO_SPECS_PY` | Populate only source-backed repo/version metadata and reject missing entries. |
| Repo, environment, and eval scripts | `SWE-bench/swebench/harness/test_spec/create_scripts.py`: `make_repo_script_list`, `make_env_script_list`, `make_eval_script_list`; `SWE-bench/swebench/harness/test_spec/python.py`: `get_test_directives`, `make_repo_script_list_py`, `make_env_script_list_py`, `make_eval_script_list_py` | Build source-derived setup scripts, allowed validation metadata, and adapted `eval_script`. |
| Docker image build ordering | `SWE-bench/swebench/harness/docker_build.py`: `build_base_images`, `build_env_images`, `build_instance_images`, `build_instance_image` | Preserve base -> env -> instance planning, reuse detection, and explicit build behavior. |
| Official-style grading | `SWE-bench/swebench/harness/grading.py`: `get_eval_report`, `get_resolution_status`, `FAIL_TO_PASS`, `PASS_TO_PASS` handling | Parse final `eval_script` output into fix-verification and regression results. |
| Current dataset boundary | `src/coding_agent/swebench/dataset.py`: `SwebenchTaskRecord.from_row`, `load_task_record`, `load_task_records` | Extend existing normalization without bypassing the parquet-backed task record path. |
| Current Docker wrapper boundary | `src/coding_agent/sandbox/docker_cli.py`: `DockerCli.run`, `image_exists`, `container_exists`, `create_container`, `exec`; `src/coding_agent/sandbox/manager.py`: `TaskSandboxManager.prepare`, `stop` | Keep Docker subprocess behavior inside the sandbox package. |
| Docker CLI command semantics | Docker CLI reference: `docker image build`, `docker image inspect`, `docker container create`, `docker container start`, `docker container exec`, `docker container cp`, `docker container rm` | Match supported command shapes and lifecycle semantics when adding wrapper helpers. |

## Phase 7 Implementation Review Notes

- `src/coding_agent/swebench/repo_specs.py` loads supported repo/version pairs
  from `specs/003-agent-runtime-refactor/runtime-image-audit.md` and assigns
  `RepoSpecReviewStatus.SOURCE_BACKED` plus the same audit file as
  `source_reference`; it does not embed per-test fixture branches.
- `src/coding_agent/swebench/images.py` derives base and instance image keys
  from source-backed TestSpec inputs and reads env image keys from the audit
  document. There is no per-instance image table in production code.
- `src/coding_agent/swebench/testspec.py` builds the adapted TestSpec from a
  normalized dataset task record and a `RepoVersionSpec`; missing metadata
  fails through the repository spec boundary instead of using guessed defaults.
- `src/coding_agent/swebench/script_builders.py` constructs setup and eval
  scripts from `RepoVersionSpec` and selected task validation identifiers. The
  fallback behavior is explicit missing-metadata failure.
- `src/coding_agent/swebench/validation.py` provides the new
  `build_official_validation_set` path for prepared-runtime runs without
  registry-template fallback; the older registered-template helper remains only
  for legacy lower-level helpers and is not wired to the new `prepare`/`run`
  benchmark CLI surface.
- `src/coding_agent/swebench/sandbox_run.py` now contains both the new
  official-style prepare/run orchestration and older helper functions retained
  for internal compatibility. The public benchmark CLI is restricted in
  `src/coding_agent/cli.py` to `swebench prepare` and `swebench run`, and old
  sandbox/batch benchmark commands are rejected before agent execution.
- Compliance scans for this phase check for runtime imports from the local
  `SWE-bench/` checkout, known fixture instance IDs, test-name branches,
  expected-output shortcuts, and unsupported legacy CLI parser registrations.
