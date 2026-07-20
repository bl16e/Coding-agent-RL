# SWE-smith 当前 Agent 真实 E2E 数据生成流程

本文记录 2026-07-20 在 `feat_introduce_swesmith_workflow` 分支上跑通的真实 SWE-smith E2E workflow。目标是让后续 session 或其他开发者能快速复现：使用当前 `coding-agent` 跑 SWE-smith 任务，使用 SWE-smith 官方评测判定 resolved，只导出 resolved 轨迹用于 SFT。

## 已验证结论

本次真实 smoke 任务：

```text
instance_id: pandas-dev__pandas.95280573.pr_53652
image: swebench/swesmith.x86_64.pandas-dev_1776_pandas.95280573:latest
subset: .tmp/swesmith_real_smoke/subset.json
```

已验证：

- SWE-smith 官方镜像已通过官方 `download_images` 路径下载到本地。
- `coding-agent swesmith run-subset` 能在真实 SWE-smith 容器里生成 artifacts。
- `coding-agent swesmith eval` 能调用 SWE-smith 官方 eval，并在真实容器里运行 pytest。
- 当前 mock backend 生成空 patch，官方 eval 判定 `resolved 0/1`。
- `coding-agent swesmith export-sft` 对 unresolved eval 结果导出 `count: 0`。
- 用同一个样例的已知 patch 作为 prediction，官方 eval 判定 `resolved 1/1`，证明环境和评测链路有效。

## 前置条件

在 Windows 上本次使用：

```powershell
$env:PYTHONPATH='D:\code\coding_agent\SWE-bench;D:\code\coding_agent\src'
```

调用 SWE-smith 官方模块时使用：

```powershell
$env:PYTHONPATH='D:\code\coding_agent\Reference\SWE-smith;D:\code\coding_agent\SWE-bench;D:\code\coding_agent\src'
```

依赖：

- Docker Desktop 可用，daemon 可创建 Linux x86_64 容器。
- 已安装 Python 依赖：`datasets`, `docker`, `ghapi`, `GitPython`, `chardet`, `modal` 等 SWE-smith/SWE-bench 所需包。
- 已完成 Docker Hub 登录。
- 本地有 `Reference/SWE-smith` 和 `SWE-bench` checkout。

如果使用代理，可先在当前 PowerShell 设置：

```powershell
$env:HTTP_PROXY="http://127.0.0.1:7897"
$env:HTTPS_PROXY="http://127.0.0.1:7897"
```

注意：Docker 镜像下载最终由 Docker Desktop daemon 执行。PowerShell 环境变量不一定会影响 daemon；必要时需要在 Docker Desktop proxy 设置里配置同一个代理。

## 1. Docker 登录

推荐先在命令行登录：

```powershell
docker login
```

Web-based login 成功后，确认 Docker config 中出现 Docker Hub key：

```powershell
$path = Join-Path $env:USERPROFILE '.docker\config.json'
$cfg = Get-Content -Raw $path | ConvertFrom-Json
$cfg.auths.PSObject.Properties.Name
```

本次登录后看到：

```text
https://index.docker.io/v1/
https://index.docker.io/v1/access-token
https://index.docker.io/v1/refresh-token
```

## 2. 按 SWE-smith 官方方式下载镜像

官方推荐方式是：

```bash
python -m swesmith.build_repo.download_images
```

为避免下载全部已发布环境，本次限定到一个 repo：

```powershell
$env:PYTHONPATH='D:\code\coding_agent\Reference\SWE-smith;D:\code\coding_agent\SWE-bench;D:\code\coding_agent\src'
python -m swesmith.build_repo.download_images --repo pandas-dev__pandas.95280573 -y
```

如果官方脚本报：

```text
Docker Hub credentials not found. Please log in using 'docker login'.
```

原因可能是 Docker Desktop web login 使用 credential store，而 `Reference/SWE-smith/swesmith/build_repo/download_images.py` 只读取 `~/.docker/config.json` 里的旧式 `auth` 字段。可用下面的临时 shim 从 Docker Desktop credential helper 取凭据，并仍调用官方 `download_images.main()`：

