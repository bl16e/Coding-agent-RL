# SWE-smith SFT/RL 任务切分账本设计

## 背景

Stage 2 当前负责生成 teacher trajectories、运行 SWE-smith official eval，并导出
SFT 数据。后续 Stage 3 SFT 和 Stage 4 GRPO/RL 会共同使用 SWE-smith 任务池，
因此必须在扩大数据生产前拆出独立的任务创建和切分步骤。

这个步骤的目标不是直接训练模型，而是创建一个可审计的训练任务账本：

- 先按任务难度把 SWE-smith instances 分层；
- 从 medium 难度中选择 SFT candidate 交给 teacher model 解答；
- teacher 解答成功且通过 quality gate 的样本进入 SFT；
- teacher 解答失败、未 resolved、或 quality gate rejected 的样本回流给 RL；
- 剩余任务继续作为 RL、GRPO dev 或 held-out eval 任务；
- 全流程以 `instance_id` 为唯一互斥键，避免 SFT 和 RL 重复使用同一个任务。

## 核心原则

SFT 不做课程学习。SFT 只消费少量高质量 medium teacher trajectories，用来学习
agent workflow、tool-call 格式、仓库导航和 patch 生成习惯。

课程学习只发生在 GRPO/RL 阶段。GRPO/RL 通过 easy、medium、hard 三个 bucket
的动态采样权重实现难度调整。

SFT 和 RL 的互斥粒度是 `instance_id`。同一个 task instance 如果最终进入 SFT，
就不能进入 RL train、GRPO dev 或 held-out eval。repo 级重叠只作为分层信号，
不是默认排除条件。

teacher 失败的 SFT candidate 不应丢弃。它没有进入 SFT 训练信号，因此可以回流到
RL pool，由当前模型重新 rollout 并通过 environment reward 学习。

## 难度定义

第一版使用 `FAIL_TO_PASS` 数量作为可解释、稳定、可复现的难度代理：

| difficulty | 规则 |
|------------|------|
| easy | `len(FAIL_TO_PASS) <= 1` |
| medium | `2 <= len(FAIL_TO_PASS) <= 5` |
| hard | `len(FAIL_TO_PASS) >= 6` |

SFT candidate 只从 medium 中抽取。easy 和 hard 默认进入 RL 相关 pool。

后续可以加入测试运行时间、patch 文件数、trajectory 长度、repo 稳定性、历史失败率
等信号，但第一版不依赖这些信号，避免过早复杂化。

## 数据流

```text
SWE-smith full pool
  -> difficulty labeling: easy / medium / hard

medium
  -> sft_candidate
      -> teacher generation
          -> sft_accepted
          -> rl_recycled
  -> rl_candidate

easy, hard
  -> rl_candidate

grpo_dev and heldout
  -> fixed task sets excluded from SFT and RL train

final:
  SFT train = sft_accepted
  RL train = rl_candidate + rl_recycled
```

`sft_candidate` 是 teacher 尝试池，不等于最终 SFT 数据集。最终 SFT 数据集只来自
`sft_accepted`，也就是 official eval resolved 且 deterministic quality gate 通过
的 trajectories。

`rl_recycled` 包含所有 teacher 尝试过但没有进入 SFT 的任务，常见原因包括：

- teacher run errored；
- official eval unresolved；
- missing artifacts；
- empty patch；
- patch touches tests、fixtures、snapshots 或 expected outputs；
- trajectory reasoning 为空；
- 使用被禁止的 shell 形式；
- step limit 接近耗尽；
- 其他 quality gate rejection。

这些任务进入 RL 时只能提供 problem statement、repository environment 和 reward path，
不能提供 teacher messages、teacher tool calls、teacher patch 或 teacher trajectory。

## Manifest

任务创建步骤输出主账本：

```text
data/swesmith_training_manifest.json
```

建议 schema：

```json
{
  "schema": "coding-agent.swesmith.training-manifest.v1",
  "created_at": "2026-08-04T00:00:00Z",
  "seed": 42,
  "source": {
    "input": "data/SWE-smith/data",
    "languages": ["python"],
    "reference_path": "Reference/SWE-smith"
  },
  "difficulty_rules": {
    "easy_max_fail_to_pass": 1,
    "medium_min_fail_to_pass": 2,
    "medium_max_fail_to_pass": 5,
    "hard_min_fail_to_pass": 6
  },
  "split_config": {
    "sft_candidate_limit": 3000,
    "grpo_dev_count": 300,
    "heldout_count": 500
  },
  "items": [
    {
      "instance_id": "pandas-dev__pandas.95280573.pr_53652",
      "repo": "pandas-dev__pandas.95280573",
      "difficulty": "medium",
      "fail_to_pass_count": 3,
      "initial_split": "sft_candidate",
      "teacher_status": "not_run",
      "quality_status": "not_run",
      "final_pool": "pending_teacher",
      "reason": "selected_medium_for_teacher"
    }
  ],
  "summary": {
    "total": 0,
    "easy": 0,
    "medium": 0,
    "hard": 0,
    "sft_candidate": 0,
    "rl_candidate": 0,
    "grpo_dev": 0,
    "heldout": 0
  }
}
```

`items` 是污染控制的权威来源。后续任何 SFT export、RL rollout、GRPO dev 或
held-out eval 都应该通过这个 manifest 选择任务，而不是直接扫描 run directories。

## 导出的 subset 文件

创建 manifest 时同时导出可直接运行的 subset：

