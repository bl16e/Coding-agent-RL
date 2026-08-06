# SWE-smith 干净 Teacher Trajectory 的 Harness/Prompt 优化设计

日期：2026-08-05

## 背景

当前 Stage 2 使用 teacher model 解 SWE-smith `sft_candidate` 任务，并通过 official
eval 与 deterministic quality gate 过滤出最终 SFT 数据。我们希望 SFT 只消费“干净”
trajectory：

- official eval resolved；
- patch 只修改源代码，不修改 tests/fixtures/snapshots/expected；
- reasoning 记录完整；
- 不包含错误的工具使用模式；
- 不包含被 harness 拒绝的 blocked `execute_bash` attempt。

最近一批 `stage2_sft8000_top39_b0001` 的 r2/r3 结果显示，teacher 能解出一部分
任务，但 rejected attempt 仍然偏多，主要集中在：

- `git log` / `git status`；
- `grep`；
- `find / -name ...`；
- `head` / `tail`；
- 在 `/root/.cache`、`/opt`、`/tmp`、site-packages 中探测环境。

这些 attempt 大多被 `ContainerToolExecutor` 拒绝，并未真正执行。但如果直接把带
rejected attempt 的 trajectory 用于 SFT，会训练 student 模型“先犯错，再纠正”，
不适合作为高质量模仿学习数据。

## 当前状态

### 已经具备的约束

`src/coding_agent/config/templates/system.j2` 已在 system prompt 中约束：

- 不要在 `execute_bash` 中使用 pipe、redirection、heredoc；
- 不要使用 `cat/head/tail/grep/find/awk/sed/git`；
- 读文件用 `read_file`；
- 搜索代码用 `search_code`；
- pytest 直接运行，不要 pipe 到 `tail`。

`src/coding_agent/tools/schemas.py` 也在 `execute_bash` schema 中重复说明了这些限制。

`src/coding_agent/tools/container_executor.py` 在运行时会拒绝：

- `git`；
- `cat/head/tail/less/more`；
- `grep/find/awk/sed`；
- `ipython/jupyter/nohup`。

### 当前不足

1. Prompt 主要是“禁止项”，缺少高频错误到正确工具的替代表。
2. `ContainerToolExecutor` 的 rejected message 太短，且当前部分输出存在编码乱码。
3. 对 `git` 的替代建议不足；模型不知道“不需要看历史，只看当前工作树”。
4. `search_code` 当前擅长按内容搜索，但返回结果没有覆盖“文件路径/文件名命中”，导致模型自然退回 `find`。
5. `execute_bash` 运行时主要按命令名拦截，尚未系统性预检 pipe/redirection/heredoc。
6. Quality gate 目前可以检测 blocked attempt，但还没有把 rejected attempt 单独分类成可诊断指标。

## 原则

### SFT 必须保持干净

最终 SFT 数据不应包含 rejected blocked attempt。即使 attempt 被 harness 拒绝、没有真正执行，也不应直接进入 SFT。

原因：

- SFT 学的是完整行为轨迹；
- rejected attempt 会教 student 模型先选择错误工具；
- 这会增加后续 RL 冷启动时的 operational failure；
- 高质量 SFT 宁可少，也不应混入错误工具选择模式。

### Rejected attempt 不等于丢弃任务

带 rejected attempt 的样本不进入 SFT，但可以保留用途：

- 进入 RL task pool；
- 用于 prompt/harness 诊断；
- 后续通过 sanitizer 自动清洗后再二次评估；
- 统计各类错误工具选择的发生率。

### Harness 应优先把错误挡在执行前

对于 `git/grep/find/cat/head/tail` 这类错误用法，harness 应：

- 在执行前拒绝；
- 给出明确替代工具；
- 不让命令实际运行；
- 在 trajectory 中留下清晰、可分析的 rejected observation。

## 优化方案

## 1. 强化 Prompt：加入替代表

