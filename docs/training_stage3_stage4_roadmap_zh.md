# Stage 3/4 训练路线图

本文记录 Stage 1 和 Stage 2 之后的后续训练规划：

- Stage 1：使用本地 vLLM，在 SWE-Bench Lite 上评测
  Qwen2.5-Coder-7B-Instruct。
- Stage 2：使用 teacher model API 生成高质量 SWE-smith trajectories。

后续阶段为：

- Stage 3：基于 teacher trajectories，对 Qwen2.5-Coder-7B-Instruct 做监督微调。
- Stage 4：基于 benchmark environment reward 做 GRPO 强化学习。

## 总体可行性

这个规划可行，但不同阶段的风险不同。

Stage 3 风险较低。如果训练数据过滤得足够好，它应该能提升模型的工具调用格式、
patch 编写习惯、仓库导航能力，以及整体解题工作流。

Stage 4 风险更高。它可能提升 benchmark 解题能力，但会引入稀疏 reward、高环境
成本、rollout 不稳定和过拟合风险。只有在 Stage 3 产生可衡量的 held-out 提升后，
才应该启动 Stage 4。

## 目标流水线

```text
Stage 1 baseline
  -> Stage 2 teacher trajectory generation
  -> Stage 3 QLoRA/LoRA SFT
  -> Stage 3 evaluation against baseline
  -> Stage 4 GRPO pilot validation
  -> Stage 4 adaptive GRPO rollout/training loop only if held-out results improve
```

## Curriculum Learning 设计

课程学习只用于 GRPO 阶段。SFT 不需要课程学习；SFT 只需要从 medium 难度中一次性筛选
少量高质量 teacher trajectories，用来建立稳定的 agent workflow、工具调用格式和 patch
生成习惯。

核心原则：

- SFT 阶段不是课程学习阶段，只做高质量 medium trajectory 筛选。
- GRPO 阶段需要大量 rollouts，用环境 reward 让模型从尝试中学习。
- GRPO 的难度提升应该由任务复杂度、测试成本、reward 稳定性和当前模型成功率共同决定。

GRPO 不采用显式的 `early`、`core`、`hardening` 阶段。正式训练时应该使用动态采样器，
根据当前训练效果连续调整 `easy`、`medium`、`hard` 的采样概率。

动态采样器的输入信号包括：

- 各难度 bucket 的近期 resolved rate；
- reward 均值、方差和正 reward 比例；
- invalid patch、tool protocol violation、timeout 的比例；
- 每个难度 bucket 的平均 wall time 和 reward worker 吞吐；
- held-out eval 是否提升，以及是否出现过拟合迹象。

采样策略应该是平滑变化的。例如 hard 采样率不应因为单次评测突然从低权重跳到高权重；
更合理的方式是使用滑动窗口指标、指数移动平均或 bandit-style weighting，让训练过程
自然从 easy-heavy 逐渐过渡到更多 medium/hard，而不是手工切换阶段。

SWE-smith 任务应先分成 `easy`、`medium`、`hard` 三档。SFT 只从 `medium`
中选高质量 teacher trajectories；GRPO 使用 `easy` 全部、`medium` 扣除 SFT
后的剩余部分、`hard` 全部。课程学习主要通过 GRPO 阶段的难度采样率实现，而不是
通过改变 SFT 的来源。

任务难度可以按以下维度分层：

- `FAIL_TO_PASS` 数量：先少后多。
- 测试运行时间：先短测试，再长测试。
- patch 规模：先小 patch，再多文件 patch。
- 轨迹长度：先短且直接，再允许更多探索。
- repo 稳定性：先环境稳定的 repo，再加入 flaky 或重型 repo。
- 任务来源：先程序化/清晰任务，再加入 PR mirror 或问题描述更复杂的任务。

不要把 curriculum learning 误解为 SFT 也要分难度逐步训练。正确做法是先用 medium
的高质量 teacher trajectories 做一次 SFT，然后在 GRPO 中用动态采样器根据训练信号
连续调节 easy、medium 和 hard 的比例。采样器必须定期用 held-out 检查约束，防止只在
当前训练分布上过拟合。

## Stage 3：基于 Teacher Trajectories 的 SFT

### 目标

训练 Qwen2.5-Coder-7B-Instruct 模仿高质量 teacher agent trajectories。这些
trajectories 必须来自成功解决 SWE-smith 任务的样本。

预期收益主要体现在：

