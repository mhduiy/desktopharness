# AutoUI MCP v2.2 架构

本文定义 v2.2 的目标架构。v2.1 仍是当前代码实现；具体迁移范围和完成状态见 [`treeland-autoui-mcp-v2-implementation.md`](treeland-autoui-mcp-v2-implementation.md)。

## 核心思想：简化、紧凑、功能完整

延续“小核心、大扩展、克制通信”：Core 负责通用执行编排和状态，平台、模型、输入和证据实现通过 ports/adapters 接入；默认响应只传递必要事实。减少重复判断、包装和历史分支，保留已有操作能力及结果验证。

本次目标是整体架构简化，安全审批只是其中一部分。保留实际能力和正确性要求，不承诺保留承载它们的现有类、对象链或接口。每一层都应回答“删除后会失去什么实际能力”；只有透传、重复表达或假设需求的层应删除或合并。文件数和代码行数仅供参考，不能代替职责、状态和调用路径的减少。

范围包括执行链、运行态、记录与诊断、协议兼容、配置和依赖。不会为简化新增两种运行模式、通用策略框架或另一套事务框架。平台、模型、执行器和证据边界因现有功能需要而保留；其他抽象须有当前调用方和独立责任支撑。

v2.2 保留桌面自动化必须具备的事实链，却不再把每一个模型动作送进默认的权限审查。单用户桌面的调用者已经通过提交任务表达了执行意图；系统应负责**正确执行、可验证完成、可追溯诊断**，而不要求调用者预测动作类型或为普通输入反复确认。

默认主链只有五步：

```text
任务目标 → 观察 → 提案 → 校验并执行 → 验证结果
```

```text
MCP facade → Orchestrator → ProposalProvider
                  │                 │
                  │                 ▼
                  ├→ ProposalValidator → ActionExecutor
                  │                         │
                  └← AssertionEvaluator ← EvidenceProvider
```

每一层只保留一个责任：

| 层 | 唯一责任 | 不能做什么 |
| --- | --- | --- |
| ProposalProvider | 根据当前观察提出一个有序动作提案 | 执行或宣布完成 |
| ProposalValidator | 确认动作格式、能力、坐标和目标仍有效 | 判断用户意图是否“允许” |
| ActionExecutor | 注入一个已校验的动作并给出回执 | 判断任务是否完成 |
| Evidence / Assertion | 采集事实并判断任务断言 | 执行、授权或改变策略 |
| Orchestrator | 编排有界循环和归约任务状态 | 重复实现各层规则 |

## 连接边界

当前 v2.1 没有 MCP 连接鉴权，示例也监听 `0.0.0.0`；因此不能称为“保留现有连接鉴权”。v2.2 的默认 `transport.host` 必须为 `127.0.0.1` 或 `::1`。若需要从本机以外访问，只允许两种明确部署：

1. 服务仍绑定 loopback，由同机、受 TLS 和鉴权保护的可信反向代理对外提供连接；代理是唯一外部入口。
2. 服务绑定非 loopback 时，必须配置并启用正式的 bearer-token 鉴权；无 token、错误 token 和缺少 token 的请求在到达 facade 前拒绝。

目标配置使用 `transport.auth.mode`：`loopback`（默认）、`trusted-proxy` 或 `bearer-token`。`trusted-proxy` 仍要求 upstream 为 loopback；`bearer-token` 要求 `token_env` 指向非空密钥环境变量。非 loopback host 配合 `loopback` 或 `trusted-proxy` 是配置错误。`describe` 只显示模式和绑定地址，绝不显示 token 或环境变量值。模型端点的访问控制是独立问题，不替代 MCP 入站鉴权。

## 默认路径：直通但不盲信

默认部署没有策略 profile、语义标签、动作白名单或确认步骤。`TaskContract` 的业务输入只表达目标、完成断言和预算，仍保留任务标识等关联信息；不再要求 `permissions.actions`、`permissions.semantic_intents`、`policy_profile` 或 `policy_overrides`。

执行前仍必须通过以下不可省略的技术校验。这些是避免错误输入的正确性条件，不是权限审查：

