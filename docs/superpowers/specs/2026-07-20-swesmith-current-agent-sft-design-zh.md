# SWE-smith 当前 Agent SFT 流水线设计

## 概要

构建一条 SWE-smith 训练轨迹流水线：使用当前项目的 `coding_agent`
agent runner，而不是 SWE-agent；同时尽最大可能遵循 SWE-smith 官方的数据集、
runtime profile、镜像/容器、评测，以及只收集 resolved 轨迹用于训练的数据收集语义。

目标工作流如下：

```text
SWE-smith subset
-> SWE-smith 官方 profile/image/container
-> coding_agent 解题
-> SWE-smith 官方评测判定 resolved 状态
-> 只导出 resolved trajectories 为 SFT JSONL
```

第一版不集成 torchtune、Modal、sglang serving 或模型训练。它只产出可被这些系统消费的训练数据集。

## 目标

- 使用当前 `coding_agent` 的 agent loop、tool executor、trajectory writer、
  prediction writer 和 artifact contract，运行 SWE-smith 生成的任务实例。
- 使用 SWE-smith 官方 repository profiles 和容器假设来搭建任务 runtime，
  而不是把 SWE-smith metadata 翻译成本项目现有的 SWE-Bench Lite runtime metadata。
- 使用 SWE-smith 官方评测语义判定生成的 patch 是否解决了实例。
- 只导出 resolved trajectories 到 OpenAI 风格 chat JSONL，用于 SFT。
- 以可复现的本地 subset 文件作为主要输入，同时提供可选辅助能力，从 Hugging Face
  `SWE-bench/SWE-smith` 数据集创建此类文件。

## 非目标

- 不运行 SWE-agent，也不依赖 SWE-agent trajectory 格式。
- 不替换现有 `src/coding_agent/swebench/` SWE-Bench Lite 官方 runtime。
- 不把 SWE-smith profile metadata 复制到
  `src/coding_agent/swebench/repo_specs.py`。
- 不导出 unresolved trajectories 用于 SFT。
- 第一版不添加训练执行、Modal 上传、torchtune 启动或 sglang serving。
- 当 SWE-smith profiles、mirrors、images 或 containers 不可用时，不静默回退到猜测的 runtime metadata。

## 架构

新增一个集成命名空间：

```text
src/coding_agent/swesmith/
|-- __init__.py
|-- dataset.py
|-- runtime.py
|-- run.py
|-- evaluate.py
`-- export_sft.py
```

这样可以把 SWE-smith 集成和现有 SWE-Bench Lite runtime refactor 分离。
新命名空间是 SWE-smith 官方 harness 行为和当前 `coding_agent` agent runner
之间的桥接层。

### `dataset.py`

职责：

- 加载 `.json` 和 `.jsonl` 格式的 SWE-smith subset 文件。
- 校验必要实例字段，至少包括 `instance_id`、`problem_statement`，
  以及 SWE-smith profile/evaluation 代码所需字段。
- 可选地从 `SWE-bench/SWE-smith` 创建本地 subset 文件，筛选条件可由用户提供或使用内置条件。

默认的 `run-subset` 路径只接受本地 subset 文件。Hugging Face 加载能力通过
`create-subset` 暴露，这样实际解题运行保持可复现，并且不依赖网络访问。

### `runtime.py`

职责：

- 从配置的 reference checkout 导入 SWE-smith。
- 通过 `swesmith.profiles.registry.get_from_inst(instance)` 解析 SWE-smith profile。
- 使用 SWE-smith 官方 profile/runtime 路径创建任务容器。

优先实现方式是在可行时直接调用 SWE-smith 的 `RepoProfile.get_container(instance)`。
如果为了捕获 metadata 需要加一层小 wrapper，也必须保留相同语义：
profile image、SWE-smith Docker workdir/user、container start，以及
`git checkout <instance_id>`。

SWE-smith 导入失败、profile 缺失、image 缺失、image pull/build 失败、
mirror 缺失和 checkout 失败都属于输入/runtime 失败。
集成层不能回退到当前项目的 SWE-Bench Lite `build_adapted_testspec` 路径。

### `run.py`

职责：

- 使用当前 `coding_agent` agent 运行一个或多个 SWE-smith 实例。
- 将 `ContainerToolExecutor` 连接到 SWE-smith 创建的容器和官方 repository workdir。
- 使用 SWE-smith instance 的 `problem_statement` 作为任务 prompt。
- 为每个实例持久化现有 artifact contract：
  `trajectory.jsonl`、`trajectory.json`、`summary.json`、`final.patch`、
  `prediction.jsonl` 和 `sandbox.json`。
- 写出一个 batch 级别的 predictions 文件，供 SWE-smith 官方评测使用。

agent runner 仍由宿主侧拥有。SWE-smith 拥有 repository 环境和 benchmark validation 语义。

### `evaluate.py`

职责：

- 对 subset 和 predictions 文件调用 SWE-smith 官方评测语义。
- 优先使用与官方命令兼容的路径：

```bash
python -m swesmith.harness.eval \
  --dataset_path <subset> \
  --predictions_path <predictions> \
  --run_id <run_id> \
  --workers <workers> \
  --timeout <timeout>