- 遵循项目的 tool-call protocol；
- 更有效地阅读和搜索仓库；
- 生成有效 patch；
- 运行聚焦的验证命令；
- 以干净的 final answer 和 patch 结束任务。

### 推荐方法

先从 LoRA 或 QLoRA 开始，不要一开始做 full fine-tuning。

原因：

- 降低 4090 显存需求；
- 迭代更快；
- 更容易回滚；
- 降低 catastrophic forgetting 风险；
- 对学习 agent workflow 和格式来说容量通常足够。

初始训练规模：

- Smoke：100-300 条 resolved trajectories。
- 第一轮有意义训练：1,000-3,000 条 resolved trajectories。
- 默认生产 SFT：几千条高质量 trajectories 即可，不追求数量最大化。
- 更大规模训练：只有在评测仍持续正向变化时才扩展；10,000+ 条不作为默认目标，
  更适合作为消融实验或数据规模上限探索。

### 数据输入

只使用通过官方评测的 Stage 2 样本。

需要的源 artifacts：

- `trajectory.jsonl`
- `trajectory.json`
- `summary.json`
- `final.patch`
- `prediction.jsonl`
- SWE-smith 官方 `report.json`

导出的 SFT 数据应该保留推理时 agent 预期输出的同一种 tool-call 表示方式。

### 数据过滤

只保留 resolved 样本是必要条件，但还不够。

需要过滤掉以下 trajectories：

- 空 patch 或过于 trivial 的 patch；
- 无效或格式错误的 tool calls；
- 过多重复搜索或重复读取文件；
- 上下文很长但信号很低；
- final patch 导出失败；
- 环境或 test harness 出错；
- 可疑的测试泄漏导致的成功；
- 偏离目标 Qwen chat template 的格式；
- final patch 之前有过多失败验证尝试。

优先选择短、直接、成功的 trajectories，而不是很长的探索型 trajectories。

### SFT 后评测

进入 Stage 4 之前，必须和 Stage 1 baseline 对比。

需要比较：

- SWE-Bench Lite resolved rate；
- SWE-Bench Lite errored rate；
- 每个 instance 的平均步骤数；
- tool-call rejection rate；
- patch apply success rate；
- final validation success rate；
- 人工抽查 20-50 条 trajectories。

进入 Stage 4 的成功门槛：

- resolved rate 提升；或者
- resolved rate 持平，但 error/tool rejection rate 明显下降；并且
- held-out tasks 上没有明显回退。

### SFT 结束标准

使用以下指标作为 Stage 3 SFT 的停止标准。validation 指标应该在固定 held-out tasks
上测量，SWE-Bench Lite 应作为外部 sanity benchmark，而不是反复调参使用的训练信号。

| 指标 | 是否作为 SFT 结束标准 | 原因 |
|------|----------------------|------|
| Held-out validation pass 或 resolved rate 不再提升 | 主要标准 | 直接反映真实任务解决能力。 |
| SFT eval loss 收敛 | 辅助标准 | 用于发现未收敛、训练震荡或过训练，但不能单独证明任务能力。 |
| Tool-calling 成功率稳定 | 强辅助标准 | 确认 agent workflow 和 tool protocol 已经形成。 |
| Patch apply success rate 稳定 | 强辅助标准 | 确认模型能产出可用 patch，而不只是格式正确的消息。 |
| Operational error rate 不上升 | 强辅助标准 | 避免接受一个能解决部分任务、但整体更不稳定的模型。 |

当 validation pass 或 resolved rate 在多次评测中进入平台期，SFT eval loss 稳定，
tool calling 和 patch application 稳定，并且 operational errors 没有上升时，可以停止
SFT。

GRPO 冷启动 reward 不应作为 SFT 停止标准。它应该作为 Stage 4 准入检查，在 SFT
已经产出候选 checkpoint 之后再评估。

## Stage 4：GRPO 强化学习

### 目标

使用环境派生 reward 来提升任务解决能力，而不是只模仿 teacher trajectories。

GRPO 应该优化真实解决 benchmark tasks 的 patch，同时保持干净的工具使用，并避免
回归。

### 推荐切入方式

不要一开始就在完整 SWE-smith 集合上做 full online GRPO。

建议顺序：

1. 使用 Stage 3 模型做 offline best-of-N 或 rejection sampling。
2. 构建小型 reward-evaluation harness。
3. 在很小的任务子集上做 GRPO pilot，验证 reward、rollout、训练闭环。
4. 只有 held-out evaluation 提升后，才进入动态采样的正式 GRPO 训练。