1. Proposal 包含一个或多个有序、已注册的 canonical action，字段和坐标空间必须有效。
2. 坐标必须落在当前桌面边界内；指针动作必须命中当前可交互目标。
3. 键盘动作必须有可用的活动窗口；执行器必须声明支持该动作。
4. 从提案到注入前重新观察一次；目标、命中点、活动窗口或坐标空间已变化则丢弃本步、重新观察和提案，绝不注入。
5. 执行器只接受 canonical action，不能开放任意 shell、Python 或动态表达式。
6. 达到 `max_steps` / `max_retries` 后停止，执行送达后才采集证据并评估断言。

这使失败语义清晰：环境变化可在预算内重新观察和提案；格式错误、能力缺失不原样重试；执行器错误是执行失败；断言不成立是任务尚未完成。它们都不能伪装为“权限不足”。校验按动作实际依赖执行，不因无关窗口变化而否定整个桌面快照。

## 保留的核心事实

v2.2 保留下列事实及其关联语义；不要求每种事实都拥有独立服务、仓库、事件或持久化对象：

```text
CanonicalSnapshot → ActionProposal → ExecutionReceipt → EvidenceRecord → AssertionResult → TaskState
```

- `CanonicalSnapshot` 是一次桌面观察的标准表示。
- `ActionProposal` 保存非空有序 actions 和来源 snapshot；单动作也使用同一序列表示，删除首动作兼容视图。
- `ExecutionReceipt` 只陈述输入是否实际送达、失败原因和执行引用，不宣称业务完成。
- `EvidenceRecord` 与 `AssertionResult` 是完成状态的唯一依据。
- `TaskState` 使用 `running`、`retrying`、`completed`、`delivered-unverified`、`failed`；删除 `needs-confirmation` 和确认恢复分支。

保留多动作提案、顺序执行和部分执行回执；这些支撑模型连续输入及故障恢复。执行前统一检查环境依赖，任一检查失效则零注入；执行中失败立即停止剩余动作，记录已尝试动作，不能自动重放整个序列。完整送达后统一观察和评估。依赖前一步界面变化的动作应分到下一轮观察后提案。`drag` 等复合输入继续由 executor 实现。

## ProposalValidator 契约

v2.1 的 `ActionGate` 同时承担协议校验、Guard 构造、语义分类、权限匹配、策略裁决和确认，职责过多且会造成普通步骤被拒绝。v2.2 将其拆减为 `ProposalValidator`，契约固定为：

```text
prepare(snapshot, proposal) → PreparedProposal | ValidationFailure
recheck(prepared, latest_snapshot) → PreparedProposal | ValidationFailure

ValidationFailure = { reason_code, retryable }
```

`PreparedProposal` 是仅在本次执行临界区存活的内部值，不是公开协议对象，也不需要独立持久化。它包含 canonical actions、来源 snapshot、每个动作的已校验参数，以及实际依赖的桌面条件：坐标空间和边界、指针命中目标 identity、键盘焦点窗口、执行器支持能力及静态部署动作限制。`prepare` 校验 action type、必填字段、字段类型与范围、文本/按键/拖拽等动作参数、坐标转换结果、能力声明和依赖目标；不推断语义或用户意图。

`recheck` 在执行锁内以最新观察重查 PreparedProposal 的实际依赖。任何依赖变化返回 retryable failure 且零注入；无关窗口或桌面变化不应使其失败。成功值立即交给 executor。不会生成 `PolicyDecision`、`SemanticResolution` 或一组 `ProposalGuard`。

结构错误、未知动作、无效参数、配置错误和执行器能力缺失返回 `retryable=false`；目标消失、遮挡、焦点变化或坐标空间变化返回 `retryable=true`。ReasonCode 是公开诊断的稳定来源，具体内部校验字段不是新协议。

## 结果、断言与状态转换

`completed` 始终表示所有必需断言通过。为了支持无预期窗口的应用启动、快捷键和单纯输入，任务可以没有 assertions；这种任务在至少一个 action sequence 完整送达后，由 provider 返回 `done`，进入终态 `delivered-unverified`。它表示输入已送达、没有完成证明，不能用作断言成功或下游业务成功。

