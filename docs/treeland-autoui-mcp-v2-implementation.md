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
| P8 | 完成 | Provider 注册表负责校验与构造；入口只按配置组装 |
| P9 | 完成 | `gui_run` 收敛为生命周期入口，`gui_diagnostic` 隔离内部阶段 |
| P10 | 完成 | 领域模型拆分为独立模块，`models` 保持稳定聚合导出 |
| P11 | 完成 | README 与手工验收指南已切换至公开和诊断双入口 |
| P12 | 完成 | CLI 强制 `--config`，旧运行变量只能被忽略并告警 |
| P13 | 完成 | Core 直导入完成，LangChain 明确为可选 MCP 客户端扩展 |
| P14 | 完成 | 领域模型恢复常规排版，协议与序列化保持不变 |
| P15 | 完成 | 快捷键与应用启动随 DesktopBackend 扩展 |
| P16 | 完成 | TaskState 成为公开状态的唯一来源；协议错误单独归并为 failed |
| P17 | 未开始 | 实现文档只保留当前结构与未完成工作 |

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

完成：`provider_registry` 统一管理 proposal/evidence 的稳定 ID、校验和工厂；内建 provider 将各自配置规则与构造细节放在 adapter 层。`server_config` 只验证已注册配置，服务入口不再导入具体 provider，也不再读取旧的 OmniParser 环境开关。

### P9：收敛公开入口

目标：默认调用面只表达任务生命周期，诊断能力不污染日常协议。

- 使用一个纯映射函数完成 `Domain Result + TaskState → Public Response`。
- 默认入口仅保留 `run`、`status`、`confirm`、`reset` 和 `describe`。
- `observe`、`propose`、`decide`、`execute`、`evaluate`、`trace` 移入独立诊断入口。
- 默认响应不返回 Guard、Attribution、原始对象或内部 pipeline stage。

验收：所有公开状态只有 `running`、`needs-confirmation`、`retrying`、`completed`、`failed`；诊断测试与默认协议测试相互独立。

完成：纯 `reduce_public_response` 以领域结果和 TaskState 生成公开响应；`gui_run` 仅接受生命周期操作，逐阶段执行与 trace 移入 `gui_diagnostic`。公开响应不再由 `diagnostic` 参数展开内部对象。

### P10：拆分领域模型文件

目标：让代码布局反映既有责任边界，降低阅读和修改成本。

- transaction：Proposal、Decision、Receipt 与 Guard。
- task：Contract、TaskState 与限制。
- desktop：Snapshot、Geometry 与 capabilities。
- evidence：Evidence、Assertion 与排除原因。
- audit：LedgerEvent 与 Attribution。
- 对外从 `core` 提供稳定导出，禁止形成循环依赖。

验收：仅移动定义和更新导入，不改变 schema、序列化结果或运行行为；完整测试通过。

完成：协议基础、desktop、transaction、task、evidence、audit 和 model context 各自独立；`core.models` 仅作兼容聚合，核心基础设施已改为按领域直接导入。重导出身份测试保证现有导入仍指向相同类。

### P11：同步公开调用文档

目标：手工验收和 README 不再指导调用已从 `gui_run` 移出的内部阶段。

- 将 `observe`、`propose`、`decide`、`execute`、`evaluate`、`trace` 示例改为 `gui_diagnostic`。
- 删除 `diagnostic=true` 的旧用法；以诊断入口展开对象和 Attribution。
- 对照 `describe` 返回的公开与诊断 operation 列表，增加文档示例检查。

验收：README、手工验收指南和 MCP 工具签名一致；按文档复制的命令不会被 `gui_run` 拒绝。

完成：README 的默认生命周期示例使用 `gui_run`，逐阶段示例使用 `gui_diagnostic`；手工验收指南同步工具范围、trace 调用和 schema revision。

### P12：封闭配置启动路径

目标：非秘密运行配置只能来自 `--config` JSON，不能由 CLI 的旧环境变量分支绕过启动校验。

- 删除 `SSE_HOST`、`MCP_TRANSPORT` 和 `CUA_*` 驱动的无配置启动路径。
- 无 `--config` 时给出明确错误与迁移提示；密钥和桌面会话资源环境变量仍可使用。
- 验证启动日志、effective config 与 provider registry 校验总会执行。

验收：所有生产启动都读取 JSON 配置；旧环境变量只能产生忽略告警，不能改变 transport、provider 或证据配置。

完成：CLI 无 `--config` 时提供迁移错误；已删除 `SSE_HOST`/`MCP_TRANSPORT` 启动分支。JSON 路径始终执行 provider registry 校验、effective config 日志和旧变量忽略告警。

### P13：收尾边界与可读性

目标：完成 P10 后的依赖迁移，并明确未接入扩展的维护状态。