在 `system.j2` 的 Shell restrictions 后增加一张操作映射表。

建议内容：

```text
Tool substitution rules:
- To inspect a file, call read_file. Do not use cat/head/tail.
- To inspect a directory, call read_file on the directory path. Do not use ls | head.
- To search code text, call search_code. Do not use grep.
- To find files by filename, call search_code with the filename or path regex. The result will mark path matches with `match_type="path"` and content matches with `match_type="content"`.
- To inspect examples or expected output files, use read_file with view_range.
- Do not use git status/log/show/diff. Work only from the current working tree.
- Do not inspect pip cache, /root/.cache, /tmp, /opt, or site-packages to infer external answers.
- For pytest output, run python -m pytest ... -x --tb=short. Do not pipe to head/tail.
```

再加入具体替代示例：

```text
Bad: grep -n "Token" pygments/lexers/*.py
Good: search_code({"pattern": "Token", "glob": "pygments/lexers/**/*.py"})

Bad: find / -name "graphics.py"
Good: search_code({"pattern": "graphics\\.py$"})
The returned match will have match_type="path".

Bad: cat tests/examplefiles/foo.output | head
Good: read_file({"file_path": "tests/examplefiles/foo.output", "view_range": [1, 80]})

Bad: git log -- file.py
Good: Do not inspect git history. Use read_file/search_code on current files only.
```

目标是让模型在“想做某件事”时看到可执行替代动作，而不是只看到禁令。

## 2. 强化 Tool Schema：把替代方式写进 `execute_bash`

`execute_bash` schema 当前已经有禁止说明，但 description 还偏泛。建议改成更强的形式：

```text
Use execute_bash only for:
- python scripts
- pytest
- pip install
- project-specific test/lint commands

Do not use it for:
- reading files
- listing many files
- searching code
- inspecting git history/status
- shell output shaping

Use:
- read_file for file or directory inspection
- search_code for text search and filename/path search
```

示例中不要出现 `pip list`、`ls | head`、`grep`、`find` 等容易诱导错误的命令。

## 3. 增强 `search_code`：同时返回文件路径匹配和内容匹配

当前 rejected attempt 中多次出现：

- `find / -name "graphics.py"`;
- `find / -name "dotnet.py"`;
- `find / -name "c_cpp.py"`;
- `find /tmp/... -path "*examplefiles*"`.

这说明模型需要“按文件名/路径找文件”的能力。但我们不希望扩大动作空间，因此不新增
`find_files` 或 `list_files` 工具，而是增强现有 `search_code`：

输入 schema 保持不变：

```json
{
  "tool_name": "search_code",
  "input": {
    "pattern": "graphics\\.py$",
    "head_limit": 100
  }
}
```

`search_code` 内部同时执行两类匹配：

- path match：正则匹配 repo-relative path；
- content match：正则匹配文件内容行。

返回 schema 仍然使用 `matches`，但每条结果增加 `match_type`：

```json
{
  "matches": [
    {
      "path": "pygments/lexers/graphics.py",
      "line": null,
      "text": "",
      "match_type": "path"
    },
    {
      "path": "pygments/lexers/graphics.py",
      "line": 42,
      "text": "class GraphicsLexer(...):",
      "match_type": "content"
    }
  ],
  "truncated": false,
  "engine": "python"
}
```

约束：

- 只能在 repo root 下搜索；
- 默认排除 `.git`、`.venv`、`venv`、`node_modules`、`build`、`dist`、`.tox`、`__pycache__`、`.pytest_cache`；
- 不允许搜索 `/`、`/root`、`/tmp`、`/opt`、site-packages；
- path match 先于 content match 返回；
- `head_limit` 同时限制 path match 与 content match 的总数量；
- 超过 `head_limit` 截断并标记 `truncated=true`。

这样模型仍然只学习一个搜索工具：

```text
search_code
```

但它可以同时替代：

- `grep`：内容搜索；
- `find -name`：文件名/路径搜索。