```powershell
$env:PYTHONPATH='D:\code\coding_agent\Reference\SWE-smith;D:\code\coding_agent\SWE-bench;D:\code\coding_agent\src'
python -c "import json, subprocess; import swesmith.build_repo.download_images as d; helper=r'C:\Program Files\Docker\Docker\resources\bin\docker-credential-desktop.exe'; p=subprocess.run([helper,'get'], input='https://index.docker.io/v1/', text=True, capture_output=True, check=True); creds=json.loads(p.stdout); d.get_docker_hub_login=lambda: (creds['Username'], creds['Secret']); d.main(repo='pandas-dev__pandas.95280573', proceed=True)"
```

本次成功输出：

```text
Found 1 environments:
- swesmith.x86_64.pandas-dev_1776_pandas.95280573
Downloading swesmith.x86_64.pandas-dev_1776_pandas.95280573...
```

确认镜像：

```powershell
docker images swebench/swesmith.x86_64.pandas-dev_1776_pandas.95280573
```

本次确认到：

```text
swebench/swesmith.x86_64.pandas-dev_1776_pandas.95280573:latest
DISK USAGE: 8.61GB
CONTENT SIZE: 2.66GB
```

## 3. 准备一个真实 SWE-smith subset

本次使用 Reference 中自带的真实样例：

```text
Reference/SWE-smith/tests/test_logs/pandas-dev__pandas.95280573.pr_53652.json
```

生成单实例 subset 和一个空 patch prediction 可用：

```powershell
New-Item -ItemType Directory -Force .tmp\swesmith_real_smoke | Out-Null
python -c "import json, pathlib; sample=json.loads(pathlib.Path('Reference/SWE-smith/tests/test_logs/pandas-dev__pandas.95280573.pr_53652.json').read_text(encoding='utf-8')); pathlib.Path('.tmp/swesmith_real_smoke/subset.json').write_text(json.dumps([sample], indent=2), encoding='utf-8'); pred={'instance_id': sample['instance_id'], 'model_name_or_path':'coding-agent-smoke', 'model_patch':''}; pathlib.Path('.tmp/swesmith_real_smoke/preds.jsonl').write_text(json.dumps(pred)+'\n', encoding='utf-8')"
```

## 4. 使用当前 agent 跑 SWE-smith 任务

用当前 `coding-agent`，不是 SWE-agent：

```powershell
$env:PYTHONPATH='D:\code\coding_agent\SWE-bench;D:\code\coding_agent\src'
python -m coding_agent.cli swesmith run-subset `
  --subset .tmp\swesmith_real_smoke\subset.json `
  --output-dir .tmp\swesmith_real_smoke\runs_real_after_download `
  --max-steps 1 `
  --timeout-seconds 60 `
  --test-timeout-seconds 10 `
  --backend mock `
  --reference-path Reference\SWE-smith
```

本次命令退出码为 `0`，生成：

```text
.tmp/swesmith_real_smoke/runs_real_after_download/
|-- batch_summary.json
|-- preds.jsonl
`-- pandas-dev__pandas.95280573.pr_53652/
    |-- final.patch
    |-- prediction.jsonl
    |-- sandbox.json
    |-- summary.json
    |-- trajectory.json
    `-- trajectory.jsonl
```

本次 `batch_summary.json` 中状态为：

```json
{
  "status": "incomplete",
  "error": "Mock backend exhausted"
}
```

这是预期行为：mock backend 只用于验证真实 runtime/artifact 流程，不会修复任务。

## 5. 使用 SWE-smith 官方 eval 评估当前 agent prediction

```powershell
$env:PYTHONPATH='D:\code\coding_agent\SWE-bench;D:\code\coding_agent\src'
python -m coding_agent.cli swesmith eval `
  --subset .tmp\swesmith_real_smoke\subset.json `
  --predictions .tmp\swesmith_real_smoke\runs_real_after_download\preds.jsonl `
  --run-id coding-agent-smoke-after-lffix `
  --workers 1 `
  --reference-path Reference\SWE-smith
```

本次输出：

```text
All instances run.
Resolved 0/1 instances.
Wrote report to logs\run_evaluation\coding-agent-smoke-after-lffix\report.json
```

关键报告：

