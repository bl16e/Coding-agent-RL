# Stage 3/4 Training Roadmap

This document records the planned continuation after:

- Stage 1: Evaluate Qwen2.5-Coder-7B-Instruct on SWE-Bench Lite with local vLLM.
- Stage 2: Generate high-quality SWE-smith trajectories with a teacher model API.

The next stages are:

- Stage 3: Supervised fine-tuning of Qwen2.5-Coder-7B-Instruct on teacher
  trajectories.
- Stage 4: GRPO reinforcement learning using benchmark-environment rewards.

## Overall Feasibility

The plan is feasible, but the risk profile changes by stage.

Stage 3 is the lower-risk step. It should improve tool-use format, patch-writing
habits, repository navigation, and task-solving workflow if the training data is
filtered well.

Stage 4 is higher risk. It can improve benchmark-solving behavior, but it
introduces sparse rewards, high environment cost, rollout instability, and
overfitting risk. Stage 4 should start only after Stage 3 produces measurable
held-out gains.

## Target Pipeline

```text
Stage 1 baseline
  -> Stage 2 teacher trajectory generation
  -> Stage 3 QLoRA/LoRA SFT
  -> Stage 3 evaluation against baseline
  -> Stage 4 small-scale GRPO smoke
  -> Stage 4 expanded RL only if held-out results improve
```

## Stage 3: SFT On Teacher Trajectories

### Goal

Train Qwen2.5-Coder-7B-Instruct to imitate high-quality teacher agent
trajectories that successfully solve SWE-smith tasks.

The expected gains are mainly in:

- following the project's tool-call protocol;
- reading and searching repositories effectively;
- producing valid patches;
- running focused validation commands;
- stopping with a clean final answer and patch.

### Recommended Method

Start with LoRA or QLoRA instead of full fine-tuning.

Reasons:

- lower 4090 memory requirement;
- faster iteration;
- easier rollback;
- lower risk of catastrophic forgetting;
- enough capacity for teaching agent workflow and formatting.

Initial training size:

- Smoke: 100-300 resolved trajectories.
- First useful run: 1,000-3,000 resolved trajectories.
- Larger run: 10,000+ only after evaluation shows positive movement.

### Data Inputs

Use only Stage 2 examples that pass official evaluation.

Required source artifacts:

- `trajectory.jsonl`
- `trajectory.json`
- `summary.json`
- `final.patch`
- `prediction.jsonl`
- SWE-smith official `report.json`

The exported SFT data should keep the same tool-call representation that the
inference-time agent expects to produce.

### Data Filtering

Resolved-only filtering is necessary but not sufficient.

Filter out trajectories with:

- empty or trivial patches;
- invalid or malformed tool calls;
- excessive repeated searches or file reads;
- very long context with low signal;
- failed final patch export;
- environment or test harness errors;
- suspicious success caused by test leakage;
- format drift from the target Qwen chat template;
- excessive failed validation attempts before the final patch.

Prefer shorter, direct, successful trajectories over long exploratory ones.

### Evaluation After SFT

Compare against the Stage 1 baseline before moving to Stage 4.

Required comparisons:

- SWE-Bench Lite resolved rate.
- SWE-Bench Lite errored rate.
- Average steps per instance.
- Tool-call rejection rate.
- Patch apply success rate.
- Final validation success rate.
- Qualitative review of 20-50 trajectories.

Success threshold before Stage 4:

- resolved rate improves, or
- resolved rate is flat but error/tool rejection rate drops materially, and
- no clear regression on held-out tasks.

### SFT Stop Criteria

Use the following as Stage 3 SFT stopping criteria. The validation metric should
be measured on fixed held-out tasks, with SWE-Bench Lite treated as an external
sanity benchmark rather than a repeatedly tuned training signal.

| Metric | Role as SFT stop criterion | Rationale |
|--------|----------------------------|-----------|
| Held-out validation pass or resolved rate stops improving | Primary | Directly reflects real task-solving ability. |
| SFT eval loss converges | Auxiliary | Detects non-convergence, instability, or overtraining, but does not prove task ability by itself. |
| Tool-calling success rate is stable | Strong auxiliary | Confirms the agent workflow and tool protocol have formed. |
| Patch apply success rate is stable | Strong auxiliary | Ensures the model produces usable patches, not only valid-looking messages. |
| Operational error rate does not increase | Strong auxiliary | Prevents accepting a model that solves some tasks but becomes less reliable overall. |

