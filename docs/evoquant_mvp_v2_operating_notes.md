# EvoQuant MVP v2 运行说明

## 当前策略

当前可运行的真实信号策略是 `cross_sectional_momentum` 横截面动量策略，面向美股和 A 股日线。

- 用 120 日动量作为主趋势，20 日动量作为短期确认。
- 用波动率和最大回撤扣分，避免只追强但风险过高的标的。
- 每个市场买入 Top 20，按分数加权，单票目标权重上限 8%。
- 持仓跌出 Top 50，或触发风险过滤、止损、停牌、涨跌停等约束后产生卖出或阻断信号。
- A 股采用 100 股整数手、T+1、涨停不买、跌停不假设可卖的规则。

这仍是研究信号，不是投资建议，也不会发真实实盘订单。

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

如果用当前会话的临时端口，也可以运行：

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 57818
```

## 数据源

真实数据适配层已经接入三个 Provider：

- `YahooFinanceProvider`：用于美股 S&P 500 成分和日线行情。
- `AkshareProvider`：用于沪深 300 成分和 A 股日线行情。
- `CsvMarketDataProvider`：用于本地 CSV、测试和离线兜底。

安装真实数据依赖：

```bash
uv sync --extra dev --extra market-data
```

当前 API 的 `/api/data-sync/{market}` 已接入 provider 同步：

- `POST /api/data-sync/US` 会同步 S&P 500 instrument master，并拉取近 5 年美股日线。
- `POST /api/data-sync/CN` 会同步沪深 300 instrument master，并拉取近 5 年 A 股日线。
- 如果本地没有安装 `market-data` 依赖，或外部免费源字段变化、限流、不可用，API 会返回 400 和明确错误信息。

## 端到端验收

建议按这个顺序验证：

1. 启动后端和前端。
2. 在 Paper Trading 页面创建一个 paper account。
3. 在 Data Health 页面点击 Sync US 或 Sync CN，或用 CSV Provider 写入足够的 `market_bars`。
4. 在 Signals 页面点击 Run Scan。
5. 查看 Global Top40 或 US/CN Top20，确认能看到 buy/hold/sell、评分、目标权重、风险标记和原因。
6. 对 buy 或 sell 信号点击 Draft，生成纸面订单草稿。
7. 在 Paper Trading 页面对草稿执行 Approve、Submit 或 Cancel。
8. 在 Backtests 页面运行 Signal Backtest，查看收益、Sharpe、最大回撤、换手等指标。
9. 在 Data Health 页面查看同步任务和市场定时任务配置。
10. 在 Audit Log 页面确认扫描、草稿、订单和风险动作有审计记录。

## 验证命令

```bash
uv run --extra dev pytest -q
cd frontend
npm run typecheck
npm run build
```

当前前端构建可能出现 Vite chunk-size warning。这是 Recharts 等依赖导致的包体积提示，不代表构建失败；后续可以通过页面级 lazy import 拆包。

## 安全边界

- 没有真实券商或交易所下单端点。
- `live_enabled=true` 会被 `/api/risk` 拒绝。
- 信号只会生成本地纸面订单草稿。
- 草稿需要人工审批后才会进入模拟盘订单。
- 模拟盘成交使用本地简化成交模型，不连接真实交易所。
- 数据覆盖率低于 70% 的市场扫描会失败，避免用过少数据给出误导性信号。

## 当前限制和下一步

- 后台 Sync 已接 provider，但仍是同步请求；下一步应改为后台异步任务，避免外部源慢响应时占住 HTTP 请求。
- `SignalScanner` 已保留中文名称字段，但需要在真实 instrument master 中补全美股中文名映射。
- 回测仍是同步执行，后续应改为异步任务和结果表。
- 模拟盘成交费用和滑点已有市场规则雏形，但还需要更贴近真实撮合。
- 策略进化层下一步应从“候选参数生成”升级为“用真实回测结果做参数搜索、稳健性筛选和纸面表现衰减监控”。
