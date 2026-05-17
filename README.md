# EvoQuant

EvoQuant 是一个多市场通用的量化研究平台 MVP。第一版聚焦研究自进化闭环：数据集版本、策略候选生成、回测、稳健性验证、策略注册、模拟盘、风控门禁和后台管理台。

## 范围

- 支持多市场抽象：`US`、`CN`、`CRYPTO`。
- 支持策略状态流转：`research`、`candidate`、`paper`、`small-live-ready`、`production-ready`、`retired`。
- 支持模拟盘账户、订单、成交、持仓和净值。
- v1 禁用真实实盘下单。

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

默认前端地址是 `http://127.0.0.1:5173/`，默认 API 地址是 `http://127.0.0.1:8000/`。

## 后台管理台

管理台覆盖以下页面：

- Overview：策略、模拟账户、审计和全局风险摘要。
- Strategies：策略指标、状态、进入模拟盘、暂停和淘汰操作。
- Backtests：对已注册策略提交样例回测并记录收益、Sharpe、回撤等指标。
- Evolution：配置模板、市场和参数空间，生成候选并人工登记为研究策略。
- Paper Trading：创建模拟账户、提交纸面订单、查看订单、成交和持仓。
- Data Health：展示数据集摘要和真实空状态。
- Risk：切换 `research-only`、`paper-only`、`paused`，真实实盘始终禁用。
- Audit Log：查看策略、风险和模拟盘动作的审计事件。

## 安全边界

- v1 没有真实券商或交易所下单通道。
- API 会拒绝开启 `live_enabled`。
- 模拟盘订单只写入本地 SQLite，并可自动生成模拟成交。
- 策略进入模拟盘需要显式人工状态变更，所有变更写入审计日志。

更多运行和验收说明见 `docs/evoquant_mvp_v1_operating_notes.md`。
