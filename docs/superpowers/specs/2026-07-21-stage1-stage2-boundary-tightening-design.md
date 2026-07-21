# Stage 1/2 边界收紧设计

## 概览

本设计将项目收紧到两个明确的工作流阶段：

- Stage 1：通过本地 vLLM 的 OpenAI-compatible endpoint，在 SWE-Bench Lite
  上评测 `Qwen2.5-Coder-7B-Instruct`。
- Stage 2：通过外部 teacher model API 生成高质量 SWE-smith teacher
  trajectories，运行 SWE-smith 官方评测，并只导出 resolved trajectories
  供后续 SFT 使用。

当前实现已经具备必要的底层能力，但工作流边界不够硬。Stage 1 和 Stage 2
都使用通用 OpenAI-compatible 模型配置；文档仍然引导用户直接使用通用
`swebench` 和 `swesmith` 命令；legacy SWE-Bench registry/sandbox 路径也仍然
以正向 runtime 代码和测试的形式存在。

这次变更会让两个阶段成为一等入口，按阶段隔离模型配置，并移除 legacy
SWE-Bench runtime helper 的受支持正向使用面。

## 目标

- 提供显式 Stage 1 命令和脚本，用于 Qwen2.5 local-vLLM SWE-Bench Lite
  evaluation。
- 提供显式 Stage 2 命令和脚本，用于 teacher-API SWE-smith trajectory
  generation。
- 防止 Stage 1 的 vLLM 配置被误用于 Stage 2 teacher runs，反之亦然。
- 删除或隔离 legacy SWE-Bench registry/sandbox 正向流程，使其不再看起来像
  受支持路径。
- 保持现有 official-style SWE-Bench runtime 和 SWE-smith integration 语义不变。
- 默认自动化测试继续使用 fake 隔离，不依赖 Docker、vLLM、teacher API、
  Hugging Face 网络访问或真实 SWE-smith images。

## 非目标

- 不实现 Stage 3 SFT 或 Stage 4 GRPO。
- 不替换现有 official-style SWE-Bench prepare/run/batch 内部实现，除非这是干净
  暴露 Stage 1 所必需的。
- 不删除通用 OpenAI-compatible backend；只在命令边界隔离 stage-specific
  configuration。
- 如果 `sandbox register/list` 在新 benchmark runtime 路径之外仍有用途，不删除它们。
- 不把真实 vLLM 或 teacher API smoke tests 加入默认测试套件。

## 命令表面

新增 `stage1` command group：

```bash
coding-agent stage1 run-qwen-vllm \
  --dataset data/dev-00000-of-00001.parquet \
  --dataset data/test-00000-of-00001.parquet \
  --output-dir runs/stage1_qwen25_lite \
  --max-steps 50 \
  --timeout-seconds 900 \
  --test-timeout-seconds 180 \
  --jobs 1 \
  --resume
```

该命令底层使用 official SWE-Bench Lite batch runtime。它不应暴露 legacy
registry 或 sandbox 选项。它可以接受与 `swebench batch-run` 相同的 runtime-safe
batch controls，包括 `--build-missing`、`--replace-existing`、`--resume`、
`--include-pass-to-pass`、`--cleanup` 和 `--arch`，前提是这些选项已经映射到
official runtime。

新增 `stage2` command group：

```bash
coding-agent stage2 generate-teacher-trajectories \
  --subset data/subset.json \
  --output-dir runs/stage2_teacher \
  --reference-path Reference/SWE-smith \
  --max-steps 80 \
  --timeout-seconds 1200 \
  --test-timeout-seconds 180 \
  --jobs 4 \
  --eval-workers 4 \
  --run-id stage2_teacher \
  --sft-output sft_data/stage2_teacher.jsonl
```

该命令编排现有 SWE-smith 流程：

```text
run-subset -> official eval -> export-sft
```

它还应允许 subset-creation mode，或者接受一个已存在的 subset。第一版实现可以
复用当前 `swesmith create-subset`、`run-subset`、`eval` 和 `export-sft` helper，
而不是复制这些 helper 的内部逻辑。

