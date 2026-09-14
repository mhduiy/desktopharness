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
| 事务协调与策略 | `core/orchestrator.py`、`core/action_gate.py` |
| 默认 MCP 通信 | `facade.py`、`mcp_autogui_main.py` |
| 执行边界 | `ports/executor.py`、`adapters/executor/`、`adapters/backends/` |
| 观察与证据 | `ports/compositor.py`、`ports/evidence.py`、`adapters/evidence/` |
| 审计 | `core/audit.py`、`core/ledger.py`、`audit_cli.py` |
| 配置 | `server_config.py`、`config/mcp-autoui.json` |

## 配置规则

所有非秘密运行配置来自 JSON。环境变量只用于模型密钥和桌面会话资源；JSON 模式下出现旧行为变量时
服务会警告其被忽略。HTTPS 使用系统信任库；不要在仓库配置中关闭证书验证。

## 扩展规则

- **新合成器**：新增 `CompositorAdapter` 与 fixture 契约测试，不修改 Core。
- **新桌面能力**：放入 desktop backend，并通过 `ActionExecutor` 路由；禁止任意 shell。
- **新模型**：实现 `ProposalProvider`，只产生单个 Proposal。
- **新证据来源**：实现 `EvidenceProvider`，声明标准 fact path，并添加 unknown/conflict 测试。

## 待办

1. 由 `AssertionResult.excluded_evidence` 统一表达过期、失效和冲突。
2. 完成真实 Treeland 回归矩阵，并记录环境阻塞与失败归因。
