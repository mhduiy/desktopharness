# AutoUI MCP v2/v2.1 实现与扩展指南

本文记录 `treeland-autoui-mcp-v2-design.md` 对应的已实现 v2 基线，以及尚未实现的
v2.1 克制化收敛路线。凡标为“v2.1 计划”的内容都不能表述为当前能力。

## MCP 服务配置

统一的服务端配置位于 [`config/mcp-autoui.json`](../config/mcp-autoui.json)，可复制模板见
[`config/mcp-autoui.example.json`](../config/mcp-autoui.example.json)。启动命令为
`uv run treeland-autogui-mcp --config config/mcp-autoui.json`；配置覆盖 transport、
Qwen-CUA proposal provider、Evidence Provider、审计策略和 `desktop_backend.kind`。
JSON 是推荐入口，`CUA_*`、`GUI_*` 和 transport 环境变量仅保留给旧部署兼容。加载器目前
直接把已校验的配置传入 proposal provider、evidence provider、审计组件和 desktop bundle；
JSON 模式不再以环境变量作为这些组件的配置桥接。环境变量只保留给敏感凭据、桌面会话
（如 display/socket）及未使用 JSON 的旧部署。敏感凭据（如模型 API key）仍应由受控
secret mechanism 提供，不应提交到 JSON 文件。

## 已实现边界

- `core/` 包含 canonical 协议对象、Action Gate、ProposalGuard、语义策略、Assertion Evaluator、确定性 Task State Reducer、append-only Ledger、Context Builder 和薄 Orchestrator；可选审计模式使用私有 JSON 对象目录、原始二进制 artifact 目录和 `ledger.csv` 持久化协议对象与事件。
- `ports/` 定义 compositor、frame、proposal、policy、executor、application launcher、platform capability 和 evidence 契约。
- `adapters/` 包含 Treeland 与严格 canonical-JSON compositor adapter、Qwen-CUA proposal adapter、PyAutoGUI frame/input adapter、Treeland/Deepin desktop capability adapter，以及 compositor-window、AT-SPI 和 OmniParser evidence provider。Treeland/Deepin desktop backend 可选提供基于 `dde-am` 的应用启动能力；该 launcher 不属于 compositor adapter。
- OmniParser 默认关闭；启用后仅作为只读 `omniparser-grounding` provider。它把截图解析为概率性 `control.*`/`document.text` EvidenceRecord，并以名称/角色的语义 locator 唯一匹配控件；原始响应保存在 artifact 引用中。它不注册 `omniparser_*` 工具，也不执行输入或把视觉 bbox 推断为任意 compositor 窗口内的可操作目标。
- AT-SPI 默认关闭；启用且会话可用时以同一语义 locator 提供独立的可访问性控件 evidence。provider 不可用时只产生缺失证据，不会伪造否定结论。
- `desktop_backend` 通过 registry 选择 desktop bundle；Treeland/Deepin bundle 提供 compositor、executor、frame provider、窗口手势、桌面能力目录、应用目录和 launcher。主装配只将这些 port 交给 Orchestrator。
- `facade.py` 实现紧凑的 `gui_run` 操作和诊断对象查询。
- `gui_run(operation="run")` 执行有界的自动闭环；每轮仍是一个独立的
  `observe -> propose -> decide -> execute -> evaluate` 事务，遇到确认、拒绝、
  重复无进展或任务终态即停止并返回恢复建议；证据不足时切换到
  `verification-focused` 投影，仍受任务步数预算限制。

Core 不 import Treeland、Deepin、Qwen、PyAutoGUI 或 `dde-am`。当前 Orchestrator 仍有
`application.launch` 与 ApplicationLauncher 的专用分支，这是 v2.1 P2 要删除的已知边界。
合成器原始树与截图保存在对象存储中；正常协议对象只携带引用。

## v2.1 实现路线

v2.1 的目标不是增加更多抽象，而是让每个事实只有一个权威表达，让普通调用方只理解
任务状态。实施必须遵循以下约束：

- 每个阶段都可独立提交、独立回归和安全回退；
- 先建立新不变量，再删除旧兼容字段；
- 迁移期可以读取旧对象和旧审计归档，但新代码不得继续生成已废弃表达；
- 不为迁移再创造新的持久领域对象；内部函数可以返回现有对象的 union；
- 设计文档中的 v2.1 目标是规范，本节是落地顺序，当前代码仍以“已实现边界”为准。

