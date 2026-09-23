# AutoUI MCP v2.1 架构

本文定义稳定架构，不记录实施进度、测试步骤或故障样例。

- 实施状态：[`treeland-autoui-mcp-v2-implementation.md`](treeland-autoui-mcp-v2-implementation.md)
- 手工验收：[`manual-test-guide.md`](manual-test-guide.md)

## 核心思想

### 小核心、大扩展、克制通信

这是本架构的首要哲学。

- **小核心**：Core 只保留跨桌面都成立的事务语义、策略裁决、状态归约和领域对象；不理解具体窗口系统、模型、输入库或应用启动方式。
- **大扩展**：合成器、桌面能力、模型、执行方式和证据来源全部通过 ports/adapters 扩展；新增能力应增加 adapter，而不是给 Core 增加平台分支。
- **克制通信**：模块之间只传递完成本层职责所需的最小事实。默认调用方只看 TaskState 和引用；原始树、截图、模型输出、Guard 与 Attribution 只在显式诊断时展开。
- **意图优先**：用户目标和可验证约束是任务边界；点击、键盘、快捷键等原始动作是模型在运行时选择的实现细节，不能仅因未被任务预先枚举而拒绝。

这不是“模型直接操控桌面”的架构，而是把一次 GUI 操作拆成一串不能互相冒充的事实：

```text
模型说“应该做什么”       → Proposal
控制器说“能否做”         → PolicyDecision
执行器说“实际做了什么”   → ExecutionReceipt
观察系统说“看到了什么”   → EvidenceRecord
断言系统说“任务是否完成” → AssertionResult / TaskState
```

每一层只回答一个问题，并由对应责任方产生唯一权威对象。这样可以同时做到：模型不拥有执行权、
执行成功不被误判为业务成功、证据不足不被伪装成失败、诊断信息不污染日常调用。

### 能力、环境与策略三条边界

Core 必须区分三种不同问题，不能用一个动作白名单同时回答：

| 边界 | 回答的问题 | 权威来源 | 典型结果 |
| --- | --- | --- | --- |
| 执行能力 | 当前 executor/backend 是否实现该 canonical action | runtime/backend descriptor 与执行事实 | unsupported / failed |
| 环境 Guard | Proposal 仍指向同一窗口、坐标与桌面状态吗 | Snapshot、hit-test、ProposalGuard | stale / invalid |
| 语义策略 | Proposal 是否仍在部署策略允许的意图范围内 | PolicyProvider、独立语义证据、policy profile | allow / confirm / deny |

`TaskContract.permissions.actions` 不属于上述任何权威事实：它既不能证明执行器能力，也不能证明用户意图，
还要求调用方提前预测模型会选择点击、快捷键还是键盘输入。Core 因此不得仅以动作未出现在该集合中为由
产生 `MECHANICAL_PERMISSION_DENIED`。该字段在兼容期只作为调用方声明或诊断元数据保留，之后可在协议大版本中删除。

需要原始动作隔离的多租户、只读 worker 或不可信代理部署，应通过可选 `PolicyProvider` 检查 Proposal，
产生独立策略标签并由 policy profile 裁决。默认单用户桌面路径不加载这类限制。这样限制能力可以扩展，
但不会扩大 Core，也不会让模型对同一目标选择不同操作方式时随机失败。

### 模型提案序列

一次模型输出对应一个 Proposal，可包含一个或多个有序原子动作；模型的输出粒度不应成为
协议限制。审计、策略、确认与归因均以 Proposal 为单位，原子动作的 Guard 和 Receipt 是该
Proposal 的执行明细。序列全部完成后统一观察与评估；任一 Guard 拒绝、环境失效或执行失败
立即停止剩余动作。该模型同时兼容单个 `drag` 与“移动、按下、移动、松开”等 CUA 输出。

## 目标

将 GUI 自动化表示为可验证、可审计的事实链。Core 可跨合成器和桌面后端复用；模型只能提案，
策略只能裁决，执行器只能执行，证据只能证明。

