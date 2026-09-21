# AutoUI MCP v2.1 实现指南

本文是代码维护入口，只说明当前实现、运行方式、扩展位置和发布前待办。

- 架构哲学、模块关系与通信协议：[`treeland-autoui-mcp-v2-design.md`](treeland-autoui-mcp-v2-design.md)
- 真实桌面验收步骤：[`manual-test-guide.md`](manual-test-guide.md)
- 对外使用示例：[`../README.md`](../README.md)

## 当前状态

v2.1 的代码与文档收敛已经完成。发布前只剩 P5：在真实 Treeland/Deepin 会话中执行验收。
环境未验收不等于模型、策略或执行失败，必须单独记录。

| 范围 | 状态 | 结果 |
| --- | --- | --- |
| P0–P4、P6–P19 | 完成 | 核心事实链、扩展边界、公开协议、命名和文档已经收敛 |
| P5 | 待完成 | 真实 Treeland/Deepin 环境回归 |

已实现的稳定边界：

- 事实链固定为 `Proposal → PolicyDecision → ExecutionReceipt → Evidence → AssertionResult → TaskState`。
- 未调用执行器时没有 `ExecutionReceipt`；执行送达不等于业务断言通过。
- `TaskState` 是公开任务状态的唯一来源，协议错误单独归并为 `failed`。
- `gui_run` 只暴露任务生命周期；逐阶段事实和 Attribution 只通过 `gui_diagnostic` 查看。
- Core 不依赖具体合成器、模型、证据实现或桌面平台工具。

## 运行与验证

```bash
uv run treeland-autogui-mcp --config config/mcp-autoui.json
uv run autoui-smoke --config config/mcp-autoui.json
uv run --with pytest pytest -q
```

所有非秘密运行配置来自 `--config` 指定的 JSON。环境变量只承载模型密钥和桌面会话资源；旧行为变量
会被忽略并告警。HTTPS 使用系统信任库，不在项目配置中关闭证书验证或指定私有 CA 文件。

`autoui-smoke` 是只读预检：输出脱敏 effective config，检查 provider 配置和
`treeland-debug --json tree`，然后调用 `gui_run(describe)`。部署在反向代理之后时使用
`--mcp-url https://host/mcp` 指向真实入口。

## 阅读顺序

| 关注点 | 入口 |
| --- | --- |
| MCP 注册与依赖组装 | `src/mcp_autogui/mcp_autogui_main.py`、`src/mcp_autogui/runtime_description.py` |
| 公开与诊断协议 | `src/mcp_autogui/facade.py`、`src/mcp_autogui/protocol_response.py` |
| Proposal 事务与有界运行 | `src/mcp_autogui/core/orchestrator.py` |
| Proposal、Decision、Receipt | `src/mcp_autogui/core/transaction.py` |
| TaskContract 与 TaskState | `src/mcp_autogui/core/task.py`、`src/mcp_autogui/core/task_state.py` |
| 运行态与事实记录 | `src/mcp_autogui/core/task_repository.py`、`src/mcp_autogui/core/transaction_recorder.py` |
| 桌面工具事务入口 | `src/mcp_autogui/desktop_transactions.py`、`src/mcp_autogui/desktop_backend.py` |
| 策略与 Guard | `src/mcp_autogui/core/action_gate.py` |
| Evidence 与 Assertion | `src/mcp_autogui/core/evidence.py`、`src/mcp_autogui/core/assertion_evaluator.py` |
| Ledger 与 Attribution | `src/mcp_autogui/core/audit_recorder.py`、`src/mcp_autogui/core/ledger.py` |
| 端口与外部实现 | `src/mcp_autogui/ports/`、`src/mcp_autogui/adapters/` |
| 配置与 provider 注册 | `src/mcp_autogui/server_config.py`、`src/mcp_autogui/provider_registry.py` |

主路径应能直接读成：

```text
AutoUIFacade
  → CoreOrchestrator
      → observe → propose → ActionGate.decide
          ├─ deny / confirm / stale / invalid → TaskState
          └─ allow → ActionExecutor → ExecutionReceipt
                                      → EvidenceRecord → AssertionResult → TaskState
```

模块之间传递领域对象或不可变对象引用，不传“类似 receipt”的临时结构。Repository 保存当前运行态，
Recorder 保存事实及因果记录；Attribution 是失败后的诊断旁路，不参与正常控制流。

## 对外边界

`gui_run` 只接受：

- `describe`
- `run`
- `status`
- `confirm`
- `reset`

公开状态只有 `running`、`needs-confirmation`、`retrying`、`completed`、`failed`。

`gui_diagnostic` 提供 `describe`、`observe`、`propose`、`decide`、`execute`、`evaluate`、`trace`，
用于调试、审计和 benchmark，不作为普通调用方的工作流 API。

## 扩展方式

- **新合成器**：实现 `ports/compositor.py`，在 desktop backend 中组装，并添加 canonical fixture 测试。
- **新桌面环境**：新增完整 `DesktopBackend`；快捷键、应用目录和启动事务随 backend 提供，不进入 Core。
- **新执行器**：实现 `ports/executor.py`；只返回实际执行事实，不判断业务成功。
- **新模型**：实现 `ports/proposal.py` 并注册 provider；每次产生一个 Proposal，可包含有序动作序列。

## Proposal 动作序列实现

- `ActionProposal.actions` 是非空有序序列；`action` 保留为首动作兼容视图，旧单动作输入会规范化为
  长度为一的序列。
- `PolicyDecision`、语义策略与用户确认以整个 Proposal 为单位。Core 为需要环境依赖的原子动作保存
  有序 Guard，并在首次注入前统一重检，避免部分执行后才发现 Proposal 已失效。
- Core 依次把原子动作交给现有执行器。动作间不调用 provider、不 capture 新 observation；首个失败会
  截断余下序列。Proposal 级 `ExecutionReceipt` 保存 `executed_actions` 和 `action_receipts`，trace 与
  持久审计沿用统一对象序列化，无第二套审计格式。
- 只有完整序列送达后才 capture observation、收集 Evidence 并评估 Assertion；任务步数按 Proposal
  增长一次。失败序列保留部分执行事实，但不会进入成功评估。
- Qwen parser 接受同一响应中的一个或多个 `tool_call`，保持模型顺序；prompt 允许模型按自身粒度返回
  最小动作序列，但禁止把依赖前一步界面变化的动作预先打包。其他 provider 只需返回相同领域对象。
- schema revision 为 `2.1-p5`；序列权限、语义合并、Guard、短路执行、原子回执和多 tool-call 解析均有
  自动回归覆盖。
- **新证据源**：实现 `ports/evidence.py`，声明标准 fact path，并覆盖 unknown、conflict 和过期证据。

扩展不得增加第二套公开状态、错误码 registry 或平台条件分支。未知 provider、重复注册和无效配置必须
在启动时失败。

## P5 真实环境回归

代码边界收敛后，发布前仍需完成真实 Treeland/Deepin 回归：

1. 安装服务证书到系统信任库，通过 HTTPS 调用实际 MCP 入口。
2. 运行 `autoui-smoke`，确认 tree、provider 和 `gui_run(describe)` 均可用。
3. 按 `manual-test-guide.md` 执行 V2-01～V2-15，并保存必要 trace 与 artifact 引用。
4. 将证书、代理、桌面会话或外部服务问题记为环境阻塞；领域失败按 ReasonCode 与 Attribution 归因。

## 文档维护

- 架构文档只描述稳定设计，不记录实施进度。
- 本文只维护当前实现、阅读入口、扩展方式和发布前待办。
- 逐提交改动、排障过程和中间方案由 Git 历史承担。
