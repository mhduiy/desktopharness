# AutoUI MCP v2.1 实现指南

本文是代码维护入口，只说明当前实现、运行方式、扩展位置和发布前待办。

- 架构哲学、模块关系与通信协议：[`treeland-autoui-mcp-v2-design.md`](treeland-autoui-mcp-v2-design.md)
- 真实桌面验收步骤：[`manual-test-guide.md`](manual-test-guide.md)
- 对外使用示例：[`../README.md`](../README.md)

## 当前状态

v2.1 的既有事实链与扩展边界已经收敛。P20 已移除 Core 中按任务原始动作白名单产生的机械拒绝，
并把特殊部署需要的动作限制移至可选策略扩展。发布前剩余 P5 真实 Treeland/Deepin 验收；环境未验收
不等于模型、策略或执行失败，必须单独记录。

| 范围 | 状态 | 结果 |
| --- | --- | --- |
| P0–P4、P6–P19 | 完成 | 核心事实链、扩展边界、公开协议、命名和文档已经收敛 |
| P20 | 完成 | 原始动作不再作为 TaskContract 硬授权；限制能力移至可选 PolicyProvider |
| P5 | 待完成 | 真实 Treeland/Deepin 环境回归 |

已实现的稳定边界：

- 事实链固定为 `Proposal → PolicyDecision → ExecutionReceipt → Evidence → AssertionResult → TaskState`。
- 未调用执行器时没有 `ExecutionReceipt`；执行送达不等于业务断言通过。
- `TaskState` 是公开任务状态的唯一来源，协议错误单独归并为 `failed`。
- `gui_run` 只暴露任务生命周期；逐阶段事实和 Attribution 只通过 `gui_diagnostic` 查看。
- Core 不依赖具体合成器、模型、证据实现或桌面平台工具。

## P20：机械授权边界收敛（已实现）

### 目标行为

- 用户给出目标后，模型可在执行器支持的 canonical actions 中选择实现方式；TaskContract 没有预先列出
  某个动作，不得单独导致拒绝。
- Core 继续验证 Proposal 协议、`done` 位置、坐标空间、桌面边界和 ProposalGuard。
- 语义策略、确认、高风险拒绝和断言验证保持不变；P20 不等于关闭策略或绕过 Guard。
- 需要只读、鼠标专用或多租户隔离的部署，通过可选 `PolicyProvider` 检查 Proposal action sequence，
  输出独立策略标签，再由现有 policy profile 决定 allow、confirm 或 deny。

### 实现

1. `core/action_gate.py` 的资格检查只保留 `done` 顺序、coordinate space 和 desktop bounds 校验；
   已删除 `action.type not in contract.permissions.actions` 拒绝分支。
2. `TaskPermissions.actions` 与输入字段 `permissions.actions` 在当前协议版本中保留解析和序列化兼容，
   但 Core 不再把它作为授权事实。不得引入 `explicit_user_authorization`、全局 allow 开关或新的授权布尔值。
3. `MECHANICAL_PERMISSION_DENIED` 暂时保留为可读取的历史 ReasonCode，避免破坏持久审计；新决策路径不再产生它。
4. 若执行器不支持某个动作，由 backend/executor 返回稳定的 capability/execution 错误；不要重新借用
   TaskContract 动作列表模拟运行时能力。
5. `action_restriction` 是独立 `PolicyProvider` 与 JSON 配置项。Provider 只提供确定性的
   `action_restricted` 策略标签，不执行动作；默认配置不启用。

### 兼容与迁移

- 现有调用方可以继续发送缺失、空或部分 `permissions.actions`；这些取值不再改变 Core 决策。
- `gui_run`、`gui_diagnostic`、TaskState、Proposal、Decision、Receipt 与审计结构保持不变。
- 不在 P20 删除字段、ReasonCode 或重写历史审计；删除属于后续协议大版本工作。
- schema revision 已从 `2.1-p5` 递增到 `2.1-p6`。

### 自动回归

- 同一 Proposal 在 `permissions.actions` 缺失、空、部分和完整四种 contract 下，不得出现
  `MECHANICAL_PERMISSION_DENIED`，其语义策略与 Guard 结果应一致。
- `done` 无须出现在任何调用方动作集合中，且只能位于动作序列末尾。
- 坐标空间错误、桌面越界、目标变化和遮挡仍分别产生现有稳定结果，并且零输入注入。
- 默认高风险语义策略仍能 confirm/deny；模型 `claimed_intent` 仍不能降低独立证据支持的策略级别。
- 可选限制 PolicyProvider 单独覆盖：默认未启用时不影响自动化；启用时只拒绝其配置的 action types。

真实桌面手工回归保留“终端运行 `htop`、关闭终端”：模型无论选择键盘、快捷键还是点击，都不能因原始动作
未枚举而失败；执行送达与任务完成仍分别由 Receipt 和 Assertion 证明。该项属于 P5，不冒充自动测试结果。

### 完成条件

自动回归已覆盖默认路径和限制 provider；README 示例不再要求调用方预测原始动作；手工验收矩阵已加入
V2-16 与 V2-17。实现没有用“默认填入所有 actions”替代删除硬拒绝。

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
- schema revision 为 `2.1-p6`；序列结构、语义合并、Guard、短路执行、原子回执和多 tool-call 解析均有
  自动回归覆盖。
- **新证据源**：实现 `ports/evidence.py`，声明标准 fact path，并覆盖 unknown、conflict 和过期证据。

扩展不得增加第二套公开状态、错误码 registry 或平台条件分支。未知 provider、重复注册和无效配置必须
在启动时失败。

## P5 真实环境回归

代码边界收敛后，发布前仍需完成真实 Treeland/Deepin 回归：

1. 安装服务证书到系统信任库，通过 HTTPS 调用实际 MCP 入口。
2. 运行 `autoui-smoke`，确认 tree、provider 和 `gui_run(describe)` 均可用。
3. 按 `manual-test-guide.md` 执行 V2-01～V2-17，并保存必要 trace 与 artifact 引用。
4. 将证书、代理、桌面会话或外部服务问题记为环境阻塞；领域失败按 ReasonCode 与 Attribution 归因。

## 文档维护

- 架构文档只描述稳定设计，不记录实施进度。
- 本文只维护当前实现、阅读入口、扩展方式和发布前待办。
- 逐提交改动、排障过程和中间方案由 Git 历史承担。
