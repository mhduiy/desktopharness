# AutoUI MCP v2.1 实现指南

本文是维护入口：记录当前实现状态、代码落点与验证方式。

- 架构原则与通信协议：[`treeland-autoui-mcp-v2-design.md`](treeland-autoui-mcp-v2-design.md)
- 真实桌面验收：[`manual-test-guide.md`](manual-test-guide.md)

## 当前状态

| 阶段 | 状态 | 已交付 |
| --- | --- | --- |
| P0 | 完成 | JSON effective config、旧归档夹具、ReasonCode 基础 |
| P1 | 完成 | 未执行路径只返回 Decision，不产生 Receipt |
| P2 | 完成 | 单一 `ActionExecutor`，backend 路由应用启动/快捷键/输入 |
| P3 | 完成 | `claimed_intent`、五态 TaskState、compact facade、`confirm` |
| P4a | 完成 | 新 Ledger 不写重复 `epistemic_type`，旧 CSV 可读 |
| P4b | 完成 | Context 仅保留 compact/recovery；EvidenceRecord 已收敛且不缓存 verified facts |
| P5 | 进行中 | `autoui-smoke` 实际调用只读 `gui_run(describe)`；待真实环境回归 |
| P6 | 完成 | 协议对象强制 ReasonCode；Core、adapter 与 Facade 不再构造裸错误码 |
| P7a | 完成 | 运行态索引迁入 TaskRepository；事件、引用与归因迁入 AuditRecorder |
| P7b | 完成 | Repository 意图 API、TransactionRecorder 与 event_type 唯一事件类别已收敛 |
| P7c | 完成 | 桌面执行/reset 串行，运行态原子更新，trace 保持只读 |
| P8 | 未开始 | 为 proposal 与 evidence provider 建立统一组装注册机制 |
| P9 | 未开始 | 集中公开状态映射，分离默认操作与诊断操作 |
| P10 | 未开始 | 按领域边界拆分 models.py，不改变通信协议 |

## 运行与预检

```bash
uv run treeland-autogui-mcp --config config/mcp-autoui.json
uv run autoui-smoke --config config/mcp-autoui.json
uv run --with pytest pytest -q
```

`autoui-smoke` 是只读预检：输出脱敏 effective config、provider 配置状态，检查
`treeland-debug --json tree`，并调用 MCP 的 `gui_run(describe)`。反向代理或 HTTPS 部署可用
`--mcp-url https://host/mcp` 指定实际入口。缺少桌面工具、无法读取 tree 或 MCP 不可达均属于环境阻塞，不计入模型或执行失败。

## 代码落点

| 责任 | 主要位置 |
| --- | --- |
| 协议对象与状态 | `src/mcp_autogui/core/models.py`、`core/task_state.py` |
| 事务协调与策略 | `core/orchestrator.py`、`core/action_gate.py`、`core/task_repository.py` |
| 默认 MCP 通信 | `facade.py`、`mcp_autogui_main.py` |
| 执行边界 | `ports/executor.py`、`adapters/executor/`、`adapters/backends/` |
| 观察与证据 | `ports/compositor.py`、`ports/evidence.py`、`adapters/evidence/` |
| 审计 | `core/audit_recorder.py`、`core/audit.py`、`core/ledger.py`、`audit_cli.py` |
| 配置 | `server_config.py`、`config/mcp-autoui.json` |

## 配置规则

所有非秘密运行配置来自 JSON。环境变量只用于模型密钥和桌面会话资源；JSON 模式下出现旧行为变量时
服务会警告其被忽略。HTTPS 使用系统信任库；不要在仓库配置中关闭证书验证。

## 扩展规则

- **新合成器**：新增 `CompositorAdapter` 与 fixture 契约测试，不修改 Core。
- **新桌面能力**：放入 desktop backend，并通过 `ActionExecutor` 路由；禁止任意 shell。
- **新模型**：实现 `ProposalProvider`，只产生单个 Proposal。
- **新证据来源**：实现 `EvidenceProvider`，声明标准 fact path，并添加 unknown/conflict 测试。

## 后续实施计划

以下阶段只收敛实现，不增加新的领域状态，也不改变
`Proposal → Decision → Receipt → Evidence → Assertion → TaskState` 事实链。每个阶段独立修改、测试、确认和提交。

### P6：统一 ReasonCode

目标：让事实对象引用同一套稳定原因码，避免枚举、裸字符串和 Attribution 各自演化。

- `PolicyDecision.reason_code`、`ExecutionReceipt.error_code` 与 Attribution code 使用 `ReasonCode`。
- Core、gate、executor 和 backend 不再直接构造未登记的大写错误码字符串。
- 序列化仍输出稳定字符串，不增加兼容层或第二套 registry。
- Attribution 只补充 stage、owner、event kind，不翻译或重命名原因码。

