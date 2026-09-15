# AutoUI MCP v2.1 实现指南

本文是代码维护入口，只说明当前实现、运行方式、扩展位置和发布前待办。

- 架构哲学、模块关系与通信协议：[`treeland-autoui-mcp-v2-design.md`](treeland-autoui-mcp-v2-design.md)
- 真实桌面验收步骤：[`manual-test-guide.md`](manual-test-guide.md)
- 对外使用示例：[`../README.md`](../README.md)

## 当前状态

v2.1 的 P0–P4、P6–P18 已完成。P19 用于统一命名、收口运行描述并再次压缩本文；发布前仍需完成
P5 真实 Treeland/Deepin 回归。环境未验收不等于模型、策略或执行失败，必须单独记录。

| 阶段 | 交付基线 |
| --- | --- |
| P0–P4 | 配置、ReasonCode、事实对象、五态 TaskState 与 compact facade |
| P6–P9 | 状态仓库、事务记录、并发边界、provider 注册与公开/诊断入口 |
| P10–P13 | 领域文件、调用文档、配置入口与可选 LangChain 边界 |
| P14–P16 | 可读模型、desktop backend 平台工具与 TaskState 状态权威 |
| P17 | 当前实现文档收敛 |
| P18 | 完成：桌面事务、Facade、协议错误与依赖测试边界已收敛 |
| P19 | 计划：统一人类可理解的命名，收口运行描述，压缩实施记录 |

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
| MCP 注册与依赖组装 | `src/mcp_autogui/mcp_autogui_main.py` |
| 公开与诊断协议 | `src/mcp_autogui/facade.py`、`src/mcp_autogui/protocol_response.py` |
| 单步事务与有界运行 | `src/mcp_autogui/core/orchestrator.py` |
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
Facade
  → CoreOrchestrator
      → observe → propose → ActionGate.decide
          ├─ deny / confirm / stale → TaskState
          └─ allow → ActionExecutor → Receipt
                                      → Evidence → Assertion → TaskState
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
- **新模型**：实现 `ports/proposal.py` 并注册 provider；每次只产生一个 Proposal。
- **新证据源**：实现 `ports/evidence.py`，声明标准 fact path，并覆盖 unknown、conflict 和过期证据。

扩展不得增加第二套公开状态、错误码 registry 或平台条件分支。未知 provider、重复注册和无效配置必须
在启动时失败。

## P18 最终边界收敛（完成）

P18 没有增加领域状态或改变事实链，只完成以下边界收敛：

- desktop backend 通过 `DesktopTransactionRunner` 发起事务，不持有完整 Core runtime。
- `gui_run` 与 `gui_diagnostic` 使用独立分派路径。
- Core 不再构造 MCP response envelope，失败通过带 `ReasonCode` 的类型传递。
- 架构测试约束 Core、adapter、desktop backend 和 Facade 的依赖方向。

验收结果：主事务无需进入平台实现即可阅读；公开路径只按 `TaskState` 约简；全量自动化测试通过。

## P19 命名与可读性收敛（计划）

P19 只解决名称误导、只读描述耦合和文档重复，不拆分稳定事务，不增加领域状态，不引入新的错误码体系。

### P19a：统一入口与响应命名（完成）

- `AutoUIFacade` 明确覆盖 `gui_run` 和 `gui_diagnostic` 两类入口。
- `protocol_response.py` 同时容纳公开 response reducer 与诊断 response builder。
- `OperationFailure` 表达应用操作失败，避免被理解为 MCP transport 或 schema 损坏。
- compositor 接口统一为 `CompositorPort`；`TreelandAdapter` 等具体实现保留 adapter 后缀。

验收：只看类名和文件名即可区分公开响应、诊断响应、port 接口和 adapter 实现；协议字段保持兼容。

### P19b：收口只读运行描述（完成）

- Facade 不再逐项读取 compositor、executor、provider、gate 和 context builder 的内部属性。
- 组装层通过冻结的 `RuntimeDescription` 生成能力、provider ID、策略 profile 和 context strategy 快照。
- 运行描述只服务于 `describe`；每次读取返回独立数据，不保存或参与任务状态。

验收：新增 provider 或 backend 时，只修改组装与描述构造，不修改 Facade 的内部属性访问列表。

### P19c：保持实现文档克制

- 已完成阶段只保留目标、稳定结果和验收结论。
- 逐提交改动、排障过程和中间方案由 Git 历史承担。
- 当前文档只维护阅读入口、扩展规则、未完成计划和发布前待办。

验收：实现文档可以从头顺序阅读，不需要从阶段日志中反推当前架构。

## P5 真实环境回归

代码边界收敛后，发布前仍需完成真实 Treeland/Deepin 回归：

1. 安装服务证书到系统信任库，通过 HTTPS 调用实际 MCP 入口。
2. 运行 `autoui-smoke`，确认 tree、provider 和 `gui_run(describe)` 均可用。
3. 按 `manual-test-guide.md` 执行 V2-01～V2-10，并保存必要 trace 与 artifact 引用。
4. 将证书、代理、桌面会话或外部服务问题记为环境阻塞；领域失败按 ReasonCode 与 Attribution 归因。

详细实施历史由 Git 提交记录承担，不在本文维护第二份变更日志。