### Reward 设计

先使用简单的 environment rewards。

建议 reward 组成：

| 事件 | Reward 方向 |
|------|-------------|
| Patch 干净应用 | 小正分 |
| 仓库保持可用 | 小正分 |
| 聚焦检查中没有 syntax/runtime error | 小正分 |
| FAIL_TO_PASS resolved | 大正分 |
| PASS_TO_PASS 保持通过 | 中等正分 |
| 无效 patch | 负分 |
| tool protocol violation | 负分 |
| timeout | 负分 |
| 过多重复动作 | 负分 |

在简单 reward pipeline 可靠之前，不要加入复杂 heuristic rewards。

### GRPO 主要风险

稀疏 reward：

大多数 rollouts 可能无法解决任务，导致有效训练信号很少。

环境吞吐：

每个 reward 都需要 Docker containers、repo operations、tests 和 patch evaluation。
这部分成本可能超过模型推理成本。

4090 限制：

GRPO 需要 rollout generation 和训练显存。单张 4090 上更现实的方式是
QLoRA/LoRA、小 batch、短 completion，以及谨慎安排 vLLM。

双 4090 会显著改善 Stage 4 的可行性：

- 可以把 rollout serving 和 GRPO training 分开，降低互相抢显存的风险；
- 可以提高并发 rollout 数量，让 reward worker 更持续地吃满任务；
- 可以使用更大的 effective batch size 或更多 samples per prompt，提高 GRPO 更新稳定性；
- 可以在一张卡保留稳定 checkpoint/serving，另一张卡做训练迭代，便于失败恢复；
- 仍然需要控制上下文长度、completion 长度和并发数，否则瓶颈会转移到 CPU、Docker、
  disk IO 或 reward evaluation。

Reward hacking：

模型可能学会利用弱验证命令、避免有意义编辑，或者过拟合 benchmark-specific
patterns。

过拟合：

如果训练、reward tuning 和评测都使用同一类任务，表面提升可能无法迁移到
SWE-Bench Lite 或 held-out SWE-smith tasks。

运维复杂度：

GRPO 会增加分布式进程管理、rollout queues、reward workers、checkpoint
管理，以及昂贵的失败恢复。

## 数据集切分

Stage 3 开始前必须保持严格 split。

| Split | 用途 |
|-------|------|
| SFT pool | 用于监督模仿的 teacher-resolved trajectories |
| GRPO train pool | 与 SFT 不重叠的 SWE-smith task instances，用于模型 rollout 和 reward |
| GRPO dev pool | 用于 reward 和超参数调优的小型固定集合 |
| Held-out eval | 只用于最终质量检查 |
| SWE-Bench Lite | 外部 sanity benchmark |

不要反复在 SWE-Bench Lite 上调参。它应该作为相对于 Stage 1 baseline 的外部对比。

### SWE-smith SFT/GRPO 切分设计

GRPO 数据可以来自 SWE-smith，但不应该复用 Stage 3 SFT 的同一批样本。

目标切分：

```text
SWE-smith task pool
  -> SFT pool: teacher resolved trajectories
  -> GRPO train pool: different task instances, no teacher trajectory input
  -> GRPO dev pool: fixed tuning set
  -> held-out pool: final evaluation only
```

关键区别在训练信号：

- SFT 消费 teacher trajectories，学习模仿。
- GRPO 消费 task instances，让当前模型生成新的 rollouts，再用环境 rewards 打分。

GRPO trainer 应该接收 problem statement、repository environment 和 validation
reward path。它不应该接收这些 GRPO instances 对应的 teacher messages、teacher
tool calls 或 teacher patches。

### SFT/GRPO 数据比例

SFT 和 GRPO 的数据需求不是同一个量级。SFT 需要少量高质量 teacher trajectories；
GRPO 需要大量 rollout attempts 和 environment rewards。

| 阶段 | 推荐数据规模 | 说明 |
|------|--------------|------|
| SFT dataset | medium 中 1,000-3,000 条高质量 resolved trajectories，最多不超过 5,000 条，且不超过 medium 总量的 30% | 单次监督微调数据集，不做课程学习 |
| GRPO task pool | easy 全部、medium 剩余部分、hard 全部 | 与 SFT task instance 严格互斥 |
| GRPO rollout budget | 每个 task instance 多次 rollout，总量按 reward 吞吐和训练稳定性扩大 | 主要 RL 信号来源 |
| GRPO adaptive sampling | 根据近期训练效果动态调整 easy、medium、hard 采样概率 | 实现平滑课程学习，不手工切换 early/core/hardening 阶段 |

