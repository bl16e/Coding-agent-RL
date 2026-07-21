# Cost-Optimized Two-Stage Deployment Strategy

This document records the recommended low-cost deployment strategy for running
Stage 1 SWE-Bench Lite evaluation with a local Qwen2.5-Coder-7B-Instruct model
while running Stage 2 SWE-smith teacher-data generation with an external teacher
model API.

## Goal

Minimize expensive 4090 rental time by keeping GPU-bound inference separate from
CPU, Docker, disk, and network-heavy benchmark work.

The core rule is:

```text
Bare-metal CPU server = long-running factory
4090 GPU server       = short-lived inference accelerator
```

## Recommended Topology

Use two machine types.

| Machine | Lifetime | Main responsibilities |
|---------|----------|-----------------------|
| Bare-metal CPU server | Long running | Docker image preparation, SWE-Bench/SWE-smith containers, Stage 2 teacher API runs, official evaluation, artifact storage |
| 4090 GPU server | Short rental windows | vLLM serving for Qwen2.5-Coder-7B-Instruct, Stage 1 local-model inference |

The 4090 should not spend paid time waiting for Docker image builds, image pulls,
official evaluation, export jobs, or data cleanup.

## Work Placement

Run these on the bare-metal server:

- Project deployment and Python environment setup.
- Docker Hub login and image pulls.
- SWE-Bench Lite image build or warm-up.
- SWE-smith subset creation.
- SWE-smith Stage 2 `run-subset` with external teacher API.
- SWE-smith official `eval`.
- SFT export.
- Artifact retention and cleanup.

Run these on the 4090 server:

- vLLM OpenAI-compatible server.
- Qwen2.5-Coder-7B-Instruct inference for Stage 1.

Stage 1 can be orchestrated either directly on the 4090 or from the bare-metal
server by pointing `BASE_URL` at the 4090 vLLM endpoint. The latter usually saves
more GPU time because Docker and artifact work stay on the cheaper machine.

## Execution Plan

### 1. Prepare the bare-metal server

```bash
./scripts/deploy.sh
docker login
```

Recommended machine shape:

- CPU: 16-32 cores
- RAM: 64-128 GB
- Disk: 500 GB SSD minimum for comfortable operation
- OS: Ubuntu 22.04 LTS

### 2. Warm up Stage 1 runtime on bare metal

Use a mock backend or very small run to force runtime preparation without
consuming GPU rental time.

```bash
coding-agent swebench batch-run \
  --dataset data/dev-00000-of-00001.parquet \
  --dataset data/test-00000-of-00001.parquet \
  --backend mock \
  --max-steps 1 \
  --timeout-seconds 60 \
  --test-timeout-seconds 30 \
  --jobs 4 \
  --build-missing \
  --resume \
  --output-dir runs/stage1_prepare_smoke
```

If this performs too much mock agent work, split the preparation by smaller
dataset chunks or selected instance lists. The intent is to move image
construction and Docker failures ahead of GPU rental.

### 3. Start Stage 2 on bare metal

Stage 2 uses the external teacher API and does not need local GPU.

```bash
export PROVIDER=openai
export MODEL=<teacher-model-name>
export API_KEY=<teacher-api-key>
export BASE_URL=<teacher-openai-compatible-base-url>

RUN_ID=stage2_teacher \
JOBS=8 \
EVAL_WORKERS=8 \
CLEANUP=1 \
./scripts/run_sft_pipeline.sh
```

Start with lower parallelism if the teacher endpoint has tight rate limits:

```bash
JOBS=2 EVAL_WORKERS=4 ./scripts/run_sft_pipeline.sh
```

### 4. Rent the 4090 only for Stage 1 inference

Start vLLM on the 4090 server:

```bash
python -m vllm.entrypoints.openai.api_server \
  --model /models/Qwen2.5-Coder-7B-Instruct \
  --served-model-name qwen2.5-coder-7b \
  --host 0.0.0.0 \
  --port 8000
```

From the process that runs Stage 1:

```bash
export PROVIDER=openai
export MODEL=qwen2.5-coder-7b
export API_KEY=not-needed
export BASE_URL=http://<4090-ip>:8000/v1
```

Then run Stage 1 in small chunks or with conservative parallelism:

```bash
coding-agent swebench batch-run \
  --dataset data/dev-00000-of-00001.parquet \
  --dataset data/test-00000-of-00001.parquet \
  --backend openai-compatible \
  --max-steps 50 \
  --timeout-seconds 900 \
  --test-timeout-seconds 180 \
  --jobs 1 \
  --resume \
  --output-dir runs/stage1_qwen25_lite
```

Use `--jobs 2` only after confirming the 4090 vLLM server, Docker containers,
CPU, RAM, and disk IO remain stable.

## Chunking Strategy

For maximum savings, do not rent a 4090 for one uninterrupted full benchmark
window. Split Stage 1 into chunks, run one chunk, sync artifacts, then shut down
the GPU server.

Suggested chunk size:

- Smoke test: 5-10 instances
- Normal chunk: 30-50 instances
- Large chunk: 75-100 instances only after stable throughput is measured

Track failed or timed-out instances separately and rerun them in a later GPU
window.

## Disk Strategy

Use `CLEANUP=1` for Stage 2 unless repeatedly running the same SWE-smith repo
set and disk is cheap.

Recommended disk sizing:

| Scenario | Disk |
|----------|------|
| Aggressive cleanup, chunked runs | 250 GB can work |
| Comfortable single-server operation | 500 GB recommended |
| Preserve many Docker image caches | 1 TB recommended |

Do not preserve all SWE-Bench Lite and SWE-smith images on the 4090 server. Keep
long-lived caches on the bare-metal server.

## Runtime Expectations

Stage 1 with Qwen2.5-Coder-7B-Instruct on SWE-Bench Lite:

- Optimistic, prepared images, stable `jobs=2`: about 13-27 hours of run time.
- Realistic including retries and Docker overhead: about 1-3 days.

Stage 2 with SWE-smith teacher API:

- `10,000` instances at `10` minutes each with `JOBS=8`: about 208 hours, or 9
  days.
- With stronger API concurrency and stable `JOBS=16`: about 4-5 days.
- With `JOBS=4`: closer to 17-18 days.

Because Stage 2 is usually longer, total wall-clock time is dominated by Stage
2. Running Stage 1 during Stage 2 does not materially extend total time if the
bare-metal server has enough CPU, RAM, disk, and network headroom.

## Monitoring

On the 4090 server:

```bash
nvidia-smi
```

On the bare-metal server:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
docker system df
df -h
htop
```

Check artifacts:

```bash
find runs/ -name "summary.json" | wc -l
find logs/run_evaluation/ -name "report.json" | wc -l
```

## Cost Rules

- Start the 4090 only after Stage 1 Docker runtime preparation has been tested.
- Stop the 4090 immediately after each Stage 1 chunk finishes.
- Keep Stage 2 on bare metal because teacher API calls do not need local GPU.
- Keep official evaluation on bare metal.
- Keep long-lived Docker caches and artifacts on bare metal.
- Do not let high Docker parallelism starve vLLM or the benchmark containers.
- Use separate environment variables per shell so Stage 1 local vLLM and Stage 2
  teacher API do not accidentally share model configuration.

## Recommended Default Parameters

Bare-metal Stage 2:

```bash
JOBS=4
EVAL_WORKERS=4
CLEANUP=1
MAX_STEPS=80
TIMEOUT_SEC=1200
```

4090-backed Stage 1:

```bash
--jobs 1
--max-steps 50
--timeout-seconds 900
--test-timeout-seconds 180
```

After one successful smoke run, increase only one parameter at a time.

## Final Recommendation

Rent the bare-metal server for the full workflow window. Rent the 4090 only in
short inference windows for Stage 1 chunks. This converts the 4090 from a
long-running benchmark host into a burst inference endpoint, which is the main
cost-saving lever.