通用 `swebench` 和 `swesmith` 命令可以保留给 lower-level use，但 README 和 stage
文档应把 `stage1` 和 `stage2` 作为常规工作流入口。

## 模型配置

新增 stage-specific model configuration loading。

Stage 1 读取：

```text
STAGE1_PROVIDER
STAGE1_MODEL
STAGE1_API_KEY
STAGE1_BASE_URL
```

推荐值：

```text
STAGE1_PROVIDER=openai
STAGE1_MODEL=qwen2.5-coder-7b
STAGE1_API_KEY=not-needed
STAGE1_BASE_URL=http://vllm-stage1.internal:8000/v1
```

Stage 2 读取：

```text
STAGE2_PROVIDER
STAGE2_MODEL
STAGE2_API_KEY
STAGE2_BASE_URL
```

推荐值应指向 teacher API provider。

如果对应阶段的环境变量缺失，stage commands 必须在任务执行前失败，并给出清晰的
input error。它们不能静默 fallback 到通用 `PROVIDER`、`MODEL`、`API_KEY` 或
`BASE_URL`。Lower-level generic commands 可以继续使用现有通用配置，以保持兼容。

`--model` 可以继续作为 stage model name 的 CLI override，但它不能 override
provider、API key 或 base URL。

## 脚本

新增 Stage 1 脚本：

```text
scripts/run_stage1_qwen_vllm.sh
```

职责：

- 校验 `STAGE1_*` 配置。
- 打印目标 vLLM endpoint 和 model name。
- 运行 `coding-agent stage1 run-qwen-vllm`。
- 保持默认参数保守：`jobs=1`、`max_steps=50`、`timeout_seconds=900`、
  `test_timeout_seconds=180`。

新增 Stage 2 脚本：

```text
scripts/run_stage2_teacher_trajectories.sh
```

职责：

- 校验 `STAGE2_*` 配置。
- 创建或复用 SWE-smith subset。
- 运行 `coding-agent stage2 generate-teacher-trajectories`。
- 将 resolved-only SFT data 作为最终 artifact 导出。

现有 `scripts/run_sft_pipeline.sh` 应被 deprecated、重命名，或者变成一个带
deprecation warning 的薄 compatibility wrapper，内部调用 Stage 2 脚本。推荐名称应描述
Stage 2 teacher trajectory generation，而不是 Stage 3 SFT training。

## 快速环境部署

保留并升级现有快速配置环境部署脚本：

```text
scripts/deploy.sh
```

该脚本是新机器上的 bootstrap 入口，不属于 Stage 1 或 Stage 2 本身，但必须为两
个阶段准备共同运行环境。

职责：

- 校验目标系统、Python、Docker、Git 和基础构建工具。
- 创建或复用 `.venv`，安装 `coding-agent` 以及 SWE-Bench/SWE-smith 所需依赖。
- 准备 `Reference/SWE-smith` checkout，或校验用户提供的 `SWE_SMITH_REF`。
- 创建标准目录结构，例如 `data/`、`runs/`、`sft_data/` 和 `logs/`。
- 生成 stage-specific 环境变量模板，而不是只生成通用 `.env`：
  - `.env.stage1.example`：包含 `STAGE1_PROVIDER`、`STAGE1_MODEL`、
    `STAGE1_API_KEY`、`STAGE1_BASE_URL`。
  - `.env.stage2.example`：包含 `STAGE2_PROVIDER`、`STAGE2_MODEL`、
    `STAGE2_API_KEY`、`STAGE2_BASE_URL`。
- 如果保留 `.env`，只能把它标记为 lower-level generic commands 的兼容配置；
  Stage 1/2 推荐路径必须使用 stage-specific env。
- 部署完成后的 next steps 应指向：
  - `scripts/run_stage1_qwen_vllm.sh`
  - `scripts/run_stage2_teacher_trajectories.sh`

`deploy.sh` 不应启动真实 vLLM、不应保存真实 teacher API key，也不应强制下载大型
benchmark images。镜像准备和真实模型服务应由 Stage 1/2 脚本或手动运行步骤触发。

