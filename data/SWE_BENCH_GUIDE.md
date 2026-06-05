# SWE-bench Lite 数据集使用指南

## 1. 数据集概述

SWE-bench lite 是一个用于评估 AI 模型在真实软件工程任务上表现的基准数据集。每个样例都来自真实的 GitHub issue 和对应的代码修复。

### 数据集规模

- **Dev set**: 23 个样例（用于开发和验证）
- **Test set**: 300 个样例（用于最终测试）
- **总计**: 323 个任务

### 涉及的代码仓库

数据集包含 18 个不同的开源项目：

| 仓库 | 任务数 | 占比 |
|------|--------|------|
| django/django | 114 | 35% |
| sympy/sympy | 77 | 24% |
| matplotlib/matplotlib | 23 | 7% |
| scikit-learn/scikit-learn | 23 | 7% |
| pytest-dev/pytest | 17 | 5% |
| sphinx-doc/sphinx | 16 | 5% |
| 其他 12 个项目 | 53 | 16% |

## 2. 数据结构

每个样例包含以下字段：

| 字段 | 说明 | 示例 |
|------|------|------|
| `repo` | GitHub 仓库路径 | `sqlfluff/sqlfluff` |
| `instance_id` | 唯一标识符 | `sqlfluff__sqlfluff-1625` |
| `base_commit` | 起始代码版本 | `14e1a23a3166...` |
| `patch` | 正确的代码修复 (diff 格式) | `diff --git a/src/...` |
| `test_patch` | 测试用例修改 | `diff --git a/test/...` |
| `problem_statement` | 问题描述 (GitHub issue 内容) | 完整的 bug 报告 |
| `hints_text` | 额外提示信息 | 相关讨论或注释 |
| `FAIL_TO_PASS` | 修复后应通过的测试 | `["test/cli/commands_test.py::test__cli__command_directed"]` |
| `PASS_TO_PASS` | 应继续通过的测试 | 回归测试列表 |
| `environment_setup_commit` | 环境配置所需的 commit | `67023b85c41d...` |
| `version` | 项目版本 | `0.6` |
| `created_at` | Issue 创建时间 | `2021-10-13T11:35:29Z` |

## 3. 读取数据

### 基础读取示例

```python
import pandas as pd

# 读取数据集
dev_df = pd.read_parquet('dev-00000-of-00001.parquet')
test_df = pd.read_parquet('test-00000-of-00001.parquet')

# 查看第一个任务
task = dev_df.iloc[0]
print(f"仓库: {task['repo']}")
print(f"问题: {task['problem_statement'][:200]}...")
print(f"修复: {task['patch'][:200]}...")
```

## 4. Docker 环境配置策略

### 4.1 关键发现：环境可大量复用

**分析结果**：
- 323 个任务仅涉及 18 个不同仓库
- django 仓库包含 114 个任务（35%）
- sympy 仓库包含 77 个任务（24%）

**结论**：应该按仓库构建基础镜像，而非为每个任务构建独立镜像。

### 4.2 优化方案对比

| 策略 | 镜像数量 | 优势 | 劣势 |
|------|---------|------|------|
| **每任务一镜像** | 323 个 | 隔离性强 | 构建慢、占空间大 |
| **每仓库一镜像** ✅ | 18 个 | 复用率高、快速 | 需运行时切换 commit |

### 4.3 推荐架构

```
基础镜像层（18个）
  ├─ django-base  → 支持 114 个任务
  ├─ sympy-base   → 支持 77 个任务
  └─ ...
     ↓
运行时（git checkout）
  └─ 切换到特定 commit
```

## 5. 实际使用

### 5.1 快速开始

```bash
# 1. 查看数据集信息
python explore_swebench.py

# 2. 分析环境复用情况
python analyze_reuse.py

# 3. 构建优化的 Docker 环境
python setup_env_optimized.py
```

### 5.2 构建基础镜像

**Dockerfile.base** - 按仓库构建可复用镜像：

```dockerfile
FROM python:3.9-slim
WORKDIR /workspace
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

ARG REPO_URL
RUN git clone https://github.com/${REPO_URL}.git repo

WORKDIR /workspace/repo
RUN pip install --no-cache-dir -e . || echo "No setup.py"
CMD ["/bin/bash"]
```

**构建示例**：

```bash
# 构建 django 基础镜像（支持 114 个任务）
docker build -t swebench-base-django-django \
  --build-arg REPO_URL=django/django \
  -f Dockerfile.base .
```

### 5.3 运行特定任务

```bash
# 在基础镜像中运行任务（自动切换到正确的 commit）
docker run -it --rm swebench-base-django-django \
  bash -c "git checkout 14e1a23a3166 && bash"
```

### 5.4 自动化工具使用

```bash
# 使用 setup_env_optimized.py 自动化管理
python setup_env_optimized.py

# 选项 1: 构建所有 18 个基础镜像
# 选项 2: 构建单个仓库镜像
# 选项 3: 运行指定任务（自动使用对应镜像）
```

## 6. 典型使用场景

### 6.1 评估 AI 代码生成能力

```python
# 输入: problem_statement
# 输出: 生成的代码修复
# 评估: 与 patch 字段对比
```

### 6.2 训练代码修复模型

```python
# 训练数据对: (problem_statement, patch)
# 目标: 学习从问题描述生成代码修复
```

### 6.3 研究软件工程模式

```python
# 分析真实世界 bug 的特征
# 研究不同项目的代码修复模式
```

## 7. 最佳实践

### 7.1 环境管理

✅ **推荐做法**:
- 按仓库构建基础镜像（18 个）
- 运行时通过 `git checkout` 切换 commit
- 复用镜像以节省时间和空间

❌ **不推荐做法**:
- 为每个任务构建独立镜像（323 个）
- 重复构建相同仓库的镜像

### 7.2 测试验证

每个任务都应该验证：
1. `FAIL_TO_PASS` 中的测试修复后通过
2. `PASS_TO_PASS` 中的测试依然通过
3. 没有引入新的测试失败

### 7.3 效率优化

| 优化项 | 效果 |
|--------|------|
| 按仓库构建镜像 | 减少构建次数 94% (323→18) |
| 并行构建 18 个镜像 | 加速初始化 |
| 使用 Docker 缓存 | 加速重复构建 |

## 8. 关键文件清单

本目录包含的工具脚本：

| 文件 | 用途 |
|------|------|
| `explore_swebench.py` | 查看数据集结构和内容 |
| `analyze_reuse.py` | 分析环境复用情况 |
| `setup_env_optimized.py` | 优化的环境管理工具 |
| `Dockerfile.base` | 可复用的基础镜像模板 |
| `README_DOCKER.md` | Docker 快速使用说明 |

## 9. 核心要点总结

🎯 **关键发现**：
- 323 个任务 → 仅需 18 个 Docker 镜像
- django 和 sympy 占据 59% 的任务量
- 环境复用可节省 94% 的构建工作

⚡ **效率提升**：
- 构建时间：数小时 → 数十分钟
- 磁盘占用：数十 GB → 几 GB
- 启动速度：每次构建 → 即时启动

📝 **使用流程**：
```
读取 parquet → 分析复用 → 构建基础镜像 → 运行任务 → 验证测试
```

---

**文档创建时间**: 2026-06-05
**数据集版本**: SWE-bench lite
**优化策略**: 按仓库复用 Docker 镜像