空断言任务在输入尚未送达时收到 `done`，或执行只部分送达、结果不确定时，不得进入 `delivered-unverified`；按相应失败语义结束。带 assertions 的任务即使收到 `done` 也必须评估断言，不能因 `done` 或 receipt 而 completed。`TaskState` 因此使用 `running`、`retrying`、`completed`、`delivered-unverified`、`failed`；删除 `needs-confirmation`。

状态归约只接受如下失败分类，所有路径均记录稳定 ReasonCode：

| 事件 | 状态与预算 |
| --- | --- |
| `ValidationFailure(retryable=false)` | `failed`；不消耗 `max_retries`，零注入。 |
| retryable validation failure / stale recheck | `retrying`，消耗一次 `max_retries`；预算耗尽后 `failed`，零注入。 |
| executor failure、部分送达或送达结果不确定 | `failed`；不自动重放整条序列，也不消耗重试预算。 |
| 必需断言明确失败且 `recoverable=true` | `retrying`，消耗一次 `max_retries`；预算耗尽后 `failed`。 |
| 必需断言明确失败且 `recoverable=false` | `failed`；不消耗重试预算。 |
| 断言 unknown/conflict 或尚未收集到适用证据 | `running`，不消耗重试预算；后续轮次可重新观察和提案。 |
| 所有必需断言通过 | `completed`。 |

每个被接受、准备执行的 proposal sequence 消耗一个 `max_steps`；失败的 prepare/recheck 不消耗 steps。达到 steps 上限但尚未进入 `completed` 或 `delivered-unverified` 时进入 `failed`。`done` 不注入输入也不消耗 steps。

## 部署限制只保留已有实际能力

现有 `action_restriction` 支持部署者限制原始动作，保留这项能力，但收敛为可选的静态部署配置 `deployment.denied_actions`，由 validator 检查并返回稳定的限制原因。未配置或空列表表示不限制动作；未知或重复动作在启动时报错。任务不能覆盖部署限制，describe 显示实际配置。

v2.2 删除通用 `PolicyProvider`、profile、语义分类、多 provider 决策合并、`confirm` 接口及确认状态机。旧 `policy_providers.action_restriction` 配置改为直接的部署动作限制字段，同步修改示例；不增加自动迁移或旧配置回退。

远程 MCP transport 继续保留，并遵守上述连接边界。通用审批扩展留待具体需求出现后单独设计，不作为本次交付条件。

## 运行态与记录收敛

- 一个运行态所有者负责任务、当前提案、实际回执、断言结果、去重及模型反馈终结标记。`TaskState` 只在一处更新；诊断和持久化不能成为第二个状态来源。
- 编排直接更新运行态，再按配置记录事件；执行与 status 不通过审计存储查找必需对象。删除只为同步运行态和审计而存在的透传包装，不为每种事实建立 manager/repository。
- 保留执行锁，以及“未执行、部分执行、完整送达”的区别。去重与模型反馈标记的生命周期随任务管理；进程重启不隐式恢复或重放输入。
- 原因码、阶段、提案标识和实际执行明细足以表达常规失败。完整归因图按需诊断，不再为一次失败生成多份控制流对象。
- `TaskRepository`、`TransactionRecorder`、`AuditRecorder`、`ObjectStore`、`EventLedger` 按以上职责收敛；具体合并以调用关系为准，不预设必须保留或必须合成一个大文件。

## 公开接口与诊断

普通调用仍是紧凑生命周期接口：

```text
gui_run: run → status → reset
```

`gui_run` 另保留 `describe`，删除 `confirm`。诊断工具是否注册由配置决定：关闭时 MCP 不注册 `gui_diagnostic`；开启时它可以查看 observation、proposal、validation、receipt 和 assertion，但不承担普通工作流。诊断执行复用同一校验执行入口，不能建立第二条执行链。

目标配置统一使用 `recording`：

```json
"recording": {
  "audit": false,
  "diagnostic": false,
  "directory": ".autoui-audit",
  "retention_days": 7,
  "max_gib": 16
}
```