## 边界

```text
MCP facade → Core → ports → adapters / desktop backend
```

Core 不依赖 Treeland、Deepin、Qwen、PyAutoGUI、`dde-am` 或 MCP transport。adapter 把外部数据转换为
canonical objects；desktop backend 在单一 executor 内路由输入、快捷键和应用启动。

## 核心通信协议

Core 模块之间只交换下列领域对象与 port 返回值；具体字段填充、缓存和序列化细节以源码为准。

```text
                         +------------------+
                         |   MCP facade     |
                         | run/status/      |
                         | confirm/reset    |
                         +--------+---------+
                                  |
                                  v
+----------------+       +------------------+       +------------------+
| CompositorPort |------>| CoreOrchestrator |<------| ProposalProvider |
| Snapshot/Frame |       | policy + state   |       | ActionProposal   |
+----------------+       +---+----------+---+       +------------------+
                            |          |
             PolicyDecision |          | ActionProposal
                            v          v
                     +-----------+  +----------------+
                     | ActionGate|  | ActionExecutor |
                     +-----------+  +-------+--------+
                                           |
                                           v
                                    ExecutionReceipt
                                           |
                     +---------------------+---------------------+
                     v                                           v
              EvidenceProvider                         AssertionEvaluator
              EvidenceRecord                           AssertionResult → TaskState
```

| 边界 | 输入 | 输出 | 禁止事项 |
| --- | --- | --- | --- |
| ProposalProvider | `ModelContext` | 一个 `ActionProposal` | 执行、裁决、修改状态 |
| ActionGate | Proposal、Contract、Snapshot | `PolicyDecision` | 注入输入 |
| ActionExecutor | 已允许 Proposal | `ExecutionReceipt` | 证明业务成功 |
| EvidenceProvider | assertion、Snapshot | `EvidenceRecord` | 判定任务完成 |
| AssertionEvaluator | assertion、evidence | `AssertionResult` | 调用 adapter 或 executor |

## 流程图

```text
调用方             Core / Policy                 Executor             Evidence / Assertion
  |                    |                              |                       |
  | task + goal        |                              |                       |
  +------------------->| observe → Proposal          |                       |
  |                    |                              |                       |
  |                    | Decision(deny/invalid)      |                       |
  |<-------------------+------------------------------+                       |
  | TaskState=failed   |                              |                       |
  |                    |                              |                       |
  |                    | Decision(confirm)           |                       |
  |<-------------------+------------------------------+                       |
  | TaskState=needs-confirmation                      |                       |
  |                    |                              |                       |
  | confirm            | guard recheck               |                       |
  +------------------->|-- stale --> TaskState=running|                       |
  |                    |-- allow -------------------->| execute               |
  |                    |                              | Receipt(failed)       |
  |<-------------------+------------------------------+                       |
  | TaskState=failed   |                              |                       |
  |                    |                              | Receipt(delivered)    |
  |                    |<-----------------------------+                       |
  |                    |----------------------------------------------->| collect
  |                    |<-----------------------------------------------+ AssertionResult
  |<-------------------+ TaskState=completed / running / retrying        |
```

## 不变量

1. `PolicyDecision` 与 `ExecutionReceipt` 是不同事实。
2. 未调用 `ActionExecutor` 时不存在 Receipt 或 `execution.completed`。
3. `ExecutionReceipt.delivered` 不等于业务成功；只有 Assertion 可证明完成。
4. `ActionProposal.claimed_intent` 是声明，不是策略真值。
5. 业务完成条件只来自 `TaskContract.assertions`；Proposal 不包含预期业务结果。
6. 未知、冲突或过期证据不得产生通过结论。
7. Attribution 是审计诊断旁路，不属于默认通信。
8. `event_type` 是审计事件类别的权威表达。
9. canonical action 的选择是 Proposal 实现细节；TaskContract 未枚举某个原始动作本身不是拒绝理由。
10. `done` 是无桌面副作用的生命周期标记，不参与动作授权或执行能力判断。

