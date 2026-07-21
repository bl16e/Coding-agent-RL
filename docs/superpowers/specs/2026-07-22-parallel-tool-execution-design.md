# 并行工具执行设计

## 概览

将 agent 的工具执行从串行（每次模型响应只执行一个 tool）升级为模型驱动的并行执行（一次响应中的多个 tool_calls 并发执行）。

对齐 Claude Code 的行为：模型在一次推理中返回多个独立的 tool_call，agent 并发执行它们，统一返回结果。

## 目标

- 模型可以一次响应返回多个 tool_call（如同时 Read 两个文件）
- Agent 使用线程池并发执行这些工具
- 同文件冲突的 Write/Update 自动降级为串行
- 一次多工具响应 = 消耗 1 个 step
- 向后兼容：单 tool_call 的行为不变
- 所有现有测试保持通过

## 非目标

- 不支持 agent 自主判断并行（并行决策权在模型）
- 不支持跨响应的工具调度优化
- 不改变工具本身的实现

## 架构改动

### 1. AgentAction → 支持批量

`ModelBackend.next_action()` 返回 `list[AgentAction]` 替代单个 `AgentAction`。

单 tool 时返回 `[AgentAction]`，多 tool 时返回 `[Action1, Action2, ...]`。
`FINAL` action 必须单独出现，不和工具混在一起。

### 2. 解析全部 tool_calls

`_parse_tool_call_message` 当前只取 `tool_calls[0]`。改为遍历全部 `tool_calls`，每个生成一个 `AgentAction`。

`parse_agent_action` 返回 `list[AgentAction]`。

JSON 文本模式的响应（非原生 function calling）保持单 action，因为 JSON 格式天然只描述一个动作。

### 3. Agent 主循环

```
while not budget_exhausted:
    actions = backend.next_action(messages)        # list[AgentAction]
    write_decision_step(actions)                    # 1 trajectory entry

    if any action is FINAL:
        finish run
        break

    tracker.consume_step()                          # N tools = 1 step

    results = parallel_execute(actions)             # ThreadPoolExecutor
    for each result:
        write_tool_result_step(result)              # N trajectory entries
        messages.append(tool_observation(result))
```

### 4. 冲突检测

在并发执行前，检查 actions 是否有文件冲突：

```
规则：如果两个 action 操作相同的 file_path，且其中至少一个是 Write/Update，
      则将它们标记为冲突组，组内串行执行。

例：
  [Read("a.py"), Read("b.py"), Write("a.py"), search_code(...)]
  冲突组: Read("a.py") + Write("a.py") → 串行
  其余: Read("b.py"), search_code(...) → 并行
```

冲突检测使用简单的 key 匹配（`file_path` 参数），不做 AST 级别的依赖分析。

### 5. 消息格式

工具结果消息保持现有格式。多个 tool result 按 tool_call 顺序依次追加到 messages 列表。

原生 function calling 模式：
```json
{"role": "tool", "tool_call_id": "call_1", "content": "..."},
{"role": "tool", "tool_call_id": "call_2", "content": "..."}
```

### 6. 轨迹

一个 MODEL step 包含多个 tool_call 信息：

```json
{"step_index": 0, "action_type": "model", "tool_calls": [
  {"tool_name": "read_file", "input": {"file_path": "a.py"}},
  {"tool_name": "read_file", "input": {"file_path": "b.py"}}
]}
```

每个 tool 有独立的 TOOL_RESULT step：

```json
{"step_index": 1, "action_type": "tool_result", "tool_call": {...}},
{"step_index": 2, "action_type": "tool_result", "tool_call": {...}}
```

## 实现文件

| 文件 | 改动 |
|------|------|
| `model_backends/base.py` | `next_action` 返回类型改为 `list[AgentAction]` |
| `model_backends/openai_compatible.py` | `_parse_tool_call_message` 遍历全部 tool_calls；`parse_agent_action` 返回列表 |
| `model_backends/mock.py` | 适配新接口 |
| `agent.py` | 主循环改为批量处理；新增 `_parallel_execute()` 和冲突检测 |
| `tools/executor.py` | 无需改动（单个 execute 不变） |
| 测试文件 | 更新 mock backend 返回列表；新增并行执行测试 |

## 错误处理

- 单个工具执行失败不影响同批次其他工具
- 所有结果（成功和失败）都返回给模型
- 线程池的异常被捕获并转为 `ToolExecutionResult(ERROR)`
- 如果所有工具都返回错误，模型会在下一轮看到全部失败信息

## 测试

- Mock backend 适配：最小改动让现有测试通过
- 新增：多 tool 解析测试
- 新增：冲突检测测试
- 新增：并行执行集成测试
- 所有现有单元测试保持通过
