# SWE-Bench Batch Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `coding-agent swebench batch-run` to run all tasks from one or more SWE-Bench Lite parquet files through the official `prepare` then `run` pipeline.

**Architecture:** Add a focused batch coordinator in `src/coding_agent/swebench/sandbox_run.py` that loads records from multiple datasets, writes resumable batch state, and invokes existing `prepare_official_swebench_runtime` and `run_prepared_swebench_runtime` per task. Add CLI parsing in `src/coding_agent/cli.py`; keep legacy registry batch commands rejected.

**Tech Stack:** Python argparse, pathlib/json, existing SWE-Bench dataset/runtime modules, pytest with monkeypatch/fake Docker.

---

### Task 1: CLI Contract

**Files:**
- Modify: `tests/contract/test_cli_swebench_runtime_contract.py`
- Modify: `src/coding_agent/cli.py`

- [ ] Add a failing test proving `swebench batch-run` accepts multiple `--dataset` values and forwards them to the coordinator.
- [ ] Run the new test and verify argparse rejects `batch-run`.
- [ ] Add parser and dispatch for `batch-run`.
- [ ] Run the test and verify it passes.

### Task 2: Batch Coordinator

**Files:**
- Modify: `tests/integration/test_swebench_batch_run.py`
- Modify: `src/coding_agent/swebench/sandbox_run.py`

- [ ] Add a failing integration test using two parquet files and monkeypatched official prepare/run functions.
- [ ] Run the test and verify `run_official_swebench_batch` is missing.
- [ ] Implement `run_official_swebench_batch` with state, per-instance dirs, resume, cleanup default, and aggregate prediction/summary outputs.
- [ ] Run the integration test and verify it passes.

### Task 3: Focused Verification

**Files:**
- Test: `tests/contract/test_cli_swebench_runtime_contract.py`
- Test: `tests/integration/test_swebench_batch_run.py`

- [ ] Run focused contract and integration tests.
- [ ] Run existing SWE-Bench runtime contract tests to ensure legacy rejection still holds.
