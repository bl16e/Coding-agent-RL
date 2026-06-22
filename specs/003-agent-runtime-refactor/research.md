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
- Fall back to legacy registry templates: rejected for new benchmark runs;
  legacy remains explicit compatibility only.

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
`FAIL_TO_PASS`; `PASS_TO_PASS` is included only when explicitly requested.
Test patches are applied temporarily or isolated from final patch export.
Final eval output is parsed into fix-verification and regression results.

**Rationale**: The benchmark task metadata defines the validation target.
Validation-only files must not contaminate the model's final patch.

**Alternatives considered**:

- Continue using registered command templates by default: rejected for new
  benchmark runs because templates are not source-backed task specs.
- Accept arbitrary model-requested tests: rejected because it violates the
  allowed validation set and weakens auditability.

## Decision: Preserve legacy registry only as explicit compatibility

Existing `sandbox register/list` and legacy flows remain available as
compatibility behavior. New benchmark `prepare` and `run` flows do not use the
legacy registry unless the developer invokes an explicit legacy command or
compatibility path.

**Rationale**: This protects existing workflows while making the new
official-style runtime path unambiguous.

**Alternatives considered**:

- Keep legacy and new paths equally supported: rejected because it would make
  default behavior ambiguous.
- Remove legacy immediately: rejected because the spec requires migration
  without breaking existing workflows.

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
- Remove existing batch code: rejected because that is unrelated cleanup and
  risks breaking existing users.

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