## Legacy SWE-Bench Runtime 清理

删除或隔离 legacy SWE-Bench runtime 正向 helper：

- `prepare_swebench_sandbox`
- `solve_prepared_sandbox`
- `run_swebench_task`
- `prepare_swebench_sandboxes`
- `solve_swebench_sandboxes`
- `run_swebench_tasks`
- 仅被这些 helper 使用的 legacy registry-backed `load_base_image_from_registry` 路径

CLI 应继续拒绝旧的 user-visible legacy commands，例如：

- `swebench prepare-sandbox`
- `swebench solve-sandbox`
- `swebench prepare-sandboxes`
- `swebench solve-sandboxes`
- 在 official Stage 1/SWE-Bench runtime commands 上传入 `--registry`

删除正向路径后，实现应移除 unused imports 和 dead command handlers。如果某个旧 helper
仍被无关的 non-runtime tests 需要，应移动到命名清晰的 legacy module，并停止从正常 CLI
dispatch 暴露。

## 文档

更新 README 和 workflow docs，使下面的流程成为 canonical flow：

```text
Stage 1 baseline:
  local vLLM + Qwen2.5-Coder-7B-Instruct -> SWE-Bench Lite metrics

Stage 2 teacher data:
  teacher API -> SWE-smith runs -> official eval -> resolved-only export
```

文档应提示 Stage 1 和 Stage 2 使用不同环境变量，通常应从不同 shell 或不同 `.env`
文件运行。

如果文档提到用 local vLLM 跑 SWE-smith，需要明确说明：这是通用 lower-level
capability，不是推荐的 Stage 2 teacher-data path。

## 错误处理

- Stage 1 环境变量缺失时，在 SWE-Bench task execution 前失败。
- Stage 2 环境变量缺失时，在 SWE-smith task execution 前失败。
- Stage 1 拒绝 teacher-only options 和 legacy registry/sandbox options。
- Stage 2 拒绝 Stage 1-only options，并要求提供 existing subset，或提供足够的
  subset-creation arguments。
- Stage 2 可以在 per-instance runtime errors 后继续，并只导出 resolved examples；
  这保持现有 SWE-smith partial-results behavior。
- Artifact persistence failures 保持现有 exit-code semantics。

## 测试

新增或更新 contract tests，覆盖：

- `stage1 run-qwen-vllm` 参数解析，以及 dispatch 到 official SWE-Bench batch
  runtime。
- Stage 1 从 `STAGE1_*` 加载配置，并且不 fallback 到 `STAGE2_*` 或 generic model
  variables。
- `stage2 generate-teacher-trajectories` dispatch 到 SWE-smith run/eval/export flow。
- Stage 2 从 `STAGE2_*` 加载配置，并且不 fallback 到 `STAGE1_*` 或 generic model
  variables。
- Deprecated 或 legacy SWE-Bench commands 在 agent execution 前被拒绝。

删除或重写 legacy registry/sandbox SWE-Bench runtime helper 的正向测试。保留
official-style SWE-Bench runtime 和 SWE-smith helper 的测试。

Focused verification 应包括：

```bash
python -m pytest \
  tests/contract/test_cli_swebench_runtime_contract.py \
  tests/contract/test_cli_swebench_run_contract.py \
  tests/contract/test_cli_swesmith_contract.py \
  tests/unit/test_openai_compatible_config.py \
  tests/unit/test_swesmith_run.py \
  tests/unit/test_swesmith_export_sft.py \
  tests/integration/test_swebench_official_runtime.py \
  tests/integration/test_swesmith_pipeline_fake.py \
  -q
```

## 迁移说明

低层 `swebench batch-run` 和 `swesmith` command groups 的现有用户可以在迁移期继续
使用它们，但 stage documentation 和 scripts 不应再把 primary workflow 引导到这些 generic
entry points。

现有 artifacts 保持有效。本次边界收紧影响 command selection、configuration loading、
script names，以及 obsolete positive legacy runtime code 的移除；它不要求重写旧 run
directories。
