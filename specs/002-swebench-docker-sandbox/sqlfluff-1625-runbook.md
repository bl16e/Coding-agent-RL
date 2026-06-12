# SQLFluff 1625 SWE-bench Docker Runbook

记录时间：2026-06-12

本文记录本地 Docker 环境中跑通 `sqlfluff__sqlfluff-1625` 的完整流程、验证证据和踩坑经验。这里的“跑通”不是只执行一个 pytest，而是要求 agent 产生可评估补丁，`trajectory.json` 中 `final_diff` 非空，`final.patch` 可应用，并且能验证 issue 症状被修复。

## 任务信息

- Dataset: `data/dev-00000-of-00001.parquet`
- Instance: `sqlfluff__sqlfluff-1625`
- Repo: `sqlfluff/sqlfluff`
- Base commit: `14e1a23a3166b9a645a16de96f694c77a5d4abb7`
- Issue: TSQL 下单表查询 `SELECT a.[hello] FROM mytable AS a` 没有 JOIN，却错误触发 L031 `Avoid using aliases in join condition`
- FAIL_TO_PASS: `test/cli/commands_test.py::test__cli__command_directed`
- Validation command: `python -m pytest test/cli/commands_test.py::test__cli__command_directed`

## 最终有效产物

最终有效 run 目录：

```text
runs/sqlfluff__sqlfluff-1625-scripted-l031-fix-v4
```

关键证据：

- `summary.json`
  - `status`: `solved`
  - `changed_files`: `["src/sqlfluff/rules/L031.py"]`
  - `test_summary`: `{"passed": 1}`
- `trajectory.json`
  - `resolved`: `true`
  - `final_diff`: 非空，包含 `src/sqlfluff/rules/L031.py` 的补丁
- `final.patch`
  - LF line endings，`CR 0`
  - 可被 `git apply`
- 独立验证：把 `final.patch` 应用到一次性容器后，直接 lint issue SQL，L031 violations 为 `[]`

## 环境和镜像

本机已有基础镜像：

```powershell
docker images
```

相关镜像：

```text
swebench-base-sqlfluff-sqlfluff:latest
swebench-base-sqlfluff-sqlfluff-testdeps:latest
```

原始 `swebench-base-sqlfluff-sqlfluff:latest` 只能作为仓库基础镜像，不能直接稳定运行该旧 commit 的测试。原因包括：

- 缺少 `pytest`
- base commit 的测试导入 `oyaml`
- SQLFluff 0.7.0a8 依赖 `pkg_resources`，需要 `setuptools<81`
- 当前镜像里的 Click 过新，旧测试使用 `CliRunner(mix_stderr=...)`，需要 `click<8.2`
- checkout 到旧 commit 后，必须重新 `pip install -e /workspace/repo`，否则 entry point metadata 可能仍指向新版本模块

因此新增了派生镜像定义：

```text
data/Dockerfile.sqlfluff-testdeps
```

构建命令：

```powershell
docker build `
  -t swebench-base-sqlfluff-sqlfluff-testdeps:latest `
  -f data/Dockerfile.sqlfluff-testdeps `
  data
```

该 Dockerfile 基于现有 SQLFluff 基础镜像，安装最小测试依赖，并在镜像内 checkout 到 `14e1a23a3166b9a645a16de96f694c77a5d4abb7` 后执行 editable install。

## Sandbox 注册

注册表路径：

```text
.coding-agent/sandboxes.json
```

注册命令：

```powershell
python -c "import sys; sys.path.insert(0,'src'); from coding_agent.cli import main; raise SystemExit(main(['sandbox','register','--repo','sqlfluff/sqlfluff','--image','swebench-base-sqlfluff-sqlfluff-testdeps:latest','--repo-path','/workspace/repo','--registry','.coding-agent/sandboxes.json','--official-compatible','--compatibility-source','local derived image from existing SWE-bench SQLFluff base with pytest/click/setuptools task dependencies','--validation-command-template','python -m pytest {tests}']))"
```

检查注册表：

```powershell
python -c "import sys; sys.path.insert(0,'src'); from coding_agent.cli import main; raise SystemExit(main(['sandbox','list','--registry','.coding-agent/sandboxes.json']))"
```

预期 `sqlfluff/sqlfluff` 指向：

```text
swebench-base-sqlfluff-sqlfluff-testdeps:latest
```

## 成功 run 的 agent 动作链

最终 run 使用 scripted mock backend，是为了在当前环境中可重复验证 sandbox、工具、patch 导出和 SWE-bench 产物格式。动作链如下：

1. `read_file`
   - 读取 `src/sqlfluff/rules/L031.py`
2. `apply_patch`
   - 把 `_eval()` 中调用 `_lint_aliases_in_join()` 的位置增加 `kwargs["dialect"]`
3. `apply_patch`
   - 把 `_lint_aliases_in_join()` 签名增加 `dialect`
4. `apply_patch`
   - 在生成 L031 violation 前增加 TSQL-only guard：

```python
if (
    dialect.name == "tsql"
    and not list(segment.recursive_crawl("join_clause"))
    and ids_refs
):
    continue
