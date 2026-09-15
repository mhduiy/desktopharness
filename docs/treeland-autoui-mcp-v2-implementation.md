# AutoUI MCP v2.1 实现指南

本文是代码维护入口，只说明当前实现、运行方式、扩展位置和发布前待办。

- 架构哲学、模块关系与通信协议：[`treeland-autoui-mcp-v2-design.md`](treeland-autoui-mcp-v2-design.md)
- 真实桌面验收步骤：[`manual-test-guide.md`](manual-test-guide.md)
- 对外使用示例：[`../README.md`](../README.md)

## 当前状态

v2.1 的 P0–P4、P6–P17 已完成。剩余工作分为两类：P18 完成最后一轮架构边界收敛；P5 在真实
Treeland/Deepin 会话中完成发布前回归。环境未验收不等于模型、策略或执行失败，必须单独记录。

| 阶段 | 交付基线 |
| --- | --- |
| P0–P4 | 配置、ReasonCode、事实对象、五态 TaskState 与 compact facade |
| P6–P9 | 状态仓库、事务记录、并发边界、provider 注册与公开/诊断入口 |
| P10–P13 | 领域文件、调用文档、配置入口与可选 LangChain 边界 |
| P14–P16 | 可读模型、desktop backend 平台工具与 TaskState 状态权威 |
| P17 | 当前实现文档收敛 |
| P18 | 进行中：P18a–P18c 已完成；P18d 待实施 |

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
| 公开与诊断协议 | `src/mcp_autogui/facade.py`、`src/mcp_autogui/public_response.py` |
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

## P18 最终边界收敛

P18 不改变事实链、公开操作或领域状态，只移除现有的宽接口和职责泄漏。每个子阶段独立测试、确认和提交。

### P18a：窄化桌面事务接口（完成）

- desktop backend 不再接收整个 `CoreOrchestrator` 或 `Any` runtime。
- Core 或应用层提供一个最小事务调用接口，统一完成 register、observe、submit、decide、execute、evaluate。
- 快捷键和应用启动仍由 backend 定义 Contract、Proposal 与平台验证，但不得自行复制核心事务顺序。

验收：backend 只能调用明确声明的事务能力；替换 backend 不修改 Core、Facade 或 MCP 工具签名。

完成：应用层 `CoreDesktopTransactionRunner` 统一 register、observe、submit、decide 与 execute，并按需提供
evaluate；desktop backend 只接收 `DesktopTransactionRunner` 与领域结果，不再持有或导入完整 Core runtime。

### P18b：分离公开与诊断分派（完成）

- `gui_run` 和 `gui_diagnostic` 使用独立分派路径，不再共享 `diagnostic` 布尔开关。
- Contract/Proposal 解析保持共享纯函数；公开 reducer 仍只依据 TaskState 和协议错误。
- 诊断入口展示领域事实，不参与公开状态约简。

验收：公开路径中不存在 Decision/Receipt 状态翻译；新增诊断字段不会影响 `gui_run`。

完成：Facade 使用独立 `_handle_public` 与 `_handle_diagnostic` 路径；公开操作直接生成 compact response，
诊断操作单独展开领域对象。两条路径只共享任务注册、describe 数据和纯解析函数。

### P18c：收回协议错误与响应职责（完成）

- 使用一个携带 `ReasonCode` 和恢复建议的轻量协议异常，删除按异常文本猜测错误码的逻辑。
- 将 `response_envelope` 从 `core/orchestrator.py` 移到 Facade/协议展示层。
- 同步架构文档：公开状态由 TaskState 决定，只有协议错误可直接归并为 `failed`。

验收：Core 不构造 MCP envelope；相同异常信息文本不会改变 ReasonCode；诊断 schema 保持稳定。

完成：`ProtocolFailure` 显式携带 ReasonCode 与恢复建议；Facade 不再解析异常文本。诊断 envelope 已迁入
`public_response.py`，架构文档同步以 TaskState 作为任务状态唯一来源。

### P18d：固化边界并恢复可读性

- 增加依赖测试：Core 不导入 adapters，desktop tools 不依赖完整 Core runtime，公开与诊断分派不回退合并。
- 只整理本阶段触及文件的导入、签名和长表达式；不为减少行数新增零散 helper 或抽象层。
- 完整测试和真实环境测试继续分别报告，不用单元测试替代 P5。

验收：边界测试可阻止上述职责泄漏回归；主事务路径无需跨越平台实现即可阅读。

## P5 真实环境回归

代码边界收敛后，发布前仍需完成真实 Treeland/Deepin 回归：

1. 安装服务证书到系统信任库，通过 HTTPS 调用实际 MCP 入口。
2. 运行 `autoui-smoke`，确认 tree、provider 和 `gui_run(describe)` 均可用。
3. 按 `manual-test-guide.md` 执行 V2-01～V2-10，并保存必要 trace 与 artifact 引用。
4. 将证书、代理、桌面会话或外部服务问题记为环境阻塞；领域失败按 ReasonCode 与 Attribution 归因。

详细实施历史由 Git 提交记录承担，不在本文维护第二份变更日志。