```

- 保留官方输出结构：`logs/run_evaluation/<run_id>/`，包括每个实例的
  `report.json` 和 batch report。
- 只有在能产生等价 report 语义和位置时，才支持 in-process wrapper。

resolved 状态从 SWE-smith report 数据读取，不从本地 test command 或 agent self-validation 推断。

### `export_sft.py`

职责：

- 读取 run artifacts 和 SWE-smith eval reports。
- 只选择 SWE-smith report 中 `resolved: true` 的实例。
- 将当前 `coding_agent` trajectories 转换成 OpenAI 风格 chat JSONL：

```json
{"messages":[{"role":"system","content":"..."},{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}
```

- 支持受 SWE-smith `transform_traj_xml` 启发的 XML function-call 风格，
  但要适配当前 `coding_agent` 的 tool schema 和 trajectory events。
- 在字段稳定时包含有用 metadata，例如 `instance_id`、`resolved`、`model`、
  `traj_id` 和 `patch`。

exporter 消费当前项目 artifacts，不消费 SWE-agent `.traj` 文件。

## CLI 表面

新增 `swesmith` command group：

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

`run-subset` 应写出名为 `preds.json` 或 `preds.jsonl` 的 batch prediction 文件。
所选格式必须能被 SWE-smith 官方评测接受。该命令还应写出 batch summary，
包含每个实例的状态和 artifact 路径。

## 数据流

1. `create-subset` 可选加载 `SWE-bench/SWE-smith`，筛选实例，并写出本地 subset 文件。
2. `run-subset` 读取 subset 文件并校验实例记录。
3. 对每个实例，`runtime.py` 解析 SWE-smith profile，并创建 SWE-smith 官方任务容器。
4. `run.py` 在该容器上执行当前 `coding_agent`，并写出每实例 artifacts。
5. `run.py` 提取 final patch，并写出 prediction record。
6. `eval` 使用 subset 和 predictions 调用 SWE-smith 官方评测。
7. `export-sft` 读取评测 reports，只保留 resolved 实例，并写出 SFT JSONL。

## 错误处理

- 如果无法导入 SWE-smith，失败并给出 setup 指引，指向配置的 reference checkout 和 `PYTHONPATH`。
- 如果某个实例没有注册的 SWE-smith profile，在 agent 执行前失败该实例。
- 如果 profile image 找不到或无法 pull，暴露 SWE-smith 错误，并指向 SWE-smith 环境/image 准备流程。
- 如果容器创建或 checkout 失败，将实例标记为 runtime error，不运行 agent。
- 如果 agent 没有生成 patch，写出空 `model_patch` prediction，让 SWE-smith 评测将其判为 unresolved。
- 如果评测超时或失败，保留 SWE-smith logs，并显式标记 evaluation 状态。
- 如果 artifact 持久化失败，返回与现有 benchmark runs 相同的 artifact-error 行为。

## 测试

默认自动化测试使用 fakes 隔离 SWE-smith 和 Docker 边界。

单元测试覆盖：

- `.json` 和 `.jsonl` subset 加载与校验
- 通过 fake SWE-smith registry/profile 做 profile lookup 和 container metadata
- SWE-smith-compatible prediction 文件生成
- evaluation report 读取和 resolved 筛选
- SFT exporter 输出格式和 unresolved 排除

集成测试覆盖：

- fake end-to-end `run-subset -> eval report -> export-sft`
- artifact 路径和 batch summary 一致性
- SWE-smith 不可用时的 import/setup 错误

手动或 opt-in 覆盖：

- 真实 `Reference/SWE-smith` 导入
- 真实 profile container 创建
- 真实 SWE-smith `python -m swesmith.harness.eval`
- 一个小型真实 subset，产出 predictions 和 resolved-only SFT output

默认自动化测试不应要求 Docker、Hugging Face 网络访问、GitHub mirrors 或 SWE-smith image downloads。

## 实现说明

- 第一版应新增 `swesmith` 命名空间和 CLI，不重构现有 SWE-Bench Lite runtime modules。
- 如果 `Reference/SWE-smith` checkout 仍保持 vendored/untracked 状态，命令应接受 reference path
  或环境变量，以便显式导入它。
- SFT exporter 应保持确定性：稳定的实例排序、尽可能稳定的 JSON key 顺序，以及基于 run path
  和 instance id 的稳定 `traj_id` 生成。
- Batch solving 可以从 `workers=1` 开始；在共享 SWE-smith image/container 行为验证后再加入并行。
- 未来若支持非 Python SWE-smith profiles，应由官方 SWE-smith profile registry 驱动，
  而不是新增项目本地 metadata。