## 4. 改善 Executor 拒绝信息

当前拒绝信息类似：

```text
'find' is blocked бк use search_code instead
```

问题：

- 有编码乱码；
- 信息过短；
- 对 `git` 没有替代建议；
- 没有说明该 attempt 会导致 SFT quality rejection。

建议统一拒绝信息模板：

```text
Rejected: `find` is not allowed in execute_bash.
Reason: file discovery must use repo-scoped tools, not shell find.
Use: search_code({"pattern": "<filename_regex>"}) and read results with match_type="path".
This rejected attempt may disqualify the trajectory from SFT.
```

不同命令的替代建议：

| 被拒命令 | 替代方式 |
| --- | --- |
| `grep` / `awk` / `sed` | `search_code`，读取 `match_type="content"` |
| `find` | `search_code`，读取 `match_type="path"`；必要时再用 `read_file` 列目录 |
| `cat` / `head` / `tail` / `less` / `more` | `read_file` + `view_range` |
| `git status` / `git log` / `git show` / `git diff` | 不允许；只看当前工作树文件 |
| `pip list | grep` | 不允许；不要通过环境探测外部答案 |

## 5. Executor 增加 shell syntax 预检

当前 runtime block 主要按 subcommand 首词识别。建议复用 quality gate 中更精确的 token parser，在 `execute_bash` 执行前预检：

Hard reject：

- `|` / `|&`；
- `>` / `>>` / `<`；
- heredoc：`<<` / `<<<`；
- command substitution：`$(...)`、反引号；
- blocked executables：`git/cat/head/tail/grep/find/awk/sed`。

允许例外：

- `&&`；
- `;`；
- `||` 作为 fallback；
- `2>/dev/null` / `2>>/dev/null`；
- `2>&1`。

理由：

- `&&` 和 `;` 对诊断脚本很常用；
- `||` 常用于 fallback test command；
- stderr suppression 到 `/dev/null` 不污染 repo，也不会隐藏 stdout；
- 其他 redirection/heredoc 容易写文件、隐藏输出或制造不可审计脚本。

## 6. Quality Gate 指标拆分

保持 SFT 严格，但把原因拆细，便于定位优化效果。

建议新增 metrics：

```json
{
  "blocked_execute_bash_executed_count": 0,
  "blocked_execute_bash_rejected_count": 2,
  "blocked_execute_bash_rejected_commands": [
    {
      "step_index": 19,
      "command": "ls tests && ... | head -50",
      "blocked_token": "head",
      "suggested_tool": "read_file"
    }
  ]
}
```

SFT gate 策略：

- 只要有 `blocked_execute_bash_executed_count > 0`，hard reject；
- 只要有 `blocked_execute_bash_rejected_count > 0`，默认仍 hard reject；
- 但 report 中标记为 `recoverable_blocked_attempt`，后续 sanitizer 可以处理。

这样既保持 SFT 干净，又能统计“本来可以通过，但工具选择不干净”的样本。

## 7. Sanitizer 作为后续阶段

不建议现在直接把 rejected attempt 样本放入 SFT。但可以设计一个后处理 sanitizer：

输入：

- resolved trajectory；
- quality gate report；
- blocked rejected attempt 列表。

处理：

- 删除 rejected tool call；
- 删除对应 rejected observation；
- 检查下一条 assistant reasoning 是否依赖该 rejected observation；
- 重新导出 messages；
- 重新跑 quality gate；
- 只接受清洗后仍连贯、无 blocked attempt、resolved 的样本。

注意：

- sanitizer 不能修改 patch；
- sanitizer 不能伪造 tool output；
- sanitizer 不能删除实际执行过的 blocked command；
- sanitizer 后必须保留 audit lineage：原始 trajectory id、删除的 step index、原因。

## 推荐实施顺序

### Phase 1：低风险 prompt/harness 改进