### P0：锁定迁移边界与有效配置

这是开始结构调整前的必做项，优先解决已经在真实验收中暴露的配置不可见问题。

1. 为当前 v2 对象、envelope、Ledger CSV 和审计归档增加兼容夹具，固定旧数据的读取行为。
2. 增加统一 `ReasonCode` 注册表；先让 PolicyDecision、ExecutionReceipt、
   AssertionResult 与 Attribution 引用同一 code，再删除重复 code。
3. 服务启动时输出脱敏后的 effective config，包括 transport、模型地址、模型名、TLS、
   proxy/trust-env、provider 和 audit 状态，但绝不输出 API key。
4. JSON 继续负责所有非秘密运行配置，环境变量只提供 secret 和桌面会话资源。检测到会被
   JSON 忽略的旧 `CUA_*`、`GUI_*` 或 transport 行为变量时明确报错或警告，不能静默清除。
5. `describe` 返回对象 schema revision 和已启用能力，使客户端能判断新旧结构；不得仅靠
   server package version 猜测协议行为。

主要修改位置：`server_config.py`、入口装配、`core/models.py`、`core/ledger.py`、审计读取器
和对应配置/持久化测试。

完成门槛：旧审计夹具仍可读取；有效配置可从启动日志和 `describe` 脱敏确认；所有新对象
只使用统一 ReasonCode。

### P1：清理未执行路径

这是 v2.1 最重要的语义修改，必须先于 facade 状态重命名。

1. 从 `ExecutionStatus` 删除 `rejected`，保留 `delivered`、`failed` 和 `unknown`。
2. Action Gate 返回 `deny`、`confirm` 或 `invalid` 时，不调用 ActionExecutor，不创建
   ExecutionReceipt，也不写 `execution.completed` 事件。
3. Guard 重检失败时追加 `PolicyDecision(status=stale)`，复用原 proposal、最新 snapshot
   和统一 ReasonCode；不得制造零时长的 rejected Receipt。
4. Core 的执行入口返回 `PolicyDecision | ExecutionReceipt`：未执行时返回最终 Decision，
   真正调用执行器后才返回 Receipt，不增加 `ExecutionResult` 一类重复包装对象。
5. Qwen pending proposal 在 deny、confirm、stale 和 invalid 后按 Decision 清理；只有
   delivered Receipt 才把动作提交到成功历史。不能为了适配模型 session 再伪造 Receipt。
6. Attribution 仍可写入 AuditTrail，但只作为 Decision/Receipt 的诊断旁路，不成为正常
   执行返回值的一部分。

主要修改位置：`core/models.py`、`core/orchestrator.py`、`core/action_gate.py`、
`ports/proposal.py`、Qwen-CUA adapter/service、`facade.py` 和核心/facade/Qwen session 测试。

完成门槛：确认、拒绝、Guard stale 和能力缺失均证明 executor 调用次数为零，且不存在
ExecutionReceipt；执行器失败仍产生唯一 failed Receipt。

### P2：统一执行边界

在 P1 稳定后，Core 从多个执行端口收缩到单一 `ActionExecutor`。

1. `ActionExecutor.execute(ActionProposal) -> ExecutionReceipt` 成为 Core 唯一执行 port。
2. desktop backend 内部按标准 ActionType 路由到 PyAutoGUI、平台快捷键或 `dde-am`；Core
   不再识别应用启动和平台动作的具体执行方式。
3. 应用 ID 校验、快捷键 capability ID 校验和禁止任意命令仍保留在 backend 安全边界，
   不能因统一 executor 而退化成通用 shell 执行。
4. 删除 Core 的 `application_launcher` 特殊依赖和 ActionType 分支；旧 launcher 可暂时作为
   backend 内部 helper，但不再是跨 Core port。
5. `desktop_shortcut_invoke` 与 `desktop_application_launch` 继续生成 canonical Proposal，
   不得直接调用具体执行 helper。

主要修改位置：`ports/executor.py`、`desktop_backend.py`、Treeland/Deepin backend、
`core/orchestrator.py`、MCP 工具装配和桌面能力测试。

完成门槛：Core 只注入一个 executor；输入、快捷键和应用启动使用同一执行事务测试；源码
检查确认 Core 不包含 `dde-am`、PyAutoGUI 或 launcher 分支。