验收：源码检查不存在协议错误码裸字符串；Decision、Receipt、Attribution 的序列化和现有行为测试通过。

### P7：拆薄 CoreOrchestrator

目标：Core 保留事务语义，但不由一个类同时承担事务、运行态索引和审计投影细节。

#### P7a：分离运行态与审计记录（完成）

- `CoreOrchestrator` 保留公开事务入口和执行顺序。
- task/proposal/decision/receipt 的运行态索引已迁入 `TaskRepository`。
- 事件追加、对象引用、因果关系和 Attribution 已迁入 `AuditRecorder`。
- `ActionGate`、`AssertionEvaluator`、`TaskStateReducer` 保持纯领域组件。

验收：Core 对外方法与事实链不变；Orchestrator 不再直接维护成组状态或审计字典；完整测试通过。

#### P7b：封装状态意图与事务记录（完成）

目标：编排器表达流程，而不是读写运行态容器或构造审计投影。

- `TaskRepository` 只提供 task、proposal、decision、guard、receipt 的意图方法；禁止 Core 直接访问内部字典。
- 新增内部 `TransactionRecorder`，负责 Decision、Receipt、状态变更和 provider feedback 的对象存储与 Ledger 记录。
- `AuditRecorder` 根据 `event_type` 推导对象类别；移除 Core 调用中的重复 `epistemic_type` 参数。
- `CoreOrchestrator` 的主路径应可直接读作 `observe → propose → decide → execute → evaluate`。

验收：Orchestrator 不访问 repository 内部集合，不构造 Ledger object type；Decision/Receipt 的因果链、provider feedback 和 reset 回归通过。

#### P7c：明确并发事务边界（完成）

目标：并发请求不会在观察、Guard 重检与输入注入之间产生不可解释的桌面状态。

- 明确全局 desktop transaction lock 覆盖的最小范围：observe、Guard recheck、execute。
- `TaskRepository` 对单任务状态更新提供原子操作；不把全局桌面锁扩展到模型调用或证据收集。
- 跨任务执行和 reset 与执行竞争已有回归测试；terminal Receipt 仍按 proposal 去重。
- trace 只读取不可变对象引用，不获取桌面事务锁；reset 后的 task trace 按正常的对象不存在语义失败。
- 调用方可依赖桌面副作用串行；模型调用、证据收集和 trace 不被桌面锁阻塞。

验收：同一任务和跨任务的并发测试可重复通过；桌面副作用保持串行，读取和模型调用不被不必要阻塞。

### P8：统一扩展组装

目标：新增模型或证据来源时，只新增实现和注册，不修改配置解析与服务入口的条件分支。

- 为 `ProposalProvider` 和 `EvidenceProvider` 建立与 desktop backend 一致的显式 registry/factory。
- provider 自己声明稳定 ID、配置校验和构造逻辑。
- composition root 只按配置选择 provider，不导入具体实现细节。
- 未知 provider、重复注册和无效配置必须在启动时失败。

验收：用测试 provider 证明扩展无需修改 Core、Facade 或主组装流程；内建 Qwen、compositor、AT-SPI、OmniParser 行为不变。

### P9：收敛公开入口

目标：默认调用面只表达任务生命周期，诊断能力不污染日常协议。

- 使用一个纯映射函数完成 `Domain Result + TaskState → Public Response`。
- 默认入口仅保留 `run`、`status`、`confirm`、`reset` 和 `describe`。
- `observe`、`propose`、`decide`、`execute`、`evaluate`、`trace` 移入独立诊断入口。
- 默认响应不返回 Guard、Attribution、原始对象或内部 pipeline stage。

验收：所有公开状态只有 `running`、`needs-confirmation`、`retrying`、`completed`、`failed`；诊断测试与默认协议测试相互独立。

### P10：拆分领域模型文件

目标：让代码布局反映既有责任边界，降低阅读和修改成本。

- transaction：Proposal、Decision、Receipt 与 Guard。
- task：Contract、TaskState 与限制。
- desktop：Snapshot、Geometry 与 capabilities。
- evidence：Evidence、Assertion 与排除原因。
- audit：LedgerEvent 与 Attribution。
- 对外从 `core` 提供稳定导出，禁止形成循环依赖。

验收：仅移动定义和更新导入，不改变 schema、序列化结果或运行行为；完整测试通过。

## 回归待办

1. 由 `AssertionResult.excluded_evidence` 统一表达过期、失效和冲突。
2. 完成真实 Treeland 回归矩阵，并记录环境阻塞与失败归因。