```

5. `run_tests`
   - 执行 `python -m pytest test/cli/commands_test.py::test__cli__command_directed`
6. `final`
   - 返回 `solved`

为什么 guard 必须限定 `dialect.name == "tsql"`：

- 初版条件是 “no JOIN 且 alias 被列引用使用就跳过”
- 这会破坏现有 ANSI 行为：`test/fixtures/linter/indentation_error_simple.sql` 中 `FROM tbl as a` 仍应报告 L031
- issue 明确是 TSQL 方言，所以修复应限定在 TSQL 的无 JOIN、alias-qualified 列引用场景

## 最终验证命令

### 1. 验证 run summary

```powershell
Get-Content -Raw runs\sqlfluff__sqlfluff-1625-scripted-l031-fix-v4\summary.json
```

必须看到：

```json
"status": "solved",
"changed_files": ["src/sqlfluff/rules/L031.py"],
"test_summary": {"passed": 1}
```

### 2. 验证 trajectory

```powershell
Get-Content -Raw runs\sqlfluff__sqlfluff-1625-scripted-l031-fix-v4\trajectory.json
```

必须检查：

- `steps` 中有 `read_file`、多次 `apply_patch`、`run_tests`
- `run_tests` observation 为 `passed`
- `final_diff` 非空
- `resolved` 为 `true`

注意：只看到测试 passed 不够。必须同时看到 `final_diff` 非空，否则只是测试执行成功，不代表 agent 修了问题。

### 3. 验证 patch line ending

```powershell
python -c "from pathlib import Path; b=Path('runs/sqlfluff__sqlfluff-1625-scripted-l031-fix-v4/final.patch').read_bytes(); print('CR', b.count(b'\r'), 'LF', b.count(b'\n'))"
```

预期：

```text
CR 0
```

Windows 上不能用普通 `Path.write_text()` 写 Docker 导出的 patch，否则可能把 LF 改成 CRLF，导致 `git apply` 失败。

### 4. 独立验证 patch 可应用且 issue 被修复

```powershell
$script = @'
import subprocess
from pathlib import Path

image = 'swebench-base-sqlfluff-sqlfluff-testdeps:latest'
patch_path = Path('runs/sqlfluff__sqlfluff-1625-scripted-l031-fix-v4/final.patch').resolve()
container = 'coding-agent-verify-sqlfluff-1625-l031'
subprocess.run(['docker', 'rm', '-f', container], capture_output=True, text=True)
try:
    subprocess.run(['docker', 'create', '--name', container, image, 'sleep', 'infinity'], check=True, text=True, capture_output=True)
    subprocess.run(['docker', 'start', container], check=True, text=True, capture_output=True)
    subprocess.run(['docker', 'cp', str(patch_path), f'{container}:/tmp/final.patch'], check=True, text=True, capture_output=True)
    subprocess.run(['docker', 'exec', container, 'git', '-C', '/workspace/repo', 'apply', '/tmp/final.patch'], check=True, text=True, capture_output=True)
    code = """
from sqlfluff.core import Linter
sql = 'SELECT a.[hello]\\nFROM\\n    mytable AS a'
violations = Linter(dialect='tsql', rules=['L031']).lint_string(sql).get_violations()
print([v.rule_code() for v in violations])
assert not [v for v in violations if v.rule_code() == 'L031']
"""
    result = subprocess.run(['docker', 'exec', container, 'python', '-c', code], check=True, text=True, capture_output=True)
    print(result.stdout.strip())