### P3：收紧 Proposal 与 facade

完成执行语义后再改变公共通信，避免同时调试领域状态和 API 映射。

1. `ActionProposal.semantic_intent` 迁移为 `claimed_intent`，明确它只是声明；解析器在一个
   兼容周期内接受旧字段，但新对象只生成新字段。
2. 从核心 Proposal 删除 `expected_effect`。模型预期保存到 `debug_ref`，业务完成条件只来自
   TaskContract assertions。
3. 普通调用只推荐 `run`、`status`、`confirm` 和 `reset`。`observe`、`propose`、`decide`、
   `execute`、`evaluate`、`trace` 保留为诊断/测试操作。
4. TaskState 收缩为 `running`、`needs-confirmation`、`retrying`、`completed`、`failed`；若
   `retrying` 没有独立消费者，则使用 `running` 加剩余预算，不保留该枚举。
5. 默认 envelope 只返回操作状态、TaskState 和必要引用，不返回 `attribution_refs`；
   Attribution、Guard、SemanticResolution 和完整对象只在 diagnostic/trace 中展开。
6. `pending` 仅表示显式操作还有后续工作，不得成为新的 TaskState 或 receipt-like 对象。

主要修改位置：`core/models.py`、`core/task_state.py`、`facade.py`、Qwen adapter、MCP 工具文档
和协议契约测试。

完成门槛：普通自动任务只需四个操作；默认响应不泄漏内部 pipeline；旧 Proposal 可读，
新 Proposal 不再生成 `semantic_intent` 或 `expected_effect`。

### P4：精简 Evidence 与 AuditTrail

该阶段风险高于字段重命名，只有在 P1–P3 稳定且真实 evidence 用例充分后实施。

1. 将 EvidenceRecord 的公共结构收敛为 source、subject、facts、quality、captured_at 和可选
   artifact_ref；先统计现有字段消费者，再删除重叠的有效性布尔值。
2. 过期、失效和冲突材料统一由 AssertionResult 的 excluded evidence 说明，不允许 provider
   用 `false` 冒充未知或失效。
3. 不引入独立 VerifiedFact 对象。TaskState 只保存已通过 assertion ID 或 AssertionResult
   引用；事实内容继续由 EvidenceRecord 提供。
4. 对外统一称为 `AuditTrail`；ObjectStore 与 EventLedger 可以继续作为内部存储实现，但
   不能被描述成两个权威事实源。
5. 当 `event_type` 已能唯一确定对象类型时，新事件不再写等价 `epistemic_type`。审计读取器
   继续接受旧 CSV 列，并在内存中归一化。
6. Context Builder 只保留一个默认投影和一个 recovery 投影；其他策略在 benchmark 证明有
   独立收益前降为实验选项，不扩大普通配置面。

主要修改位置：Evidence/Assertion/TaskState 模型、providers、`core/ledger.py`、Audit CLI、
Context Builder 和持久化兼容测试。

完成门槛：旧归档可浏览和导出；新 Ledger 不写重复类型；unknown/conflict 行为不变；默认
ModelContext 明显缩小且不降低既有任务正确率。

### P5：收束文档和验收入口

1. 主设计文档只保留核心对象、状态机、公开 API 和不可破坏的不变量，目标 300～500 行。
2. Attribution 枚举、故障案例和 benchmark 规则迁入附录；端口与 adapter 细节留在本文；
   操作步骤只留在 `manual-test-guide.md`。
3. 提供一个只读 smoke 命令或测试脚本，自动完成 `describe`、Treeland tree、provider 和
   effective config 预检，避免人工拼接 MCP JSON-RPC。
4. 根据新对象和状态重写手工验收预期，明确环境阻塞、策略拒绝和 executor 失败的统计分母。

完成门槛：同一规则只在一处规范定义；其他文档使用链接引用；新维护者可以从本文确定
“当前已实现、下一步修改、如何验证”而无需通读完整设计历史。

### 提交与验证顺序

每个优先级至少拆成一个独立提交，不把协议语义、执行重构、配置迁移和文档整理混在同一
提交。推荐顺序：

```text
P0a 旧对象/归档兼容夹具
P0b ReasonCode 与 effective config
P1  未执行路径不产生 Receipt
P2  单一 ActionExecutor
P3a 最小 Proposal 与 TaskState
P3b compact facade
P4a Evidence 与 Ledger 兼容迁移
P4b Context Builder 收缩
P5  文档与验收入口
```

