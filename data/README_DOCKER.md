# SWE-bench Docker 环境配置

## 快速开始

### 1. 构建特定任务的环境

```bash
python setup_env.py
```

选择任务编号，自动构建对应的 Docker 镜像。

### 2. 手动构建示例

```bash
# 为第一个任务构建环境
docker build -t swebench-task1 \
  -f Dockerfile.template \
  --build-arg REPO_URL=sqlfluff/sqlfluff \
  --build-arg BASE_COMMIT=14e1a23a3166b9a645a16de96f694c77a5d4abb7 \
  .
```

### 3. 运行容器

```bash
docker run -it --rm swebench-task1
```

## 工作流程

```
读取 parquet → 选择任务 → 构建 Docker → 运行测试 → 验证修复
```