finally:
    subprocess.run(['docker', 'rm', '-f', container], capture_output=True, text=True)
'@
$script | python -
```

预期输出：

```text
[]
```

## 本项目中修复的关键基础问题

这次真实跑通前，先修了两个 agent/sandbox 基础问题。

### 1. Docker sandbox 没有导出容器内 patch

问题：

- Docker 模式下，agent 实际修改发生在容器内
- 原实现的 `final.patch` 基于宿主机 `_workspace_snapshot`
- 结果是 `trajectory.json` 里 `final_diff` 为空，即使容器内文件被改了也不能提交到 SWE-bench

修复：

- 在 `run_swebench_task()` 成功路径中，容器停止前执行：

```text
git -C /workspace/repo diff --binary HEAD
```

- 用容器 diff 覆盖：
  - `final.patch`
  - `prediction.jsonl`
  - `trajectory.json` 的 `final_diff`
  - `summary.json` 的 `changed_files`

回归测试：

```text
tests/integration/test_swebench_sandbox_run.py::test_sandboxed_run_exports_container_patch_to_artifacts
```

### 2. ContainerToolExecutor.apply_patch(update) 的脚本是非法 Python

问题：

- update 分支把 `if count==0: ...` 放在分号链后
- Python 不允许 compound statement 出现在这种位置
- 容器中报 `SyntaxError`
- agent 后续还可能继续跑测试并错误地 final solved

修复：

- 把内联 Python 改成多行合法脚本
- 通过 argv 传 `old_string/new_string`，不要做 shell 风格 quote 转义

回归测试：

```text
tests/unit/test_container_tools.py::test_container_executor_update_script_is_valid_python
```

## 测试命令

本地 pytest 环境存在第三方插件自动加载导致卡住的问题。验证本项目测试时使用：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests\unit\test_container_tools.py tests\integration\test_swebench_sandbox_run.py tests\unit\test_prediction.py tests\integration\test_run_artifact_consistency.py -q
```

已验证结果：

```text
14 passed in 0.24s
```

语法检查：

```powershell
python -m py_compile src\coding_agent\sandbox\tools.py src\coding_agent\swebench\sandbox_run.py
```

容器清理检查：

```powershell
docker ps --filter name=coding-agent --format "table {{.Names}}\t{{.Status}}"
```

预期无残留任务容器。

## 经验原则

1. 不要把“测试命令能跑”当成“agent 解决了问题”
   - 必须检查 `final.patch`、`trajectory.json.final_diff`、`prediction.jsonl.model_patch`

2. Docker sandbox 的补丁来源必须是容器内 `git diff`
   - 宿主机占位 workspace 不能证明容器内修改

3. `FAIL_TO_PASS` passing 不是充分条件
   - 还要独立验证 issue 症状，尤其是本地 validation template 不一定等价于官方 harness

4. Windows 写 patch 要避免文本换行转换
   - patch 应用失败时先检查 CRLF
   - 写 patch 文件优先用 `write_bytes(patch.encode("utf-8"))`

5. 镜像要与任务 base commit 的 Python 包状态对齐
   - checkout 后需要重新 editable install
   - 否则 entry point metadata 可能指向旧/新版本不一致的模块

6. scripted mock backend 可用于验证 agent 基础设施
   - 但必须让 scripted actions 包含真实 `read_file/apply_patch/run_tests/final`
   - 只 scripted `run_tests` 不是解题 run

7. 工具失败不能被 final solved 掩盖
   - 看 `trajectory.jsonl`，确认每个关键 `apply_patch` outcome 是 `ok`
   - 看 `summary.last_successful_tool_call` 是否合理

## 后续建议

- CLI 层增加一个 `--scripted-actions` 或 fixture runner，便于重放这种可审计 agent run
- `run_task()` 可以在 `run_tests` 失败后阻止 mock/scripted agent 返回 `solved`，至少在测试模式中加断言
- Docker sandbox 运行完成后默认校验 `final.patch` 可被 `git apply --check`
- 对真实 SWE-bench 评估，优先集成官方 harness 生成的 eval script，而不是长期依赖 fallback template

