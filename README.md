# EvoQuant

EvoQuant 是一个多市场通用的量化研究平台 MVP。当前 v2 聚焦“真实日线数据 -> 横截面动量信号 -> 信号回测 -> 纸面订单草稿 -> 人工审批模拟盘”的闭环，为后续策略自进化、分钟级别数据和更完整的交易执行层打基础。

## 范围

- 支持多市场抽象：`US`、`CN`、`CRYPTO`，当前真实信号链路优先覆盖美股和 A 股。
- 支持免费数据源适配：美股 `yfinance`、A 股 `AKShare`，并保留 CSV Provider 作为本地和测试兜底。
- 支持缓存日线行情、同步任务记录、覆盖率检查和手动定时任务配置。
- 支持 `cross_sectional_momentum` 横截面动量策略：
  - 评分 = `0.50 * 120日动量排名分 + 0.25 * 20日动量排名分 - 0.15 * 波动率惩罚 - 0.10 * 最大回撤惩罚`
  - 买入 Top 20，按分数加权，单票上限 8%
  - 持有到跌出 Top 50，或触发风险/止损/数据问题后卖出
- 支持信号扫描快照、买/持/卖信号、中文名称展示字段、按市场 Top20 和 Global Top40 查看。
- 支持从信号生成纸面订单草稿，再人工 approve/cancel/submit。
- 支持策略状态流转：`research`、`candidate`、`paper`、`small-live-ready`、`production-ready`、`retired`。
- 支持模拟盘账户、订单、成交、持仓和净值。
- 禁用真实实盘下单。

## 本地运行

安装依赖后运行完整测试：

```bash
uv run --extra dev pytest -q
```

启动后端 API：

```bash
uv run evoquant --host 127.0.0.1 --port 8000
```

启动后台管理台：

```bash
cd frontend
npm install
npm run dev
```

默认前端地址是 `http://127.0.0.1:5173/`，默认 API 地址是 `http://127.0.0.1:8000/`。如果要使用真实数据源依赖：

```bash
uv sync --extra dev --extra market-data
```

## 后台管理台

管理台覆盖以下页面：

- Overview：策略、模拟账户、审计和全局风险摘要。
- Strategies：策略指标、状态、进入模拟盘、暂停和淘汰操作。
- Signals：运行美股/A股信号扫描，查看买/持/卖、评分、权重和风险标记，并生成纸面订单草稿。
- Backtests：对已注册策略提交样例回测，也可用已缓存日线跑真实信号回测。
- Evolution：配置模板、市场和参数空间，生成候选并人工登记为研究策略。
- Paper Trading：创建模拟账户、提交纸面订单、审批信号草稿、查看订单、成交和持仓。
- Data Health：展示数据集摘要、行情同步任务和手动定时任务配置。
- Risk：切换 `research-only`、`paper-only`、`paused`，真实实盘始终禁用。
- Audit Log：查看策略、风险和模拟盘动作的审计事件。

## 安全边界

- 当前没有真实券商或交易所下单通道。
- API 会拒绝开启 `live_enabled`。
- 模拟盘订单和信号草稿只写入本地 SQLite，并可自动生成模拟成交。
- 策略进入模拟盘需要显式人工状态变更，所有变更写入审计日志。
- Signals 页面展示的是研究信号，不构成投资建议。

更多运行和验收说明见 `docs/evoquant_mvp_v2_operating_notes.md`。