推荐原则：

- SFT 和 GRPO 数据都来自 SWE-smith，但按 task instance 严格互斥。
- SFT 不采用课程学习；它是一次性的高质量模仿学习数据集。
- SFT 不需要覆盖所有 SWE-smith resolved trajectories。
- SFT 只从 medium 难度中选择高质量 teacher trajectories。
- SFT 总量不超过 5,000 条，且不超过 medium 总量的 30%。
- SFT 应该只保留高质量、短路径、格式稳定、patch 有效的 teacher trajectories。
- GRPO 数据来自 easy 全部、medium 扣除 SFT 后剩余部分、hard 全部。
- GRPO 需要大量 rollouts，因为大多数尝试不会 resolved，reward 信号稀疏。
- GRPO 的核心单位是 rollout，不是 teacher trajectory。
- 同一个 GRPO task 可以采样多次，用不同 temperature、seed 或 checkpoint 产生多条
  rollouts。
- 不要为了扩大 SFT 数量而加入低质量 teacher trajectories；低质量样本更适合丢弃，
  而不是交给模型模仿。

一个合理的初始配比是：

```text
SFT: medium 中 1,000-3,000 条高质量 resolved trajectories，最多 5,000 条
GRPO: easy 全部 + medium 剩余部分 + hard 全部，每个 task instance 多次 rollout
```

如果资源有限，应优先保证 SFT 质量和 GRPO reward 吞吐，而不是扩大 SFT 样本量。

### 排除规则

GRPO train pool 必须排除：

- 所有 SFT 使用过的 `instance_id`；
- 所有 GRPO dev 或 held-out evaluation 使用过的任务；
- 与 SWE-Bench Lite tasks 高相似的样本；
- 当 PR metadata 可解析时，与 SWE-Bench Lite task 拥有相同 PR 编号的样本；
- `FAIL_TO_PASS` 集合与 held-out task 完全相同或高度重叠的样本；
- patch fingerprint 或 changed-file set 与 held-out task 高度相似的样本。

repo 级重叠只作为分层信号，不作为自动排除条件。只要 task、PR、tests 和 patch
不同，同仓库任务是可以接受的。

### 切分策略

推荐默认策略：

```text
SWE-smith task pool
  -> difficulty labeling: easy / medium / hard
  -> SFT pool: high-quality teacher-resolved trajectories from medium only
       constraints:
         - total <= 5,000 trajectories
         - total <= 30% of medium tasks
  -> GRPO train pool:
       - all easy tasks
       - medium tasks not used by SFT
       - all hard tasks
  -> GRPO dev pool: fixed tuning set, excluded from train
  -> held-out pool: final evaluation only, excluded from train
```

SFT 与 GRPO 的互斥粒度应该是 `instance_id`。同一个 task instance 如果进入 SFT，
就不能再进入 GRPO train、GRPO dev 或 held-out eval。SFT 可以读取 teacher messages、
tool calls 和 final patch；GRPO 只能读取 problem statement、repo environment 和
reward path，不允许读取对应的 teacher trajectory。

GRPO 课程学习由动态采样器实现，不设置显式的 `early`、`core`、`hardening` 阶段。
采样器维护 `easy`、`medium`、`hard` 三个 bucket 的权重，并根据滑动窗口指标持续更新。

推荐的权重更新信号：

- 如果整体 positive reward 过低，提高 easy 权重，降低 hard 权重；
- 如果 easy resolved rate 已经稳定较高，提高 medium 权重；
- 如果 medium 的正 reward 比例稳定且 timeout 可控，逐步提高 hard 权重；
- 如果 hard 导致 timeout、invalid patch 或 reward 全负比例过高，降低 hard 权重；
- 如果 held-out 指标回退，回滚到最近稳定采样分布和 checkpoint；
- 对每次权重更新设置最大步长，避免采样分布突然跳变。

动态采样器的目标不是固定比例，而是在训练过程中持续维持足够的正 reward 密度，同时
逐步增加更难任务的覆盖率。

更严格的防污染策略：

```text
Repo group A -> SFT only
Repo group B -> GRPO only
Repo group C -> held-out only
```

repo-disjoint 方案能提供更干净的泛化信号，但会让训练更难，因为 SFT 和 GRPO 的
分布差异更大。

### GRPO Pool 选择

优先选择便宜且可靠的 GRPO 任务：