Stop SFT when validation pass or resolved rate has plateaued across repeated
evaluations, SFT eval loss is stable, tool calling and patch application are
stable, and operational errors are not rising.

GRPO cold-start reward should not be treated as an SFT stop criterion. It is a
Stage 4 entry gate after SFT has already produced a candidate checkpoint.

## Stage 4: GRPO Reinforcement Learning

### Goal

Improve task-solving behavior using environment-derived rewards instead of only
imitating teacher trajectories.

GRPO should optimize for patches that actually resolve benchmark tasks while
preserving clean tool use and avoiding regressions.

### Recommended Entry Point

Do not start with full online GRPO over the full SWE-smith set.

Use this sequence:

1. Offline best-of-N or rejection sampling using the Stage 3 model.
2. Build a small reward-evaluation harness.
3. Run GRPO smoke on a tiny task subset.
4. Expand only if held-out evaluation improves.

### Reward Design

Use simple environment rewards first.

Suggested reward components:

| Event | Reward direction |
|-------|------------------|
| Patch applies cleanly | small positive |
| Repository remains usable | small positive |
| No syntax/runtime error in focused checks | small positive |
| FAIL_TO_PASS resolved | large positive |
| PASS_TO_PASS preserved | medium positive |
| Invalid patch | negative |
| Tool protocol violation | negative |
| Timeout | negative |
| Excessive repeated actions | negative |

Avoid complex heuristic rewards until the simple reward pipeline is reliable.

### Main GRPO Risks

Sparse reward:

Most rollouts may fail to resolve the task, producing little useful signal.

Environment throughput:

Each reward requires Docker containers, repo operations, tests, and patch
evaluation. This can become more expensive than model inference.

4090 limits:

GRPO requires rollout generation plus training memory. On one 4090, realistic
training likely needs QLoRA/LoRA, small batches, short completions, and careful
vLLM placement.

Reward hacking:

The model may learn to exploit weak validation commands, avoid meaningful edits,
or overfit to benchmark-specific patterns.

Overfitting:

If training, reward tuning, and evaluation all use the same task family, apparent
gains may not transfer to SWE-Bench Lite or held-out SWE-smith tasks.

Operational complexity:

GRPO adds distributed process management, rollout queues, reward workers,
checkpoint management, and expensive failure recovery.

## Dataset Splits

Keep strict splits before Stage 3 starts.

| Split | Purpose |
|-------|---------|
| SFT pool | Teacher-resolved trajectories used for supervised imitation |
| GRPO train pool | Disjoint SWE-smith task instances used for model rollouts and rewards |
| GRPO dev pool | Small fixed set for reward and hyperparameter tuning |
| Held-out eval | Final quality check only |
| SWE-Bench Lite | External sanity benchmark |

Do not repeatedly tune on SWE-Bench Lite. Use it as an external comparison
against the Stage 1 baseline.

### SWE-smith SFT/GRPO Split Design

GRPO data can come from SWE-smith, but it should not reuse the same samples as
Stage 3 SFT.

The intended split is:

```text
SWE-smith task pool
  -> SFT pool: teacher resolved trajectories
  -> GRPO train pool: different task instances, no teacher trajectory input
  -> GRPO dev pool: fixed tuning set
  -> held-out pool: final evaluation only
```

The important distinction is the training signal:

- SFT consumes teacher trajectories and teaches imitation.
- GRPO consumes task instances and lets the current model generate fresh
  rollouts, then scores those rollouts with environment rewards.

The GRPO trainer should receive the problem statement, repository environment,
and validation reward path. It should not receive teacher messages, teacher tool
calls, or teacher patches for those GRPO instances.

### Exclusion Rules

The GRPO train pool must exclude:

- every `instance_id` used in SFT;
- every task used for GRPO dev or held-out evaluation;
- samples with high similarity to SWE-Bench Lite tasks;
- samples with the same PR number as a SWE-Bench Lite task when PR metadata can
  be parsed;
- samples whose `FAIL_TO_PASS` set is identical or highly overlapping with a
  held-out task;
- samples whose patch fingerprint or changed-file set is highly similar to a
  held-out task.

