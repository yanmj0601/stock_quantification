# EvoQuant MVP v1 运行说明

## 启动后端

```bash
uv run evoquant --host 127.0.0.1 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/healthz
```

期望返回：

```json
{"status":"ok"}
```

## 启动后台

```bash
cd frontend
npm install
npm run dev
```

默认地址：

- 后台管理台：`http://127.0.0.1:5173/`
- 后端 API：`http://127.0.0.1:8000/`

## 端到端验收

建议按这个顺序验证：

1. 在 Evolution 页面选择市场和参数空间，点击 Generate。
2. 对生成的候选点击 Register，候选会进入 Strategies 页面成为 `research` 策略。
3. 在 Strategies 页面点击 Paper，把策略提升到模拟盘状态。
4. 在 Backtests 页面选择策略并运行样例回测，收益、Sharpe、最大回撤等指标会写回策略。
5. 在 Paper Trading 页面创建模拟账户，提交纸面订单，查看订单、成交和持仓。
6. 在 Risk 页面切换 `paper-only` 或 `paused`，确认真实实盘始终禁用。
7. 在 Audit Log 页面查看策略、风险和模拟盘动作的审计事件。

## 验证命令

```bash
uv run --extra dev pytest -q
cd frontend
npm run typecheck
npm run build
```

当前前端构建可能出现 Vite chunk-size warning，这是包体积提示，不代表构建失败。

## 安全边界

- v1 禁用真实实盘交易。
- API 没有真实券商或交易所下单端点。
- `live_enabled=true` 会被 `/api/risk` 拒绝。
- 只有模拟盘会产生本地模拟订单、成交和持仓。
- 策略进入模拟盘需要人工状态变更。
- 策略创建、状态变更、回测指标、模拟盘订单和风险模式变更都会写入审计事件。

## 当前限制

- 数据健康 API 目前只暴露数据集数量，详细新鲜度、缺失 K 线、重复 K 线和异常价格报告仍是后续扩展点。
- 回测队列是同步 MVP 流程，还没有异步任务调度器。
- 模拟盘成交使用本地撮合简化模型，不连接真实行情源。
- 管理台没有 RBAC，多用户权限和审批流留到后续版本。