`audit` 和 `diagnostic` 默认均为 `false`；`diagnostic=true` 要求 `audit=true`，否则配置错误。两者关闭时只保留当前进程内运行态，响应不得返回 trace/object 引用；`audit=true`、`diagnostic=false` 时持久化最小任务、提案、回执、最终断言和关联事件，但不注册 `gui_diagnostic`，也不保存截图、模型原文或完整桌面树；两者为 true 时才注册诊断工具并持久化详细诊断材料。持久化引用可在保留期内由 audit CLI 查询；内存引用仅在 task reset 或进程退出前有效，reset 后所有该任务引用失效。默认响应只返回任务状态、必要的下一步信息及可用时的持久化诊断引用。

## v2.2 迁移边界

| 移除或降级 | 保留或替换 |
| --- | --- |
| `TaskPermissions` 的 actions / semantic intents | goal、assertions、limits |
| 默认 semantic policy profile、per-task override 与通用 PolicyProvider | 默认无限制；可选静态部署动作限制 |
| `SemanticTag`、`SemanticResolution`、模型 intent 审查 | 仅保留模型调试信息，不参与控制流 |
| `PolicyDecision`、`needs-confirmation` 和 confirm | 内部校验值与直接失败原因 |
| 单动作兼容视图、重复 Guard 持久化对象 | 统一 actions 序列、内部校验数据、含实际执行明细的 Proposal 回执 |
| 全量默认审计对象落盘 | 可选、最小事件审计；诊断按需展开 |
| 重复状态索引、事务与审计间透传包装 | 一个运行态所有者、一个状态更新入口、按需记录 |
| 未定义的远程监听与审计/诊断开关 | 显式 transport auth 与 recording 配置契约 |

## 快速迭代：直接删除兼容代码

项目尚未商用，v2.2 允许破坏性变更，不设置弃用期，不维护旧协议适配层。

- 直接删除已废弃字段、接口别名、旧配置回退、兼容后端及仅为历史格式保留的解析分支；同步更新仓库内调用方、配置、示例与测试。
- 删除 `permissions`、任务级 `policy_profile` / `policy_overrides` 和仅用于旧路径的 ReasonCode。旧请求按当前 schema 返回清晰的字段错误，不静默忽略或补齐旧行为。
- 仅保留当前审计格式的读写；不要求新运行时读取历史格式，也不删除已有审计文件。需要查看旧记录时使用对应 Git 版本。
- 更新协议版本并说明破坏性变化；旧实现通过 Git 历史查阅，无须为其保留运行时分支。
- 多动作提案、桌面能力和 provider 扩展有实际功能价值，不能仅因复杂或较早实现就归为兼容代码。

## 验收条件

1. 当前任务格式不需要 permissions 或策略覆盖即可运行；已删除字段有明确输入错误，仓库内调用方全部使用当前格式。
2. 输入文本、快捷键、点击和拖拽不会因语义分类、未知标签或调用方未列举动作而进入确认或拒绝。
3. 坐标越界、目标消失、遮挡、焦点变化和能力缺失仍阻止输入注入，并以明确技术原因重试或失败。
4. `ExecutionReceipt.delivered` 仍不等于任务成功；只有断言通过才 completed，空断言任务只能成为 delivered-unverified。
5. 显式配置的部署动作限制有效，未配置时普通动作无需审批；无通用策略与确认状态机。
6. 多动作提案、拖拽、失败短路及部分执行事实保留；诊断关闭时不额外持久化逐动作 Guard 或语义审查对象。
7. 关闭审计仍可运行、去重、查询状态和 reset；模型收到与实际执行一致的终结反馈。
8. 平台、模型、输入与证据能力无退化；没有为了减少文件而把平台实现并入 Core，也没有新增透传层补回已删除的复杂度。
9. 默认仅 loopback 监听；所有非 loopback 部署有 bearer-token 或 loopback upstream 的可信反向代理配置。三种 recording 模式的工具注册、持久化范围和引用生命周期符合本文契约。
