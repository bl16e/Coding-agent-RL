# SWE-smith Windows 兼容补丁记录

本文记录为让 SWE-smith 官方 eval 在 Windows host 上跑通而加入的兼容补丁。目标是让后续在 Unix/Linux 上运行时知道哪些逻辑是 Windows-only，可以恢复、移除或避免启用。

## 补丁范围

相关代码：

```text
src/coding_agent/swesmith/compat.py
src/coding_agent/swesmith/evaluate.py
src/coding_agent/swesmith/runtime.py
tests/unit/test_swesmith_compat.py
tests/unit/test_swesmith_evaluate.py
```

相关提交：

```text
cd5e63a fix: align SWE-smith eval wrapper with official CLI
adfd725 fix: support official SWE-smith eval on Windows
```

这些补丁只应影响 Windows：

- `runtime.import_swesmith()` 调用 `install_windows_resource_shim()`，函数内部检查 `os.name != "nt"` 时直接返回。
- `evaluate.run_official_eval()` 只有在 `os.name == "nt"` 时走 `python -c <prelude>`；非 Windows 仍使用：

```bash
python -m swesmith.harness.eval ...
```

## 补丁 1：移除 eval wrapper 中不存在的 `--timeout`

### 症状

真实 Reference 的 `swesmith.harness.eval` 参数为：

```text
--dataset_path
--predictions_path
--run_id
--workers
--redo_existing
--instance_ids
--f2p_only
--report_only
```

没有 `--timeout`。早期实现按设计草案传了 `--timeout`，真实入口不接受。

### 修复

`coding-agent swesmith eval` 不再暴露或传递 `--timeout`。官方评测使用 SWE-smith profile 自带 timeout，例如 pandas 样例 profile timeout 为 `90`。

### Unix 恢复说明

这不是 Windows-only 补丁，而是与当前 Reference SWE-smith 官方 CLI 对齐的修复。不要在 Unix 上恢复 `--timeout`，除非上游 SWE-smith CLI 新增该参数并已验证。

## 补丁 2：Windows 缺少 Unix `resource` 模块

### 症状

在 Windows 上导入 SWE-bench/SWE-smith 官方 harness 时报：

```text
ModuleNotFoundError: No module named 'resource'
```

原因是 SWE-bench eager import 了使用 Unix-only stdlib `resource` 的模块。

### 修复

`src/coding_agent/swesmith/compat.py`：

```python
def install_windows_resource_shim() -> None:
    if os.name != "nt" or "resource" in sys.modules:
        return
    module = types.ModuleType("resource")
    module.RLIMIT_NOFILE = 0
    module.setrlimit = lambda *args, **kwargs: None
    sys.modules["resource"] = module
```

官方 eval 子进程也通过 `windows_resource_shim_prelude()` 注入同样 shim。

### Unix 恢复说明

Unix/Linux 上存在真实 `resource` 模块，不需要 shim。当前代码在 `os.name != "nt"` 时不会安装 shim。若在纯 Unix 部署中希望完全移除 Windows 支持，可删除：

- `install_windows_resource_shim`
- `windows_resource_shim_prelude`
- `runtime.py` 中对 `install_windows_resource_shim()` 的调用
- Windows 分支相关测试

删除后必须确认 Unix 上仍可：

```bash
python -m swesmith.harness.eval --help
```

## 补丁 3：官方 `copy_to_container` 在 Windows 上把容器路径变成反斜杠

### 症状

官方 eval 在 Windows host 上失败：

```text
ValueError: No escaped character
```

堆栈来自：

```text
SWE-bench/swebench/harness/docker_utils.py::copy_to_container
container.exec_run(f"mkdir -p {dst.parent}")
```

调用方传入：

```python
Path("/eval.sh")
```

在 Windows host 上，`Path("/eval.sh").parent` 变成 `\`。Docker SDK 对字符串命令执行 `shlex.split("mkdir -p \\")`，于是报 `No escaped character`。

### 修复

`windows_official_eval_prelude()` 在 Windows eval 子进程中 monkeypatch：

```python
import swebench.harness.docker_utils as _ca_du
_ca_du.copy_to_container = _ca_copy_to_container
import swesmith.harness.utils as _ca_su
_ca_su.copy_to_container = _ca_copy_to_container
```

替代函数把容器目标路径按 POSIX 处理：

```python
dst_text = str(dst).replace("\\", "/")
parent = posixpath.dirname(dst_text)
name = posixpath.basename(dst_text)
container.exec_run(["mkdir", "-p", parent])
container.put_archive(parent, data)
```

关键点：

- 不改 `Reference/SWE-smith` 或 `SWE-bench` checkout。
- 只在 Windows eval 子进程中 monkeypatch。
- 使用 exec-list 形式调用 `mkdir`，避免 Docker SDK 对字符串做 shell-like split。

### Unix 恢复说明

Unix/Linux 上 `Path("/eval.sh").parent` 为 `/`，官方代码不会触发这个问题。当前 monkeypatch 只在 `os.name == "nt"` 分支启用。若在 Unix 上跑，不需要恢复；它本来不会执行。

如果要彻底去掉 Windows monkeypatch，可把 `evaluate.py` 中 Windows 分支改回只注入 `resource` shim 或完全删除 Windows 分支：

```python
command = [sys.executable, "-m", "swesmith.harness.eval", *eval_args]
```

但这样 Windows host 上官方 eval 会重新失败。

## 补丁 4：Windows 写出的 `eval.sh` CRLF 导致容器 bash 解析错误

### 症状

路径问题修好后，官方 eval 能把 `eval.sh` copy 到容器，但容器内 bash 读到 CRLF：

```text
/eval.sh: line 2: set: pipefail: invalid option name
+ cd $'/testbed\r'
/eval.sh: line 3: cd: $'/testbed\r': No such file or directory
pytest ... $'pandas/tests/indexing/test_datetime.py\r'
ERROR: file or directory not found
```

原因是官方代码：

```python
eval_file.write_text(...)
```

在 Windows 默认写入 CRLF。这个脚本随后被复制到 Linux 容器执行。

### 修复

同一个 Windows `copy_to_container` monkeypatch 在复制 `.sh` 文件时归一化换行：

```python
if name.endswith(".sh"):
    payload = src.read_text().replace("\r\n", "\n").replace("\r", "\n").encode()
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    tar.addfile(info, io.BytesIO(payload))
else:
    tar.add(src, arcname=name)