```text
logs/run_evaluation/coding-agent-smoke-after-lffix/report.json
logs/run_evaluation/coding-agent-smoke-after-lffix/pandas-dev__pandas.95280573.pr_53652/report.json
logs/run_evaluation/coding-agent-smoke-after-lffix/pandas-dev__pandas.95280573.pr_53652/test_output.txt
```

本次 per-instance report：

```json
{
  "patch_exists": true,
  "resolved": false,
  "tests_status": {
    "FAIL_TO_PASS": {
      "success": [],
      "failure": [
        "pandas/tests/indexing/test_datetime.py::TestDatetimeIndex::test_getitem_pyarrow_index[DataFrame]",
        "pandas/tests/indexing/test_datetime.py::TestDatetimeIndex::test_getitem_pyarrow_index[Series]"
      ]
    },
    "PASS_TO_PASS": {
      "failure": []
    }
  },
  "model_name_or_path": "mock-model"
}
```

`test_output.txt` 证明官方 eval 在真实容器里跑了 pytest：

```text
collecting ... collected 22 items
...
18 passed
4 failed
```

失败项正是 `FAIL_TO_PASS`，符合空 patch 预期。

## 6. 只导出 resolved 轨迹做 SFT

```powershell
python -m coding_agent.cli swesmith export-sft `
  --runs .tmp\swesmith_real_smoke\runs_real_after_download `
  --eval-dir logs\run_evaluation\coding-agent-smoke-after-lffix `
  --out .tmp\swesmith_real_smoke\sft_after_lffix.jsonl
```

本次输出：

```json
{
  "output": ".tmp\\swesmith_real_smoke\\sft_after_lffix.jsonl",
  "count": 0
}
```

这验证了核心约束：unresolved trajectory 不进入 SFT 数据。

## 7. 用样例 patch 验证任务可 resolved

为了确认环境和评测不是假阴性，用 Reference 样例中的 patch 构造 prediction：

```powershell
python -c "import json, pathlib; sample=json.loads(pathlib.Path('Reference/SWE-smith/tests/test_logs/pandas-dev__pandas.95280573.pr_53652.json').read_text(encoding='utf-8')); pred={'instance_id': sample['instance_id'], 'model_name_or_path':'sample-patch', 'model_patch': sample['patch']}; pathlib.Path('.tmp/swesmith_real_smoke/sample_patch_preds.jsonl').write_text(json.dumps(pred)+'\n', encoding='utf-8')"
```

跑官方 eval：

```powershell
$env:PYTHONPATH='D:\code\coding_agent\SWE-bench;D:\code\coding_agent\src'
python -m coding_agent.cli swesmith eval `
  --subset .tmp\swesmith_real_smoke\subset.json `
  --predictions .tmp\swesmith_real_smoke\sample_patch_preds.jsonl `
  --run-id coding-agent-smoke-sample-patch `
  --workers 1 `
  --reference-path Reference\SWE-smith
```

本次输出：

```text
All instances run.
Resolved 1/1 instances.
Wrote report to logs\run_evaluation\coding-agent-smoke-sample-patch\report.json
```

batch report：

```json
{
  "resolved": 1,
  "unresolved": 0,
  "total": 1,
  "ids_resolved": [
    "pandas-dev__pandas.95280573.pr_53652"
  ],
  "ids_unresolved": []
}
```

per-instance report 中 `FAIL_TO_PASS` 和 `PASS_TO_PASS` 全部 success。

## 注意事项

- 不要手动假设所有 SWE-smith 镜像都已发布到 Docker Hub。先用官方 `download_images` 枚举和下载当前已发布镜像。
- `docker manifest inspect` 能看到 manifest，不代表 Docker daemon 的 `pull` 路径一定可用；本次在登录前曾出现 manifest 可见但 pull 返回 `not found`。
- PowerShell `Set-Content -Encoding UTF8` 可能写出 BOM 或 JSON 形态不符合预期。生成 subset/prediction 建议用 Python `json` 标准库。
- Windows host 下官方 SWE-bench/SWE-smith eval 有额外兼容问题，本项目 wrapper 已加 Windows-only shim。详见 `2026-07-20-swesmith-windows-compat-patches-zh.md`。
- 真实运行产物 `logs/` 和 `.tmp/` 不应提交。
