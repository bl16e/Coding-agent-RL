# Agent Self-Test Command Design

## Purpose

SWE-Bench `run` should separate the agent's in-loop self-testing from final
benchmark validation.

The agent should not see or reproduce the official eval script. It should be
able to run focused repository tests and small diagnostics during problem
solving, then declare completion. The runtime should then run the hidden
official eval script and use that result as the benchmark outcome.

## Current Problem

The current `run_tests` tool only accepts exact matches from
`validation.allowed_commands`. In the official-style runtime this command can be
a long generated eval script containing heredocs, `git apply`, marker lines, and
cleanup commands.

This causes three issues:

- The agent often cannot reproduce the command byte-for-byte.
- The official eval script becomes visible to the agent, even though it should
  be runtime-owned validation.
- Agent loop status can become `incomplete` due to rejected test attempts even
  when the final official eval passes.

## Design

### Agent-Visible Testing

The system prompt should no longer list exact official eval commands. It should
tell the agent that it may use `run_tests` for focused repository tests and small
diagnostic commands, and that final benchmark validation runs automatically
after it finishes.

Examples of agent-visible commands that should be allowed:

- `pytest ...`
- `python -m pytest ...`
- `./tests/runtests.py ...`
- `python -c "..."`
- `python path/to/diagnostic.py`

### Command Policy

`run_tests` should use a policy rather than exact string matching in the
official-style container runtime.

The policy should allow common test and diagnostic commands while rejecting
commands that are destructive, install dependencies, access the network, manage
containers, or mutate benchmark-owned validation state.

Allowed command forms:

- `pytest` and arguments
- `python -m pytest` and arguments
- Django test runner invocations such as `./tests/runtests.py`
- `python -c` snippets for small diagnostics
- `python <repo-relative-script.py>` diagnostics

Rejected command forms:

- Shell control operators: `&&`, `||`, `;`, `|`, `>`, `<`, background `&`,
  command substitution, and backticks
- Destructive filesystem commands such as `rm`, `mv`, and broad `chmod` or
  `chown`
- Git mutation commands such as `git checkout`, `git reset`, `git apply`, and
  `git clean`
- Dependency or system mutation commands such as `pip install`, `apt`, `curl`,
  `wget`, and `docker`

All allowed commands still run inside the prepared Docker task container, under
the repository path, with the configured timeout.

### Final Benchmark Validation

Final validation remains runtime-owned. After the agent finishes, the runtime
must run the adapted official eval script and parse the official output.

The agent's self-test commands must not replace final official eval.

### Summary Semantics

`summary.status` should represent the benchmark outcome:

- `solved` when final official eval resolves all selected tests.
- non-solved when final official eval fails, cannot be parsed, errors, or does
  not run.

The agent loop outcome should be preserved separately:

- `agent_status`: raw status returned by the agent loop.
- `agent_error`: raw agent loop error, if any.

This preserves process diagnostics without allowing agent self-assessment to
override benchmark validation.

Example:

```json
{
  "status": "solved",
  "agent_status": "incomplete",
  "agent_error": "model reported solved after unresolved tool failure",
  "validation": {
    "eval_report": {
      "resolved": true
    }
  }
}
```

## Data Flow

1. `prepare` creates a ready official-style task environment.
2. `run` starts the agent with a container-backed tool executor.
3. The agent may call `run_tests` with policy-approved self-test commands.
4. The agent calls `final` with its own assessment.
5. The runtime exports the container diff.
6. The runtime runs the hidden official eval script.
7. The runtime writes `summary.status` from official eval and writes
   `agent_status`/`agent_error` from the agent loop.

## Error Handling

Rejected self-test commands should remain visible in trajectory and
`test_summary`, but should not automatically make the benchmark result
`incomplete` if final official eval passes.

If the agent mutates generated diagnostic files, those files may appear in the
container diff unless they are removed by the agent. This is acceptable for the
first implementation, but the command policy should reject commands that mutate
official validation files through git operations.

If final official eval fails or cannot be parsed, `summary.status` should not be
`solved` even when the agent reported success.

## Testing

Required tests:

- Container `run_tests` allows `pytest`, `python -m pytest`, Django
  `./tests/runtests.py`, `python -c`, and `python script.py` commands.
- Container `run_tests` rejects shell control operators and destructive or
  mutation commands.
- The agent prompt no longer exposes the official eval script as an exact
  allowed command.
- `run_prepared_swebench_runtime` preserves `agent_status` and `agent_error` in
  summary metadata.
- `summary.status` is `solved` when final official eval resolves, even if
  `agent_status` is `incomplete`.
- `summary.status` is not `solved` when final official eval fails, even if the
  agent reports solved.

## Scope

This design changes only official-style SWE-Bench prepared container runs.
Local non-SWE-Bench runs may keep exact allowlist behavior unless a later change
explicitly updates them.
