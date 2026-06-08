# coding-agent

`coding-agent` 是一个面向 SWE-Bench Lite 任务的 Python CLI/库。它一次运行一个
编码代理任务，支持两种执行位置：

- 已准备好的本地仓库工作区。
- 已注册的 SWE-Bench 兼容 Docker 任务沙箱。

宿主进程负责模型调用、预算控制、轨迹记录和产物落盘；仓库读写、代码搜索和测试执行
通过受限工具完成。Docker 模式下，这些工具会在任务容器内执行，避免宿主机工作区被
直接修改。

## 当前范围

已支持：

- 单任务运行，不做批量调度。
- Mock 模型后端和 OpenAI-compatible 模型后端。
- 四个仓库工具：`read_file`、`apply_patch`、`search_code`、`run_tests`。
- 运行产物：`trajectory.jsonl`、`trajectory.json`、`final.patch`、
  `summary.json`、`prediction.jsonl`。
- SWE-Bench Docker 模式的基础镜像注册、任务容器创建、base commit checkout、
  `FAIL_TO_PASS` 默认验证、可选 `PASS_TO_PASS` 回归验证。
- Docker 模式额外写入 `sandbox.json`，记录镜像、容器、仓库路径和验证命令来源。

暂不支持：

- 自动构建缺失的官方 SWE-Bench 镜像。
- 多任务 benchmark 批量编排。
- 让模型执行任意 shell 命令。
- 在未注册或未标记 `official_compatible` 的镜像中运行 SWE-Bench 沙箱任务。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
```

项目要求 Python 3.11+。读取本地 parquet 数据集需要 `pyarrow`，开发依赖中已经包含
测试所需工具。

## 本地工作区运行

本地模式假设目标仓库已经存在，并且依赖环境已经由调用方准备好。代理只在
`--workspace` 指定目录内读写文件，测试命令必须精确匹配 `--allowed-test`。

```powershell
coding-agent run `
  --backend mock `
  --instance-id example__repo-1 `
  --workspace D:\tmp\swebench-task-workspace `
  --problem-statement-file D:\tmp\problem.txt `
  --allowed-test "python -m pytest tests/test_example.py" `
  --max-steps 20 `
  --timeout-seconds 600 `
  --test-timeout-seconds 120 `
  --output-dir D:\tmp\swebench-agent-run
```

常用参数：

- `--max-steps`：模型最多决策轮数。
- `--timeout-seconds`：整次运行总预算。
- `--test-timeout-seconds`：单次测试命令超时时间。
- `--backend mock`：无需真实模型，适合合同测试和流程验证。
- `--backend openai-compatible`：使用真实 OpenAI-compatible 服务。

## SWE-Bench Docker 沙箱运行

Docker 模式先注册一个已经准备好的仓库基础镜像，再从数据集中选择一个
`instance_id` 运行。注册表只记录镜像元数据，不负责构建镜像。

### 注册基础镜像

```powershell
coding-agent sandbox register `
  --repo django/django `
  --image swebench-django-official:latest `
  --repo-path /workspace/repo `
  --registry .coding-agent/sandboxes.json `
  --official-compatible `
  --validation-command-template "python -m pytest {tests}"
```

参数说明：

- `--repo` 必须匹配 SWE-Bench 数据集里的 `repo` 字段。
- `--image` 是本地 Docker 可 inspect 的镜像名。
- `--repo-path` 是容器内仓库根目录。
- `--official-compatible` 表示调用方确认该镜像兼容官方 SWE-Bench 任务环境。
- `--validation-command-template` 必须包含 `{tests}`，用于没有 `eval_script` 时生成测试命令。

查看注册表：

```powershell
coding-agent sandbox list --registry .coding-agent/sandboxes.json
```

### 运行一个数据集实例

```powershell
coding-agent swebench run `
  --dataset data/dev-00000-of-00001.parquet `
  --instance-id django__django-11099 `
  --registry .coding-agent/sandboxes.json `
  --backend mock `
  --max-steps 20 `
  --timeout-seconds 900 `
  --test-timeout-seconds 180 `
  --output-dir runs/django__django-11099
```

运行流程：

1. 从 parquet 数据集中读取 `instance_id` 对应任务。
2. 按任务的 `repo` 查找已注册基础镜像。
3. 拒绝未标记 `official_compatible` 的镜像。
4. 创建任务容器并在容器内 checkout 到 `base_commit`。
5. 用 `FAIL_TO_PASS` 构造默认测试命令。
6. 注入容器内工具执行器并运行同一个 agent loop。
7. 停止并删除任务容器，保留运行产物。

默认只验证 `FAIL_TO_PASS`。需要同时加入 `PASS_TO_PASS` 时添加：

```powershell
--include-pass-to-pass
```

## 产物说明

每次运行的输出目录包含：

- `trajectory.jsonl`：逐步记录模型决策和工具结果，便于审计。
- `trajectory.json`：更接近 SWE-Bench 常见汇总格式的轨迹视图。
- `final.patch`：运行前后工作区差异。
- `summary.json`：状态、预算、测试摘要、变更文件和产物路径。
- `prediction.jsonl`：SWE-Bench 预测格式，包含 `instance_id`、模型名和 patch。
- `sandbox.json`：仅 Docker 沙箱模式存在，记录容器和验证元数据。

检查一次运行：

```powershell
coding-agent inspect --run-dir D:\tmp\swebench-agent-run
```

重新导出 prediction：

```powershell
coding-agent export-prediction `
  --run-dir D:\tmp\swebench-agent-run `
  --model-name mock-model `
  --output D:\tmp\predictions.jsonl
```

## 真实模型配置

`--backend openai-compatible` 会从进程环境或仓库根目录 `.env` 读取：

- `PROVIDER`
- `MODEL`
- `API_KEY`
- `BASE_URL`

也可以通过 `--model` 覆盖 `.env` 中的 `MODEL`。

## 项目结构

```text
src/coding_agent/
|-- cli.py                         # CLI 参数、子命令和退出码映射
|-- agent.py                       # 代理主循环、预算、轨迹和产物持久化
|-- models.py                      # 运行、工具、沙箱和预测的数据契约
|-- tools/                         # 本地工作区工具实现
|-- sandbox/                       # Docker CLI、镜像注册表、容器生命周期和容器工具
|-- swebench/                      # 数据集读取、验证命令构造、沙箱运行编排和预测导出
`-- trajectory/                    # 轨迹写入、摘要、patch 和格式转换
```

详细设计见 `specs/002-swebench-docker-sandbox/plan.md`。

## 测试

运行全部测试：

```powershell
python -m pytest
```

按范围运行：

```powershell
python -m pytest tests\unit
python -m pytest tests\contract
python -m pytest tests\integration
```

Docker 相关单元和合同测试大量使用 fake/mocks；真实 Docker 镜像的端到端验证需要调用方
先准备并注册兼容镜像。