Use repository-level overlap only as a stratification signal, not as an automatic
exclusion. Same-repository tasks are acceptable when the task, PR, tests, and
patch are different.

### Split Strategies

Recommended default:

```text
Within each stable SWE-smith repo:
  70% SFT candidate pool
  20% GRPO candidate pool
  10% held-out or dev pool
```

Stricter anti-contamination option:

```text
Repo group A -> SFT only
Repo group B -> GRPO only
Repo group C -> held-out only
```

The repo-disjoint option gives a cleaner generalization signal, but it may make
training harder because the SFT and GRPO distributions differ more.

### GRPO Pool Selection

Prefer GRPO tasks that are cheap and reliable to score:

- stable Docker environments;
- fast test suites;
- clear problem statements;
- moderate `FAIL_TO_PASS` count;
- low known flakiness;
- no obvious overlap with SWE-Bench Lite;
- no history of harness or artifact failures in Stage 2.

This keeps GRPO focused on learning from environment feedback instead of burning
rollouts on unstable infrastructure.

## Infrastructure Plan

Bare-metal CPU server:

- Stage 2 teacher generation;
- data filtering;
- official evaluation;
- SFT data export;
- Docker reward workers for GRPO where possible;
- artifact storage.

4090 GPU server:

- Stage 1 vLLM inference;
- Stage 3 QLoRA/LoRA SFT;
- Stage 4 small-scale GRPO training and rollout generation.

For Stage 4, consider separating rollout serving and training if the 4090 becomes
memory-bound.

## Checkpoints And Promotion Gates

### Gate 1: Before Stage 3

- Stage 2 exports a non-trivial resolved-only dataset.
- SFT examples are valid under the target chat/tool format.
- A fixed held-out evaluation set is defined.

### Gate 2: Before Larger SFT

- A 100-300 sample smoke fine-tune completes.
- The fine-tuned model can run through the agent loop.
- Tool-call format does not regress.

### Gate 3: Before Stage 4

- Stage 3 beats the baseline, or matches it with fewer operational errors.
- Held-out performance does not regress.
- Reward evaluation can run reproducibly from saved predictions.
- GRPO cold-start reward is positive or materially better than the Stage 1
  baseline on the GRPO candidate pool.
- The reward distribution is not all zero, all negative, or dominated by
  invalid-patch and timeout failures.

### Gate 4: Before Expanded GRPO

- Small GRPO smoke produces stable training metrics.
- Reward distribution is not all zero or all negative.
- Held-out evaluation improves or at least preserves Stage 3 gains.
- Runtime cost per resolved improvement is acceptable.

## Likely Future Blockers

Data quality blockers:

- Too few resolved trajectories.
- Teacher trajectories contain noisy or inefficient behavior.
- Export format does not match Qwen's expected chat template.
- Long trajectories exceed training context limits or create low-signal samples.

Training blockers:

- 4090 memory pressure during SFT or GRPO.
- Tokenization or chat-template mismatch.
- Catastrophic forgetting after SFT.
- SFT improves formatting but not solve rate.

Reward blockers:

- Sparse reward makes GRPO inefficient.
- Official evaluation is too slow for online RL.
- Reward hacking against weak validation.
- High variance across repositories and languages.

Infrastructure blockers:

- Docker image storage and cleanup failures.
- Container throughput bottlenecks on CPU, RAM, or disk IO.
- Teacher API rate limits during Stage 2.
- Long-running jobs needing robust resume and retry behavior.

Evaluation blockers:

- Overfitting to SWE-smith train distribution.
- No clean held-out split.
- Comparing against a moving Stage 1 baseline.
- Treating resolved rate alone as success while operational errors increase.

## Recommended Next Steps

1. Finish Stage 1 baseline and save immutable metrics.
2. Generate Stage 2 teacher trajectories with resolved-only export.
3. Build a data-quality report for exported SFT examples.
4. Run Stage 3 QLoRA smoke on 100-300 examples.
5. Evaluate the smoke model against a fixed subset.
6. Scale Stage 3 only if the smoke run improves behavior.
7. Delay GRPO until Stage 3 has clear evidence of benefit.

## Position

Stage 3 should be treated as the main near-term training milestone. Stage 4 is a
research and infrastructure milestone. The project should not commit major GRPO
resources until SFT improves the baseline or reduces operational failure modes.