```text
data/splits/sft_candidate.json
data/splits/rl_train_initial.json
data/splits/grpo_dev.json
data/splits/heldout.json
```

teacher generation 和 quality gate 完成后，更新 manifest 并导出：

```text
data/splits/sft_accepted.jsonl
data/splits/rl_train_final.json
data/splits/recycled_from_teacher.json
```

`sft_accepted.jsonl` 是最终可训练的 SFT 数据来源。`rl_train_final.json` 是 RL 任务
来源，包含初始 RL candidate 加上 teacher 失败或 quality rejected 后回流的任务。

## CLI 设计

第一步，创建任务和 split：

```powershell
coding-agent swesmith create-training-manifest `
  --input data\SWE-smith\data `
  --out data\swesmith_training_manifest.json `
  --splits-dir data\splits `
  --languages python `
  --reference-path Reference\SWE-smith `
  --easy-fail-to-pass-max 1 `
  --medium-fail-to-pass-min 2 `
  --medium-fail-to-pass-max 5 `
  --sft-candidate-limit 3000 `
  --grpo-dev-count 300 `
  --heldout-count 500 `
  --seed 42
```

第二步，只让 teacher 解答 SFT candidate：

```powershell
coding-agent stage2 generate-teacher-trajectories `
  --subset data\splits\sft_candidate.json `
  --output-dir runs\stage2_sft_candidate_001 `
  --reference-path Reference\SWE-smith `
  --max-steps 50 `
  --timeout-seconds 900 `
  --test-timeout-seconds 180 `
  --jobs 1 `
  --eval-workers 2 `
  --run-id stage2_sft_candidate_001 `
  --sft-output sft_data\stage2_sft_candidate_001.jsonl
```

第三步，用 teacher、eval 和 quality gate 结果更新 manifest：

```powershell
coding-agent swesmith update-training-manifest `
  --manifest data\swesmith_training_manifest.json `
  --runs runs\stage2_sft_candidate_001 `
  --eval-dir logs\run_evaluation\stage2_sft_candidate_001 `
  --quality-report sft_data\stage2_sft_candidate_001.quality.json `
  --filtered-sft sft_data\stage2_sft_candidate_001.filtered.jsonl `
  --splits-dir data\splits
```

## 状态流转

初始状态：

| initial_split | final_pool |
|---------------|------------|
| `sft_candidate` | `pending_teacher` |
| `rl_candidate` | `rl_train` |
| `grpo_dev` | `grpo_dev` |
| `heldout` | `heldout` |

teacher 和 quality 更新后的状态：

| 条件 | teacher_status | quality_status | final_pool |
|------|----------------|----------------|------------|
| official eval resolved 且 quality accepted | `resolved` | `accepted` | `sft_train` |
| official eval unresolved | `unresolved` | `not_accepted` | `rl_train` |
| teacher run errored | `errored` | `not_accepted` | `rl_train` |
| missing artifacts | `artifact_missing` | `not_accepted` | `rl_train` |
| quality rejected | `resolved` | `rejected` | `rl_train` |

`final_pool=sft_train` 是唯一允许读取 teacher trajectory 的训练用途。
`final_pool=rl_train` 不允许读取 teacher trajectory，即使这个 instance 曾经被
teacher 尝试过。

## 防复用校验

Manifest 创建和更新都必须执行以下校验：

- 每个 `instance_id` 只能出现一次；
- `sft_train` 与 `rl_train` 不能重叠；
- `grpo_dev`、`heldout` 不能与任何 train pool 重叠；
- `sft_train` 只能来自 `initial_split=sft_candidate`；
- `sft_train` 必须同时满足 official eval resolved 和 quality accepted；
- `rl_train` 中来自 teacher 回流的样本必须记录 reject 或 failure reason；
- 导出的 subset 文件数量必须与 manifest summary 一致。

## 非目标

第一版不实现以下能力：

- patch fingerprint 相似度去重；
- 与 SWE-Bench Lite 的 PR 级或 changed-file 级 overlap 检测；
- repo-disjoint 强隔离 split；
- 基于测试耗时、历史 flakiness 或 patch 规模的复杂难度模型；
- GRPO 动态采样器本身。

这些能力可以在 manifest 基础上增量加入。第一版优先保证 `instance_id` 级别互斥、
teacher 失败回流、SFT/RL 数据来源清晰可审计。

## 测试策略

单元测试：

- 使用小型 fixture 验证 `FAIL_TO_PASS` 数量分桶；
- 验证 deterministic seed 下 split 可复现；
- 验证 `sft_candidate` 只来自 medium；
- 验证 teacher failed、unresolved、quality rejected 都回流到 `rl_train`；
- 验证 accepted 样本进入 `sft_train`；
- 验证重复 `instance_id` 直接失败；
- 验证导出的 subset 文件与 manifest summary 一致。

CLI contract 测试：

- `create-training-manifest` 写出 manifest 和四个初始 subset；
- `update-training-manifest` 读取 quality report 和 filtered SFT 后写出 final subset；
- 参数非法时返回输入错误，而不是静默生成污染数据。

## 成功标准

实现完成后，用户可以先运行任务创建命令，得到固定 manifest 和 SFT candidate subset。
随后 teacher generation 只处理这个 subset。teacher 完成后，manifest 能明确说明每个
`instance_id` 最终用于 SFT、RL、GRPO dev、held-out，或为何从 SFT candidate 回流到 RL。

任何后续 SFT 或 RL 数据消费都可以通过 manifest 验证没有复用同一个 `instance_id`。