每个提交先运行对应单元/契约测试，再运行完整测试；P1、P2、P3 完成后分别执行真实
Treeland 的拒绝、应用启动、确认和完成语义验收。任何阶段出现证据不足都保持旧实现，
不得为了完成迁移而放宽安全策略。

## 尚未完成的实现与验收

v2 事务内核、默认 Qwen + Treeland 路径、配置直注入、AT-SPI 与 OmniParser 的只读迁移均已
实现；v2.1 路线尚未实现。以下是验收或由用户暂缓的后续范围，不应被表述为已经完成：

1. **独立业务证据的真实环境验收**：AT-SPI 和 OmniParser provider 已实现；仍需在真实桌面
   测量其控件/文本 evidence 的准确性、歧义处理、延迟与归因。DOM、应用 API 等更强的业务
   evidence 仅在目标应用需要时新增，不应把它们混入 compositor-window provider。
2. **跨合成器实证（当前暂缓）**：CanonicalJsonAdapter 已覆盖协议夹具；仍需至少一个非 Treeland
   合成器的真实 adapter 与同等契约/桌面测试，才能证明通用性。应用装配通过显式
   backend registry 创建后端，JSON 的 `desktop_backend.kind` 只能选择已注册项；新增后端
   必须注册其 factory，不能让 Core 根据平台名分支。
3. **持久审计的真实环境验收**：设置 JSON `audit.directory` 后，运行时将小型、结构化协议对象
   以及截图、原始树和模型输出等 artifact 写入私有 JSON 文件，并把 Ledger 追加到
   `ledger.csv`；二进制 artifact 以原始 `.bin` 文件保存于独立 `artifacts/` 目录，JSON
   仅保存相对路径、长度和 SHA-256。`reset` 只清运行态并追加 `task.reset`，不会删除
   既有 Ledger。保留期和容量清理以一个 JSON 对象及其全部 artifact 为原子单元；无法
   JSON 化的值保存说明性 stub，而不会无记录消失。目录拒绝 group/other 可访问权限，默认
   保留 7 天、总计 16 GiB（由 `audit.retention_days` 与 `audit.max_gib` 配置）。仍需按部署
   路径验证权限、容量和保留策略；该审计副本用于重启后复核，不能恢复执行中的任务。

启用审计后，可用与合成器无关的 `autoui-audit` 浏览存档。直接传目录会进入终端 TUI：

```text
autoui-audit /private/path/audit
```

TUI 支持任务列表 → 事件时间线 → 对象详情的逐层浏览；`↑↓` 选择、`Enter` 进入、`b`
返回、`q` 退出。顶栏显示任务、事件和完整归档容量（CSV、JSON 和 artifact）；对象详情页可展开 JSON，二进制 artifact
可按 `e` 后输入的路径导出，并拒绝覆盖已有文件。启动时会显示只读归档扫描和因果链索引
动画；任意按键可跳过。任务列表页按 `z` 可将 `ledger.csv` 与所有对象打包为 `.tar.gz`；
将该文件复制到其他机器后，直接执行 `autoui-audit copied-audit.tar.gz` 即可在临时只读目录
中打开同一份审计记录。压缩包含 `manifest.json`，打开前会校验每个成员的大小和 SHA-256，
可发现缺件或意外损坏；它不是签名或防篡改证据，存在对抗性威胁时必须在部署层增加签名或
受控导出流程。
4. **集中真实 Treeland 回归验收**：按
   `manual-test-guide.md` 的基础事务、桌面适配器与 5×10 重复矩阵执行，产出可复核的
   成功率、拒绝率、延迟和 attribution 报告。当前单元测试不能替代此项。

当前 v2 基线可以继续集中真实 Treeland 验收；v2.1 实现按 P0–P5 独立推进，不能把设计目标
计为已完成能力。独立业务 evidence 的真实环境质量验证与第二合成器由用户暂缓，保留本节
作为后续恢复实施时的边界。每项实现完成后仍必须运行相应单元和契约测试；集中验收用于
验证这些能力在真实桌面中的联合作用。

## 事务不变量

v2 路径对单个动作执行：

```text
observe -> propose -> decide -> guard recheck -> execute
        -> observe -> collect evidence -> evaluate -> reduce state
```