## 2026-06-12 同题重复稳定性验证记录

这部分记录的是同一个 `sqlfluff__sqlfluff-1625` 问题的重复稳定性验证，不是三个不同
SWE-bench 问题。它只能证明同一问题、同一修复动作链在当前 sandbox 中可重复，不能证明
runner 能覆盖多个不同问题。

输出根目录：

```text
runs/sqlfluff-1625-repeat-verification
```

子目录：

```text
runs/sqlfluff-1625-repeat-verification/run-1
runs/sqlfluff-1625-repeat-verification/run-2
runs/sqlfluff-1625-repeat-verification/run-3
```

每次 run 都使用同一个真实 Docker sandbox 流程：

1. `read_file src/sqlfluff/rules/L031.py`
2. 3 次 `apply_patch` 修改容器内 `src/sqlfluff/rules/L031.py`
3. `run_tests` 执行 `python -m pytest test/cli/commands_test.py::test__cli__command_directed`
4. `final solved`
5. sandbox 结束前从容器内执行 `git diff --binary HEAD` 导出补丁

每次 run 的产物检查结果一致：

```text
status: solved
changed_files: ["src/sqlfluff/rules/L031.py"]
test_summary: {"passed": 1}
apply_patch statuses: ["ok", "ok", "ok"]
run_tests statuses: ["passed"]
trajectory.resolved: true
final_diff length: 1365
final.patch length: 1365
prediction.model_patch length: 1365
final.patch CR count: 0
last_successful_tool_call: run_tests
```

### 独立容器补丁验证

每个 run 的 `final.patch` 又分别放进全新一次性容器验证：

1. 应用补丁前直接 lint issue SQL：

```python
from sqlfluff.core import Linter
sql = 'SELECT a.[hello]\nFROM\n    mytable AS a'
violations = Linter(dialect='tsql', rules=['L031']).lint_string(sql).get_violations()
print([v.rule_code() for v in violations])
```

baseline 输出均为：

```text
['L031']
```

2. 对每个补丁执行：

```text
git -C /workspace/repo apply --check /tmp/final.patch
git -C /workspace/repo apply /tmp/final.patch
```

3. 应用补丁后再次 lint 同一 SQL，3 次输出均为：

```text
[]
```

4. `git diff --name-only HEAD` 均只包含：

```text
src/sqlfluff/rules/L031.py
```

### 本次再次暴露的假阳性

重复验证前先用了一版过期 scripted edit 字符串，结果出现：

```text
status: solved
test_summary: {"passed": 1}
changed_files: []
final_diff length: 0
final.patch length: 0
prediction.model_patch length: 0
```

查看 `trajectory.jsonl` 后确认 3 次 `apply_patch` 全部是：

```text
{"error": "not found"}
```

但 `run_tests` 仍然 passed。这再次证明：`FAIL_TO_PASS` passing 不是充分条件，必须同时检查：

- 关键 `apply_patch` 的 tool result 必须是 `ok`
- `changed_files` 必须包含预期文件
- `trajectory.json.final_diff` 必须非空
- `final.patch` 必须非空且 LF-only
- `prediction.jsonl.model_patch` 必须非空
- 独立容器里 `git apply --check` 必须通过
- 应用补丁后必须复现 issue 症状已消失

### 本次项目回归验证