## 领域模型

| 对象 | 责任 |
| --- | --- |
| `TaskContract` | 目标、策略选择、可验证断言、预算；兼容期可携带非权威动作声明 |
| `CanonicalSnapshot` / `FrameReference` | 标准化桌面观察 |
| `ActionProposal` | 非空、有序的 canonical action 序列、来源 snapshot、可选 `claimed_intent`；`action` 是首动作兼容视图 |
| `PolicyDecision` | `allow`、`deny`、`confirm`、`stale`、`invalid` |
| `ExecutionReceipt` | Proposal 级 `delivered`、`failed`、`unknown`，以及逐原子动作回执 |
| `EvidenceRecord` | provider 对 subject 的事实材料 |
| `AssertionResult` | 对 TaskContract assertion 的结论及排除材料 |
| `TaskState` | `running`、`needs-confirmation`、`retrying`、`completed`、`failed` |

领域错误使用统一 `ReasonCode`。诊断 Attribution 可补充 stage、owner 和 event kind，但不得另建错误码体系。

## Proposal 事务与动作序列

```text
observe → proposal → decision
                    ├─ deny / confirm / stale / invalid → TaskState
                    └─ allow → preflight all guards
                                  ├─ stale → TaskState（零注入）
                                  └─ action[0..n] → aggregate Receipt
                                                         → observe → evidence → assertion → TaskState
```

一次模型输出是一个 Proposal，无论模型用一个高层动作，还是用移动、按下、移动、释放等多个动作表达。
策略、确认和审计按 Proposal 裁决一次；每个原子动作仍保留自己的 Guard 和回执。执行前统一重检全部
Guard，任一失效则产生新的 `PolicyDecision(status=stale)`，且不注入任何动作。执行阶段严格按序，
任一步失败就停止剩余动作，并产生唯一的 Proposal 级 `ExecutionReceipt(status=failed)`，其中保留已尝试
动作的明细。动作间不重新调用模型，也不重新观察桌面；只有序列结束后才统一观察并评估断言。
Qwen pending proposal 由 Decision 或 Proposal 级 Receipt 终结，不能伪造 Receipt。

## 公开协议

普通调用通过 `gui_run`，只使用：

```text
run → status → confirm → reset
```

`gui_diagnostic` 承担 `observe`、`propose`、`decide`、`execute`、`evaluate` 和 `trace`，仅用于诊断或测试。
`gui_run` 的任务状态只由 `TaskState` 约简；请求或协议错误可直接归并为 `failed`。响应只包含公开状态、
`task_state`、必要引用和恢复信息，不返回 Guard、Attribution 或原始领域对象。
`gui_diagnostic(describe)` 可展开 schema revision、能力和 provider。

## 配置与审计

JSON 是非秘密运行配置唯一来源；环境变量仅用于密钥和桌面会话资源。启动必须输出脱敏 effective config，
并警告被忽略的旧行为变量。HTTPS 使用系统信任库。

对外审计称为 `AuditTrail`。ObjectStore 保存对象/artifact，EventLedger 保存顺序与因果关系；二者是同一
审计记录的内部实现，不是竞争的事实源。旧 CSV 归档必须可读，新 CSV 不写重复 `epistemic_type`。

## 扩展规则

- 新合成器实现 `CompositorPort`，具体实现使用 adapter 命名，只输出 canonical desktop facts。
- 新桌面能力在 backend 内校验并路由到 `ActionExecutor`，不得开放任意 shell。
- 新原始动作限制通过 `PolicyProvider` 和 policy profile 扩展，不得在 Core 增加每任务动作白名单分支。
- 新 Evidence Provider 声明可提供的标准 fact path；AssertionEvaluator 决定适用、排除和冲突。
- 新模型实现 `ProposalProvider`，返回一个可含有序动作序列的 Proposal，不能执行或放宽策略。