- `based_on_snapshot` 只记录来源。Action Gate 从该 Snapshot 推导 ProposalGuard，并只在最新 Snapshot 上重检动作实际依赖的条件。
- Proposal 的 semantic intent 是模型或主控 claim。只有独立 adapter/provider tag 才作为策略真值；没有独立证据时采用 `unknown -> confirm`，除非 TaskContract 显式覆盖。
- `ExecutionReceipt.delivered`、Evidence、AssertionResult 和 TaskState 是不同对象。只有 Reducer 能产生 `completed`。
- Evidence Provider 只能输出注册过的 fact path。缺失、过期、仅模型声明或冲突的 evidence 不能使断言通过。
- Ledger Event 只保存对象/artifact 引用和因果 event ID，不嵌入原始树、截图或完整模型输出。
- Context Builder 的 `compact`、`visual-heavy`、`recovery`、`verification-focused`
  和 `planning-reset` 是不同预算与事件投影，不是同一 history 的别名。恢复投影
  会附带最近 primary attribution；模型历史不会被当作 verified fact。
- 对外信封返回 attribution 引用和稳定恢复动作；环境变化、安全拒绝和证据不足
  与组件执行错误分开记录。

## 新增合成器

在 `adapters/compositor/` 中实现 `ports.compositor.CompositorAdapter`，并返回 `CanonicalSnapshot`。只映射 `CanonicalWindowFact` 定义的字段；其余原生字段丢弃，或将完整原始 payload 保存到 `raw_artifact_ref`。Adapter 必须声明真实 stacking model；无法提供 hit test、identity、visibility 或 cursor 时不能伪装为否定事实。

已经输出 canonical JSON 的 compositor bridge 可以直接使用 `CanonicalJsonAdapter`。它会有意忽略未知输入字段。

## 新增桌面后端能力

一个桌面后端是合成器观察能力及其同一桌面会话的可选能力的组合，而不是让 Core 认识
某个桌面系统。以当前 Treeland/Deepin 后端为例，`TreelandAdapter` 除了实现
`CompositorAdapter`，还暴露可选的 `application_launcher`；其实现使用 `dde-am`，但
`dde-am` 并不是 Core API，也不应被当作所有合成器共有的命令。

在另一平台继续开发时：

1. 实现该平台的 `CompositorAdapter`，并通过 Canonical Model 暴露可证明的窗口、坐标和 stacking 能力。
2. 若桌面会话有安全、稳定的应用启动 API，在该后端提供 `ApplicationLauncher`；没有就传入 `None`，由事务返回 `CAPABILITY_UNAVAILABLE`，不要降级为任意 shell 命令。
3. 若有经过审查的平台操作，在该后端提供 `PlatformCapabilityProvider`；其能力 ID 和策略语义不得依赖任意 D-Bus 参数或快捷键串。
4. 在 `desktop_backend.py` 的 backend registry 注册 factory，并将后端提供的 ports 交给 Orchestrator。把新的 ID 写入 JSON 的 `desktop_backend.kind`；未知 ID 会在 MCP 启动前被拒绝。

无论上述可选能力是否存在，所有启动和平台动作仍必须生成 Proposal，并经过 Policy、Guard、Receipt 与 Assertion 事务。

## 新增 Evidence 或执行后端

Evidence Provider 声明 `core.facts.STANDARD_FACT_PATHS` 的子集，并只返回 `EvidenceRecord`，不能判断任务完成。只有当新 fact 具有稳定语义且有核心消费者时，才扩展注册表。

Input/Application backend 只返回 `ExecutionReceipt`。窗口变化或业务结果不能写入回执，必须由独立 Evidence Provider 采集。

## 工具面

旧 `qwen_cua_predict`、`qwen_cua_execute`、`qwen_cua_reset`、`qwen_cua_status`
兼容工具已删除。唯一对外工具是 `gui_run`（全部协议操作）以及
`desktop_*` 工具；`desktop_shortcut_invoke` 与 `desktop_application_launch`
内部同样走 canonical Proposal -> PolicyDecision -> Guard -> ExecutionReceipt。
Qwen 后端只实现 `ProposalProvider`：每轮必须产出一个 canonical action，原始模型
输出仅以 `debug_ref` 保存。需要自动执行时由 `gui_run(operation="run")` 驱动；需要
人工审批或诊断时使用 `observe`、`propose`、`decide`、`execute`、`evaluate`、`trace`
等显式操作。