执行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests\unit\test_container_tools.py tests\integration\test_swebench_sandbox_run.py tests\unit\test_prediction.py tests\integration\test_run_artifact_consistency.py -q
```

结果：

```text
14 passed in 0.17s
```

语法检查：

```powershell
python -m py_compile src\coding_agent\sandbox\tools.py src\coding_agent\swebench\sandbox_run.py
```

结果：退出码 0。

容器清理检查：

```powershell
docker ps --filter name=coding-agent --format "table {{.Names}}\t{{.Status}}"
```

结果只剩表头：

```text
NAMES     STATUS
```

## 2026-06-12 三个不同 SQLFluff 问题验证记录

按“不同问题”重新验证了 3 个独立 instance：

```text
runs/sqlfluff-three-distinct-problems/sqlfluff__sqlfluff-2419
runs/sqlfluff-three-distinct-problems/sqlfluff__sqlfluff-1733
runs/sqlfluff-three-distinct-problems/sqlfluff__sqlfluff-1763
```

这次暴露并修复了一个 runner 缺口：很多 SWE-bench 的 `FAIL_TO_PASS` 测试来自官方
`test_patch`，base commit 本身没有这些测试。sandbox run 现在会在 agent 动作前应用并暂存
`test_patch`，让验证测试存在；最终导出的 `final.patch` 只取未暂存的 agent 源码改动，避免把
测试补丁混进 model patch。

同时修复了 Windows Docker stdin 问题：原来的 `subprocess.run(text=True, input=...)` 会把
stdin 换成 CRLF，并可能破坏非 ASCII patch 内容。现在 Docker CLI wrapper 用 UTF-8 bytes
传 stdin，再把 stdout/stderr 解码回字符串。

### 三个问题的 run 结果

`sqlfluff__sqlfluff-2419`

```text
base_commit: f1dba0e1dd764ae72d67c3d5e1471cf14d3db030
changed_files: ["src/sqlfluff/rules/L060.py"]
test: python -m pytest test/rules/std_L060_test.py::test__rules__std_L060_raised
status: solved
test_summary: {"passed": 1}
apply_patch statuses: ["ok"]
trajectory.resolved: true
final.patch length: 482
final.patch CR count: 0
```

`sqlfluff__sqlfluff-1733`

```text
base_commit: a1579a16b1d8913d9d7c7d12add374a290bcc78c
changed_files: ["src/sqlfluff/rules/L039.py"]
test: python -m pytest test/rules/std_L003_L036_L039_combo_test.py::test__rules__std_L003_L036_L039
status: solved
test_summary: {"passed": 1}
apply_patch statuses: ["ok"]
trajectory.resolved: true
final.patch length: 685
final.patch CR count: 0
```

`sqlfluff__sqlfluff-1763`

```text
base_commit: a10057635e5b2559293a676486f0b730981f037a
changed_files: ["src/sqlfluff/core/linter/linted_file.py"]
test: python -m pytest test/core/linter_test.py::test_safe_create_replace_file[utf8_create] test/core/linter_test.py::test_safe_create_replace_file[utf8_update] test/core/linter_test.py::test_safe_create_replace_file[utf8_special_char]
status: solved
test_summary: {"passed": 1}
apply_patch statuses: ["ok", "ok"]
trajectory.resolved: true
final.patch length: 1523
final.patch CR count: 0
```

### 独立容器验证结果

每个实例都在全新一次性容器中验证：

1. checkout 到对应 `base_commit`
2. 应用官方 `test_patch`
3. 运行 `FAIL_TO_PASS`，确认 baseline 失败
4. 应用该 run 产出的 `final.patch`
5. 再运行同一 `FAIL_TO_PASS`，确认通过

结果：

```text
sqlfluff__sqlfluff-2419: baseline_exit 1 -> after_exit 0, changed_files ["src/sqlfluff/rules/L060.py"]
sqlfluff__sqlfluff-1733: baseline_exit 1 -> after_exit 0, changed_files ["src/sqlfluff/rules/L039.py"]
sqlfluff__sqlfluff-1763: baseline_exit 1 -> after_exit 0, changed_files ["src/sqlfluff/core/linter/linted_file.py"]
```

### 本次新增回归测试

执行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests\unit\test_docker_cli.py tests\unit\test_swebench_dataset.py tests\unit\test_container_tools.py tests\integration\test_swebench_sandbox_run.py tests\unit\test_prediction.py tests\integration\test_run_artifact_consistency.py -q
```

结果：

```text
26 passed in 0.68s
```

语法检查：

```powershell
python -m py_compile src\coding_agent\sandbox\docker_cli.py src\coding_agent\sandbox\tools.py src\coding_agent\swebench\dataset.py src\coding_agent\swebench\sandbox_run.py
```

结果：退出码 0。

容器清理检查：

```powershell
docker ps --filter name=coding-agent --format "table {{.Names}}\t{{.Status}}"
```

结果只剩表头：

```text
NAMES     STATUS
```