```

修复后真实 eval 输出：

```text
+ cd /testbed
collecting ... collected 22 items
...
18 passed
4 failed
```

对于空 patch，官方 report 正确判定：

```json
{
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
  }
}
```

### Unix 恢复说明

Unix/Linux host 的 `Path.write_text()` 默认写 LF，不需要这个归一化。当前逻辑只在 Windows eval 子进程中执行。Unix 上不受影响。

## 补丁 5：Docker Desktop web login 与官方 `download_images.py`

### 症状

即使 `docker login` 成功，官方脚本仍可能报：

```text
Docker Hub credentials not found. Please log in using 'docker login'.
```

原因是官方脚本只支持：

```json
{
  "auths": {
    "https://index.docker.io/v1/": {
      "auth": "base64(username:password)"
    }
  }
}
```

而 Docker Desktop web-based login 使用：

```json
{
  "credsStore": "desktop",
  "auths": {
    "https://index.docker.io/v1/": {},
    "https://index.docker.io/v1/access-token": {},
    "https://index.docker.io/v1/refresh-token": {}
  }
}
```

### 本次临时处理

未修改项目代码。只在命令行临时用 Docker Desktop credential helper 读取 secret，并替换官方函数：

```powershell
$env:PYTHONPATH='D:\code\coding_agent\Reference\SWE-smith;D:\code\coding_agent\SWE-bench;D:\code\coding_agent\src'
python -c "import json, subprocess; import swesmith.build_repo.download_images as d; helper=r'C:\Program Files\Docker\Docker\resources\bin\docker-credential-desktop.exe'; p=subprocess.run([helper,'get'], input='https://index.docker.io/v1/', text=True, capture_output=True, check=True); creds=json.loads(p.stdout); d.get_docker_hub_login=lambda: (creds['Username'], creds['Secret']); d.main(repo='pandas-dev__pandas.95280573', proceed=True)"
```

该命令没有把 secret 写入仓库，也没有提交任何凭据。

### Unix 恢复说明

这是操作层 workaround，不是代码补丁。Unix 上如果官方脚本能读到 `~/.docker/config.json` 的 `auth`，直接使用：

```bash
python -m swesmith.build_repo.download_images --repo <repo> -y
```

如果 Unix 上也使用 credential helper，建议优先：

```bash
docker login -u <username>
```

让 Docker config 生成官方脚本能读取的旧式 auth；或者在上游 SWE-smith 中正式支持 Docker credential helpers。

## Unix 上建议的最小运行路径

在 Linux/WSL/CI 上，理想情况下不需要任何 Windows shim，命令应是：

```bash
export PYTHONPATH="$PWD/Reference/SWE-smith:$PWD/SWE-bench:$PWD/src"
python -m swesmith.build_repo.download_images --repo pandas-dev__pandas.95280573 -y

export PYTHONPATH="$PWD/SWE-bench:$PWD/src"
python -m coding_agent.cli swesmith run-subset \
  --subset .tmp/swesmith_real_smoke/subset.json \
  --output-dir .tmp/swesmith_real_smoke/runs \
  --max-steps 1 \
  --timeout-seconds 60 \
  --test-timeout-seconds 10 \
  --backend mock \
  --reference-path Reference/SWE-smith

python -m coding_agent.cli swesmith eval \
  --subset .tmp/swesmith_real_smoke/subset.json \
  --predictions .tmp/swesmith_real_smoke/runs/preds.jsonl \
  --run-id <run_id> \
  --workers 1 \
  --reference-path Reference/SWE-smith
```

如果要验证 Windows shim 没有在 Unix 上生效，可在 Unix 上检查 `run_official_eval()` 构造的命令是否仍为：

```text
python -m swesmith.harness.eval ...
```

而不是：

```text
python -c <windows prelude> ...
```

## 回归验证命令

修改或移除这些补丁后，至少运行：

```bash
python -m pytest tests/unit/test_swesmith_evaluate.py tests/unit/test_swesmith_compat.py -q
python -m pytest -q
```

真实 smoke 建议复跑：

```bash
python -m coding_agent.cli swesmith eval \
  --subset .tmp/swesmith_real_smoke/subset.json \
  --predictions .tmp/swesmith_real_smoke/sample_patch_preds.jsonl \
  --run-id smoke-sample-patch \
  --workers 1 \
  --reference-path Reference/SWE-smith
```

期望：

```text
Resolved 1/1 instances.
```
