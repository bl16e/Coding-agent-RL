# Cost-Optimized Two-Stage Deployment Strategy

This guide keeps the expensive GPU window limited to Stage 1 local inference
while Stage 2 runs on cheaper CPU/Docker capacity with a teacher model API.

## Boundary

| Stage | Workload | Model source | Config | Script |
|-------|----------|--------------|--------|--------|
| Stage 1 | SWE-Bench Lite evaluation | local vLLM serving `Qwen2.5-Coder-7B-Instruct` | `.env.stage1` | `./scripts/run_stage1_qwen_vllm.sh` |
| Stage 2 | SWE-smith trajectory generation, eval, SFT export | teacher model API | `.env.stage2` | `./scripts/run_stage2_teacher_trajectories.sh` |

Keep these environments separate. Stage 1 should never use the teacher API key,
and Stage 2 should never point at the local Qwen vLLM endpoint.

## Recommended Topology

| Machine | Lifetime | Responsibilities |
|---------|----------|------------------|
| Bare-metal CPU server | Long running | deploy project, run Docker workloads, clone SWE-smith, run Stage 2, store artifacts |
| 4090 GPU server | Short rental windows | serve Qwen2.5-Coder-7B-Instruct through vLLM for Stage 1 |

The 4090 should not spend paid time installing packages, cloning repos, building
Docker layers, exporting SFT data, or waiting for teacher API calls.

## Bootstrap

On the bare-metal server:

```bash
./scripts/deploy.sh
docker login
```

The deploy script creates `.env.stage1.example`, `.env.stage2.example`, and
editable `.env.stage1` / `.env.stage2` files when missing.

## Stage 2 On Bare Metal

Edit `.env.stage2`:

```ini
TEACHER_MODEL=your-teacher-model
STAGE2_API_KEY=your-api-key
STAGE2_BASE_URL=https://api.openai.com/v1
```

Run:

```bash
RUN_ID=stage2_teacher \
JOBS=8 \
EVAL_WORKERS=8 \
./scripts/run_stage2_teacher_trajectories.sh
```

Lower `JOBS` and `EVAL_WORKERS` if the teacher endpoint has tight rate limits.

## Stage 1 With Short GPU Windows

Start vLLM on the 4090:

```bash
python -m vllm.entrypoints.openai.api_server \
  --model /models/Qwen2.5-Coder-7B-Instruct \
  --served-model-name Qwen/Qwen2.5-Coder-7B-Instruct \
  --host 0.0.0.0 \
  --port 8000
```

Edit `.env.stage1` on the process that orchestrates Stage 1:

```ini
STAGE1_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct
STAGE1_API_KEY=EMPTY
STAGE1_BASE_URL=http://<4090-ip>:8000/v1
```

Run a chunk:

```bash
DATASET=data/swebench_lite.parquet \
OUTPUT_DIR=runs/stage1_qwen_lite_chunk_001 \
JOBS=1 \
./scripts/run_stage1_qwen_vllm.sh
```

Use `JOBS=2` only after confirming that the vLLM server, Docker containers,
CPU, RAM, and disk IO remain stable.

## Chunking Strategy

- Smoke test: 5-10 instances.
- Normal chunk: 30-50 instances.
- Large chunk: 75-100 instances only after throughput is stable.

Sync artifacts after every chunk and stop the GPU server immediately when no
Stage 1 inference is running.

## Monitoring

On the 4090:

```bash
nvidia-smi
```

On the bare-metal host:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
docker system df
df -h
htop
```

## Cost Rule

Stage 2 usually dominates wall-clock time but does not need a local GPU. Run it
continuously on the bare-metal server. Rent the 4090 only for Stage 1 inference
chunks, then shut it down.