1. 修复 rejected message 编码和内容；
2. 在 prompt/schema 加入替代表；
3. quality gate 拆分 rejected/executed blocked metrics；
4. 保持 SFT 严格，不放宽 rejected attempt。

预期收益：

- 模型第二次犯同类错误的概率降低；
- rejected attempt 原因更可统计；
- 不影响现有工具接口。

### Phase 2：增强 `search_code` 的 path match

1. 不新增 tool schema；
2. 保持 `search_code` 输入参数不变；
3. 在 `search_code` 实现中先匹配 repo-relative path，再匹配内容行；
4. 在返回结果中增加 `match_type="path"` / `match_type="content"`；
5. 在 prompt/schema 中把 `find` 替代为 `search_code(pattern=<filename_regex>)`；
6. 添加单元测试和 fake container 测试。

预期收益：

- 大幅减少 `find / -name ...`；
- 避免模型去 `/root/.cache`、`/tmp`、`/opt`、site-packages 探测。
- 不增加动作空间，student 仍只学习现有工具集合。

### Phase 3：executor 预检 shell syntax

1. 抽取 shared shell policy；
2. quality gate 与 executor 共用同一套 parser；
3. 运行前拒绝 pipe/redirection/heredoc；
4. 拒绝消息给出替代工具。

预期收益：

- 错误 shell pattern 在执行前被统一拦截；
- quality gate 与 runtime 规则一致；
- 轨迹错误更早暴露。

### Phase 4：sanitizer

1. 只处理 `status=rejected` 的 blocked attempt；
2. 不处理实际执行过的 blocked command；
3. 清洗后重新 quality gate；
4. 输出 `sanitized.filtered.jsonl` 与 audit report。

预期收益：

- 回收一部分 resolved 但有单次 rejected attempt 的样本；
- 不污染主 SFT 数据。

## 验收指标

每个 Stage 2 batch 记录：

- `accepted_count / total`；
- `blocked_execute_bash_rejected_count`；
- `blocked_execute_bash_executed_count`；
- blocked token 分布：`git/grep/find/head/tail/...`；
- 因 `find` 被拒的比例；
- 因 `git` 被拒的比例；
- teacher resolved 但因 rejected attempt 被拒的样本数；
- sanitizer 可回收数。

短期目标：

- `blocked_execute_bash_executed_count = 0`；
- `blocked_execute_bash_rejected_count` 持续下降；
- SFT accepted rate 提升时不牺牲干净轨迹标准。

## 当前批次观察

`stage2_sft8000_top39_b0001` r3 中：

- accepted：9/20；
- rejected：11/20；
- 剩余 blocked 主要来自 `grep/find/git`；
- 这些 attempt 多数已被 executor 拒绝；
- 说明 runtime block 有效，但 prompt/tool affordance 仍不足。

代表性错误：

```text
find / -name "graphics.py" -path "*lexers*" 2>/dev/null
git log --oneline -5 -- pygments/lexers/graphics.py
pip list 2>/dev/null | grep -i pygments
grep -n "Number" tests/examplefiles/csharp/test.cs.output | head -60
```

对应优化：

- `search_code(match_type="path")` 解决文件名/路径查找；
- `read_file(view_range)` 解决查看文件片段；
- `search_code` 解决文本匹配；
- prompt 明确禁止 git history/status，要求只基于当前工作树修复。

## 结论

不建议为了提高短期 accepted rate 而让带 rejected attempt 的 trajectory 直接进入 SFT。

正确方向是：

1. 保持 SFT quality gate 对 rejected attempt 严格；
2. 在 harness/prompt 源头减少错误工具选择；
3. 增强 `search_code` 补齐文件名/路径查找能力；
4. 将 rejected attempt 细分为可诊断指标；
5. 后续用 sanitizer 有审计地回收 recoverable resolved 样本。

这样可以同时保证 SFT 数据干净、teacher 利用率可逐步提升，并为 Stage 4 RL 保留未进入 SFT 的任务。