- Docker environments 稳定；
- test suites 运行快；
- problem statements 清晰；
- `FAIL_TO_PASS` 数量适中；
- 已知 flakiness 低；
- 与 SWE-Bench Lite 没有明显重叠；
- Stage 2 中没有 harness 或 artifact 失败历史。

这样能让 GRPO 聚焦于从环境反馈中学习，而不是把 rollout 预算消耗在不稳定基础设施上。

## 基础设施规划

裸金属 CPU 服务器：

- Stage 2 teacher generation；
- 数据过滤；
- 官方评测；
- SFT 数据导出；
- 尽可能承担 GRPO 的 Docker reward workers；
- artifact 存储。

4090 GPU 服务器：

- Stage 1 vLLM inference；
- Stage 3 QLoRA/LoRA SFT；
- Stage 4 GRPO training 和 rollout generation。

如果使用双 4090，Stage 4 的推荐部署方式是分离 rollout serving 和 training：

```text
GPU 0: vLLM rollout serving / sampling
GPU 1: QLoRA/LoRA GRPO training
CPU bare metal: Docker reward workers, repo checkout/cache, artifact storage
```

当 rollout 需求更高时，也可以让两张 4090 都参与 rollout generation，再用梯度累积和较小
micro-batch 做训练；但这种方式需要更严格的队列控制，避免训练进程因为 rollout 或 reward
延迟而长时间空等。

## Checkpoints 和 Promotion Gates

### Gate 1：Stage 3 之前

- Stage 2 导出非空且有规模的 resolved-only dataset。
- SFT examples 在目标 chat/tool 格式下有效。
- 固定 held-out evaluation set 已定义。

### Gate 2：扩大 SFT 之前

- 100-300 样本的 smoke fine-tune 完成。
- 微调后的模型能跑通 agent loop。
- tool-call 格式没有回退。

### Gate 3：Stage 4 之前

- Stage 3 相比 baseline 有提升，或在性能持平时显著减少 operational errors。
- held-out performance 没有回退。
- reward evaluation 可以从保存的 predictions 可复现地运行。
- GRPO 冷启动 reward 在 GRPO candidate pool 上为正，或显著优于 Stage 1 baseline。
- reward distribution 不是全 0、全负，且不是主要由 invalid patch 和 timeout 失败主导。

### Gate 4：扩大 GRPO 之前

- 小规模 GRPO pilot 产生稳定训练指标。
- reward distribution 不是全 0 或全负。
- held-out evaluation 提升，或至少保住 Stage 3 的收益。
- 每个 resolved improvement 的 runtime cost 可接受。

## 未来可能的阻塞

数据质量阻塞：

- resolved trajectories 数量太少。
- teacher trajectories 包含噪声或低效行为。
- export format 不匹配 Qwen 预期的 chat template。
- 长 trajectories 超过训练上下文限制，或形成低信号样本。

训练阻塞：

- SFT 或 GRPO 时 4090 显存压力过大。
- tokenization 或 chat-template mismatch。
- SFT 后 catastrophic forgetting。
- SFT 改善格式，但不提升 solve rate。

Reward 阻塞：

- 稀疏 reward 让 GRPO 低效。
- 官方评测太慢，不适合 online RL。
- 模型 reward hacking 弱验证。
- 不同 repositories 和 languages 之间方差很高。

基础设施阻塞：

- Docker image 存储和清理失败。
- CPU、RAM 或 disk IO 限制 container throughput。
- Stage 2 teacher API rate limit。
- 长任务需要稳健的 resume 和 retry 行为。

评测阻塞：

- 过拟合 SWE-smith train distribution。
- 没有干净 held-out split。
- 与不断变化的 Stage 1 baseline 比较。
- 只看 resolved rate，而忽略 operational errors 上升。

## 推荐下一步

1. 完成 Stage 1 baseline，并保存不可变 metrics。
2. 生成 Stage 2 teacher trajectories，并只导出 resolved 样本。
3. 为导出的 SFT examples 构建 data-quality report。
4. 在 100-300 个样本上运行 Stage 3 QLoRA smoke。
5. 在固定 subset 上评测 smoke model。
6. 只有 smoke run 改善行为后，才扩大 Stage 3。
7. 延迟 GRPO，直到 Stage 3 有明确收益证据。

## 立场

Stage 3 应该被视为近期主要训练里程碑。Stage 4 是研究和基础设施里程碑。
在 SFT 改善 baseline 或减少 operational failure modes 之前，项目不应该投入大量
GRPO 资源。