- 将 Core 内仍从 `core.models` 聚合导入的模块改为按 desktop、transaction、task、evidence、audit 直接导入。
- 保留 `core.models` 仅作为外部兼容入口，并以测试保证重导出身份稳定。
- 明确 `langchain/agent_graph.py` 的使用边界；未接入主链则移至可选扩展或补上集成测试。

验收：Core 内部不再依赖聚合导入；LangChain 扩展要么有可执行入口与测试，要么不位于默认运行包。

完成：Core 实现模块全部按领域直接导入，`core.models`/`core` 只保留外部兼容导出；边界测试防止回退。LangChain 代码明确为独立客户端扩展，不被服务入口导入或启动，并提供单独的使用说明。

### P14：恢复领域模型可读性

目标：代码精简来自职责收敛，而不是压缩排版；领域对象应能被人类快速扫描和评审。

- 将 `transaction.py`、`task.py`、`evidence.py`、`audit_models.py` 和 `context.py` 恢复为一字段一行、枚举一值一行的常规格式。
- 展开单行条件与异常，不修改类名、字段顺序、默认值、类型和序列化结果。
- 保持现有领域文件边界，不重新合并 `models.py`，也不新增抽象层。

验收：格式化前后的 dataclass 字段、枚举值和 `to_primitive` 输出完全一致；完整测试通过。

完成：五个领域模型文件已恢复为常规 Python 排版；未改变类名、字段顺序、默认值、枚举值、校验和模块边界。

### P15：由桌面后端提供平台工具

目标：快捷键目录、快捷键执行和应用启动由所选桌面后端提供；`mcp_autogui_main.py` 不理解具体桌面环境的能力与事务。

- `CompositorAdapter` 只负责窗口、坐标、层叠和命中等 canonical observation，不承担快捷键或应用启动。
- `DesktopBackend` 作为环境能力 bundle，提供 capability catalog、application launcher 和对应的 `ActionExecutor` 路由。
- Treeland + Deepin 的快捷键与 `dde-am` 启动事务迁入 `adapters/backends/treeland_deepin` 范围；其他后端可提供完全不同的实现。
- MCP 层只调用当前 backend 暴露的稳定能力，不包含 Deepin capability、热键或应用 ID 的判断逻辑。
- 保留 `gui_run` 与 `gui_diagnostic` 在 Facade；不增加新的公开工具或状态。
- 不为了减少文件行数拆出零散 helper；每个桌面后端的工具作为完整扩展单元组装。

验收：替换 desktop backend 时，快捷键目录、应用目录和执行方式随 backend 一起替换，无需修改 MCP 入口或 Core；现有六个 MCP 工具及行为不变。

完成：`DesktopBackend` 通过 `create_tools` 提供平台工具对象；Treeland/Deepin 后端拥有快捷键、应用目录、`dde-am` 启动事务与验证逻辑。MCP 入口只保留四个稳定桌面工具的薄转发。

### P16：统一公开状态来源

目标：公开状态只由 TaskState 和是否发生协议错误决定，不在 Core、Facade 和 response reducer 中重复翻译。

- `CoreOrchestrator.run` 返回事实引用、TaskState 和恢复建议，不再返回手写的任务状态字符串。
- `PolicyDecision`、`ExecutionReceipt` 和 `AssertionResult` 保持各自领域状态，不新增 ResultStatus 或第二套枚举。
- `reduce_public_response` 是 `gui_run` 公开状态的唯一映射位置；诊断入口继续展示原始领域状态。
- 删除 Facade 中重复的 Decision/Receipt → public status 条件分支。

验收：源码中公开五态的映射只有一处；`gui_run` 只输出 `running`、`needs-confirmation`、`retrying`、`completed`、`failed`，诊断对象 schema 不变。

完成：`CoreOrchestrator.run` 只返回最终 `TaskState`、迭代事实与恢复建议；非 delivered 的执行结果先写入失败任务状态。Facade 的公开路径不再解释 Decision/Receipt，`reduce_public_response` 只依据 `TaskState` 或协议错误生成公开状态。

### P17：压缩实现文档

目标：实现指南成为当前维护入口，而不是 P0–P16 的过程日志。

- 保留架构链接、当前状态、运行命令、代码落点、扩展规则和真实环境待办。
- 已完成阶段压缩为简短交付表；删除重复的目标、步骤、验收和“完成”段落。
- 详细历史由 Git 提交记录承担，不另建第二份变更日志。
- 明确保留 P5 真实 Treeland 回归为发布前未完成项。

验收：维护者能在短文档中回答“如何运行、代码在哪里、如何扩展、还缺什么”；内容不重复架构文档和手工验收指南。

## 回归待办

1. 由 `AssertionResult.excluded_evidence` 统一表达过期、失效和冲突。
2. 完成真实 Treeland 回归矩阵，并记录环境阻塞与失败归因。
