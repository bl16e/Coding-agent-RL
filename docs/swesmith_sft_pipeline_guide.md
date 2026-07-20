# SWE-smith SFT 数据生成流水线 — 服务器操作指南

本文档覆盖从空白服务器到产出 SFT 训练数据的完整流程。

---

## 目录

1. [架构概览](#1-架构概览)
2. [服务器要求](#2-服务器要求)
3. [首次部署](#3-首次部署)
4. [运行流水线](#4-运行流水线)
5. [配置参考](#5-配置参考)
6. [Docker 镜像生命周期](#6-docker-镜像生命周期)
7. [磁盘空间管理](#7-磁盘空间管理)
8. [监控与进度查看](#8-监控与进度查看)
9. [故障排查](#9-故障排查)
10. [高级用法](#10-高级用法)
11. [附录：完整命令索引](#11-附录完整命令索引)

---

## 1. 架构概览

```
                          ┌─────────────────────────┐
                          │   HuggingFace Dataset    │
                          │  SWE-bench/SWE-smith     │
                          │      ~52,000 实例        │
                          └──────────┬──────────────┘
                                     │
                          ┌──────────▼──────────────┐
                          │  Step 1: create-subset   │
                          │  按语言/repo/难度过滤     │
                          │  → ~8k-12k Python 实例   │
                          └──────────┬──────────────┘
                                     │
                          ┌──────────▼──────────────┐
                          │  Step 2: run-subset      │
                          │  并行: 每个实例 Docker    │
                          │  容器 + agent 修复 bug    │
                          │  → trajectories + patches│
                          └──────────┬──────────────┘
                                     │
                          ┌──────────▼──────────────┐
                          │  Step 3: eval            │
                          │  SWE-smith 官方评测       │
                          │  → resolved / not        │
                          └──────────┬──────────────┘
                                     │
                          ┌──────────▼──────────────┐
                          │  Step 4: export-sft      │
                          │  只导出 resolved 轨迹     │
                          │  → OpenAI chat JSONL     │
                          └─────────────────────────┘
```

**关键设计决策：**

- 只用 `coding-agent`（你自己的 agent），不依赖 SWE-agent
- 只导出 **resolved**（agent 成功修复的）轨迹，确保训练数据质量
- 语言过滤（默认 Python）+ PR 过滤 + FAIL_TO_PASS 区间过滤，精简到高质量子集
- 按 repo 排序实例 + 用后清理镜像，磁盘只保留 `jobs` 数量级的 Docker 镜像

---

## 2. 服务器要求

### 硬件

| 资源 | 最低 | 推荐 |
|------|------|------|
| CPU 核心 | 8 | 32+ |
| 内存 | 32 GB | 64 GB+ |
| 磁盘 | 100 GB SSD | 200 GB+ SSD |
| 网络 | 100 Mbps | 1 Gbps |

### 软件

| 组件 | 版本 |
|------|------|
| 操作系统 | **Ubuntu 22.04 LTS**（SWE-smith 唯一官方支持的 OS） |
| Docker | ≥ 24.0，Linux x86_64 容器模式 |
| Python | 3.11+ |

### 外部服务

| 服务 | 用途 | 是否需要 |
|------|------|----------|
| Docker Hub | 拉取 SWE-smith 预构建环境镜像 | **必须** |
| HuggingFace Hub | 下载 SWE-smith 数据集 | **必须** |
| LLM API | Agent 推理（OpenAI 兼容接口） | **必须**（或用 mock 测试） |
| GitHub | SWE-smith profiles 的元数据查询 | 可选（不传 `--reference-path` 则不需要） |

---

## 3. 首次部署

### 3.1 上传项目到服务器

```bash
# 从本地打包上传
tar czf coding-agent.tar.gz coding-agent/
scp coding-agent.tar.gz user@your-server:~/

# 在服务器上解压
ssh user@your-server
tar xzf coding-agent.tar.gz
cd coding-agent
```

### 3.2 一键部署

```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

这个脚本会依次完成：

1. 安装系统包（python3.11, git, curl, build-essential）
2. 安装 Docker CE 并启动 daemon
3. 创建 Python `.venv` 虚拟环境
4. 安装所有 Python 依赖（coding-agent + swebench + datasets + docker + ghapi + ...）
5. 检查 `Reference/SWE-smith/` 参考实现（不存在则自动 clone）
6. 创建 `.env` 模板（如不存在）

### 3.3 配置模型凭证

```bash
vim .env
```

填入你的 LLM API 信息：

```ini
PROVIDER=openai
MODEL=qwen3-coder-plus
API_KEY=sk-your-api-key-here
BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

支持任何 OpenAI 兼容接口（阿里 DashScope / DeepSeek / OpenAI / vLLM / 等）。

### 3.4 登录 Docker Hub

```bash
docker login
```

SWE-smith 的预构建镜像托管在 Docker Hub，不登录也可以拉取公开镜像，但登录后可以避免速率限制。

> **注意：** 如果在云服务器上使用代理，需要同时配置 Docker daemon 的代理设置和 shell 环境变量。

---

## 4. 运行流水线

### 4.1 完整运行（一键）

```bash
source .venv/bin/activate
./scripts/run_sft_pipeline.sh
```

这个命令会**顺序执行全部 4 步**，最终输出在 `sft_data/sft_<timestamp>.jsonl`。

### 4.2 分步运行

如果只想执行某几步：

```bash
# 只创建子集，不运行 agent
SUBSET_ONLY=1 ./scripts/run_sft_pipeline.sh

# 只运行 agent，不做评测和导出
RUN_ONLY=1 ./scripts/run_sft_pipeline.sh

# 跳过子集创建（已有子集文件时）
RESUME=1 ./scripts/run_sft_pipeline.sh
```

### 4.3 自定义参数运行

```bash
# 自定义并发度和超时
JOBS=16 MAX_STEPS=100 TIMEOUT_SEC=1800 ./scripts/run_sft_pipeline.sh

# 指定模型
MODEL=gpt-4o ./scripts/run_sft_pipeline.sh

# 用 mock backend 快速验证流程
BACKEND=mock ./scripts/run_sft_pipeline.sh

# 跑完不清理 Docker 镜像（保留缓存加速下次运行）
CLEANUP=0 ./scripts/run_sft_pipeline.sh

# 选择其他语言
LANGUAGES=python,javascript ./scripts/run_sft_pipeline.sh
```

### 4.4 使用原始 CLI

```bash
source .venv/bin/activate

# Step 1: 创建子集
coding-agent swesmith create-subset \
  --out data/my_subset.json \
  --split train \
  --require-pr \
  --min-fail-to-pass 2 \
  --max-fail-to-pass 5 \
  --languages python \
  --reference-path Reference/SWE-smith

# Step 2: 运行 agent
coding-agent swesmith run-subset \
  --subset data/my_subset.json \
  --output-dir runs/my_run \
  --max-steps 50 \
  --timeout-seconds 900 \
  --test-timeout-seconds 180 \
  --jobs 8 \
  --cleanup-images \
  --reference-path Reference/SWE-smith

# Step 3: 官方评测
coding-agent swesmith eval \
  --subset data/my_subset.json \
  --predictions runs/my_run/preds.jsonl \
  --run-id my_run \
  --workers 10 \
  --reference-path Reference/SWE-smith

# Step 4: 导出 SFT
coding-agent swesmith export-sft \
  --runs runs/my_run \
  --eval-dir logs/run_evaluation/my_run \
  --out sft_data/my_run.jsonl
```

---

## 5. 配置参考

### 流水线环境变量（`run_sft_pipeline.sh`）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MODEL` | (空，用 `.env`) | 覆盖模型名 |
| `BACKEND` | `openai-compatible` | `openai-compatible` 或 `mock` |
| `SPLIT` | `train` | HF 数据集 split |
| `MAX_STEPS` | `50` | 每个实例 agent 最大推理步数 |
| `TIMEOUT_SEC` | `900` | 每个实例最长运行秒数 |
| `TEST_TIMEOUT_SEC` | `180` | 单条测试命令最长秒数 |
| `JOBS` | `4` | 并行 worker 数 |
| `EVAL_WORKERS` | `10` | 评测并行容器数 |
| `MIN_FTP` | `2` | 最少 FAIL_TO_PASS 数 |
| `MAX_FTP` | `5` | 最多 FAIL_TO_PASS 数 |
| `LANGUAGES` | `python` | 逗号分隔的语言过滤器 |
| `REQUIRE_PR` | `1` | 只选 PR 实例 |
| `CLEANUP` | `1` | 跑完自动删除 Docker 镜像 |
| `SUBSET_ONLY` | `0` | 执行完 Step 1 后停止 |
| `RUN_ONLY` | `0` | 执行完 Step 2 后停止 |
| `RESUME` | `0` | 跳过 Step 1 |
| `RUN_ID` | `sft_<timestamp>` | 运行标识符 |

### 模型配置（`.env`）

| 变量 | 说明 | 示例 |
|------|------|------|
| `PROVIDER` | 提供商标识 | `openai` |
| `MODEL` | 模型名 | `qwen3-coder-plus` |
| `API_KEY` | API 密钥 | `sk-xxxx` |
| `BASE_URL` | API 端点 | `https://api.openai.com/v1` |

### 支持的语言

`python`, `c`, `cpp`, `csharp`, `go`, `java`, `javascript`, `php`, `ruby`, `rust`, `typescript`

---

## 6. Docker 镜像生命周期

### 核心机制

SWE-smith 为每个 GitHub 仓库维护一个预构建 Docker 镜像（托管在 Docker Hub），包含该仓库特定 commit 的完整开发环境。

```
┌──────────────────────────────────┐
│  swebench/swesmith.x86_64.       │
│  pandas-dev_1776_pandas.95280573 │  ← 133 个 Python repo 各有 1 个
└──────────────┬───────────────────┘
               │
               ├── instance 1 → container pandas-dev__pandas.95280573.pr_53652
               │                 (git checkout pr_53652, agent runs, container deleted)
               │
               ├── instance 2 → container pandas-dev__pandas.95280573.pr_42901
               │                 (git checkout pr_42901, agent runs, container deleted)
               │
               └── instance N → ...
```

### 复用策略

1. **实例按 repo 排序** → 同一 repo 的实例聚集在一起
2. **并行执行时**，每个线程从同一个 image 创建独立 container
3. `pull_image()` 只拉一次——Docker 层缓存命中
4. `get_container()` 每次创建新容器——`git checkout <instance_id>` 切换分支

### 清理策略

```
默认模式 (CLEANUP=1):
  运行开始 → 拉取 repo A 的 image
          → 处理 repo A 的 N 个实例（image 复用 N 次）
          → 拉取 repo B 的 image
          → 处理 repo B 的 M 个实例
          → ...
          → 全部完成后 docker rmi 所有 image

保留模式 (CLEANUP=0):
  运行结束后保留所有 image，下次运行不用重新拉取
  适合：连续运行多次流水线的场景
```

---

## 7. 磁盘空间管理

### 空间占用模型

```
峰值磁盘占用 = 并行 jobs 数 × 单个镜像大小 + 运行产物 + 系统开销

4 jobs  × 5 GB/image  =  20 GB   （同时存在的 Docker 镜像）
运行产物                =   3 GB   （trajectories + summaries + patches）
SFT 输出                =   1 GB   （最终 JSONL）
系统开销                =  10 GB   （OS + venv + 缓存）
─────────────────────────────────
总计                    ≈ 35 GB
```

100 GB SSD **足够**。不需要 500GB+。

### 手动管理 Docker 磁盘

```bash
# 查看当前镜像占用
docker system df

# 删除未使用的镜像
docker image prune -a

# 删除所有未使用的 Docker 资源
docker system prune -a --volumes

# 查看特定镜像
docker images | grep swesmith
```

### 查看运行产物

```bash
# 运行日志
du -sh runs/*/

# 每个实例的产物
ls runs/sft_20260721_100000/pandas-dev__pandas.95280573.pr_53652/
# trajectory.jsonl    agent 执行轨迹
# summary.json        运行摘要
# final.patch         agent 生成的 patch
# prediction.jsonl    SWE-smith 格式的 prediction
# sandbox.json        容器元数据
```

---

## 8. 监控与进度查看

### 实时进度

```bash
# 查看正在运行的 Docker 容器
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"

# 查看流水线日志
tail -f runs/sft_*/batch_summary.json  # 实时更新的汇总

# 统计完成进度
find runs/sft_*/ -name "summary.json" | wc -l  # 已完成的实例数
```

### 运行产物检查

```bash
# 查看某个实例的 agent 推理过程
cat runs/sft_*/instance_id/trajectory.jsonl | python -m json.tool | less

# 查看运行摘要（状态/步数/时间）
cat runs/sft_*/instance_id/summary.json | python -m json.tool

# 统计各状态数量
grep -r '"status"' runs/sft_*/batch_summary.json
```

### 评测结果

```bash
# 查看评测日志
ls logs/run_evaluation/sft_*/

# 统计 resolved 数量
find logs/run_evaluation/ -name "report.json" -exec grep -l '"resolved": true' {} \; | wc -l
```

---

## 9. 故障排查

### Docker daemon 不启动

```bash
sudo systemctl status docker
sudo systemctl start docker
sudo journalctl -u docker -n 50
```

### Docker 镜像拉取失败

```bash
# 检查网络和代理
docker pull hello-world

# 检查 Docker Hub 登录状态
docker info | grep Username

# 手动拉取特定镜像
docker pull swebench/swesmith.x86_64.pandas-dev_1776_pandas.95280573:latest
```

### 磁盘空间不足

```bash
# 紧急清理
docker system prune -a --force
docker volume prune --force

# 清理 pip 缓存
pip cache purge

# 检查大文件
du -sh /* 2>/dev/null | sort -rh | head -10
```

### Agent 实例报错

```bash
# 检查单个实例的错误
cat runs/sft_*/instance_id/summary.json | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('error','no error'))"

# 查看 batch_summary 中所有 errored 实例
python -c "
import json
with open('runs/sft_*/batch_summary.json') as f:
    data = json.load(f)
for task in data['tasks']:
    if task['status'] == 'errored':
        print(task['instance_id'], task['error'])
"
```

### 模型 API 调用失败

```bash
# 测试 API 连接
curl -s -X POST "$BASE_URL/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "'$MODEL'", "messages": [{"role": "user", "content": "hi"}]}' \
  | head -20

# 检查 .env 配置
cat .env
```

### 重置环境

```bash
# 完全重置（保留代码和 .env）
rm -rf .venv runs/ sft_data/ logs/ data/
docker system prune -a --force
./scripts/deploy.sh
```

---

## 10. 高级用法

### 10.1 只跑特定 repo

```bash
# 先创建子集看有哪些 repo
SUBSET_ONLY=1 ./scripts/run_sft_pipeline.sh

# 手动编辑子集文件，只保留目标 repo
python -c "
import json
data = json.load(open('data/subset.json'))
# 只保留 pandas 相关
filtered = [x for x in data if 'pandas' in x['instance_id']]
json.dump(filtered, open('data/pandas_only.json', 'w'))
"

# 用自定义子集运行
RESUME=1 SUBSET_FILE='data/pandas_only.json' ./scripts/run_sft_pipeline.sh
```

### 10.2 断点续跑

```bash
# 第一次：只创建子集
SUBSET_ONLY=1 ./scripts/run_sft_pipeline.sh

# 第二次：从已有子集继续，指定 RUN_ID
RESUME=1 RUN_ID=sft_20260721_100000 ./scripts/run_sft_pipeline.sh
```

### 10.3 分阶段执行（推荐大子集）

```bash
# Phase 1: 创建子集 + 运行 agent（最耗时）
RUN_ONLY=1 RUN_ID=my_batch_001 ./scripts/run_sft_pipeline.sh
# 可能需要数小时到数天，取决于实例数和 JOBS

# Phase 2: 评测
RUN_ID=my_batch_001 ./scripts/run_sft_pipeline.sh
# 实际上 RESUME=1 会跳过 subset 创建，但还不会跳过 run
# 使用原始 CLI 手动执行后续步骤
coding-agent swesmith eval \
  --subset data/subset.json \
  --predictions runs/my_batch_001/preds.jsonl \
  --run-id my_batch_001 \
  --workers 10 \
  --reference-path Reference/SWE-smith

coding-agent swesmith export-sft \
  --runs runs/my_batch_001 \
  --eval-dir logs/run_evaluation/my_batch_001 \
  --out sft_data/my_batch_001.jsonl
```

### 10.4 多机并行

当前不支持内置多机并行，但可以通过以下方式实现：

```bash
# 机器 0：处理子集的前 1/3
python -c "
import json
data = json.load(open('data/subset.json'))
chunk_size = len(data) // 3
json.dump(data[:chunk_size], open('data/subset_chunk0.json', 'w'))
"
SUBSET_FILE=data/subset_chunk0.json RUN_ID=chunk0 ./scripts/run_sft_pipeline.sh

# 机器 1、机器 2 同理...
# 最后合并 SFT 输出
cat sft_data/chunk0.jsonl sft_data/chunk1.jsonl sft_data/chunk2.jsonl > sft_data/merged.jsonl
```

### 10.5 使用本地模型（vLLM）

```bash
# 启动 vLLM 服务
python -m vllm.entrypoints.openai.api_server \
  --model /path/to/your/model \
  --port 8000

# 配置 .env 指向本地
PROVIDER=openai
MODEL=your-model-name
API_KEY=not-needed
BASE_URL=http://localhost:8000/v1
```

---

## 11. 附录：完整命令索引

### 部署

```bash
./scripts/deploy.sh                                  # 一键部署
docker login                                          # 登录 Docker Hub
vim .env                                              # 配置模型凭证
```

### 流水线

```bash
./scripts/run_sft_pipeline.sh                         # 完整运行
SUBSET_ONLY=1 ./scripts/run_sft_pipeline.sh           # 只创建子集
RUN_ONLY=1 ./scripts/run_sft_pipeline.sh              # 只运行 agent
RESUME=1 ./scripts/run_sft_pipeline.sh                # 跳过子集创建

JOBS=8 MAX_STEPS=100 ./scripts/run_sft_pipeline.sh    # 自定义参数
BACKEND=mock ./scripts/run_sft_pipeline.sh            # 测试模式
CLEANUP=0 ./scripts/run_sft_pipeline.sh               # 保留 Docker 镜像
```

### 原始 CLI

```bash
coding-agent swesmith create-subset --out <path> --languages python --reference-path Reference/SWE-smith
coding-agent swesmith run-subset --subset <path> --output-dir <dir> --jobs 8 --cleanup-images --reference-path Reference/SWE-smith
coding-agent swesmith eval --subset <path> --predictions <preds> --run-id <id> --reference-path Reference/SWE-smith
coding-agent swesmith export-sft --runs <dir> --eval-dir <dir> --out <path>
```

### 监控与维护

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"     # 运行中的容器
docker system df                                       # Docker 磁盘占用
find runs/ -name "summary.json" | wc -l                # 已完成实例数
docker system prune -a --force                         # 清理所有未用 Docker 资源
```

---

## 快速参考卡片

```
┌─────────────────────────────────────────────────────────────┐
│  从零到 SFT 数据 — 最小步骤                                  │
│                                                             │
│  1. 上传项目到 Ubuntu 22.04 服务器                           │
│  2. ./scripts/deploy.sh                                     │
│  3. vim .env                    # 填 API_KEY                │
│  4. docker login                                            │
│  5. ./scripts/run_sft_pipeline.sh                           │
│                                                             │
│  输出: sft_data/sft_<timestamp>.jsonl                       │
│  格式: OpenAI chat JSONL，可直接用于 SFT 训练                │
│                                                             │
│  时间估算 (JOBS=8, ~10k 实例, 每实例 ~10 分钟):              │
│    10,000 × 10 min ÷ 8 ÷ 60 ≈ 208 小时 ≈ 9 天              │
│                                                             │
│  模型 API 成本估算 (~10k 实例, ~7k tokens/实例):             │
│    ≈ 70M tokens × 模型价格                                   │
└─────────────────────────────────────────────────────────────┘
```
