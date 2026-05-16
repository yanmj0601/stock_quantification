# EvoQuant

EvoQuant 是一个多市场通用的量化研究平台 MVP。第一版聚焦研究自进化闭环：数据集版本、策略候选生成、回测、稳健性验证、策略注册、模拟盘、风控门禁和后台管理台。

## 范围

- 支持多市场抽象：`US`、`CN`、`CRYPTO`。
- 支持策略状态流转：`research`、`candidate`、`paper`、`small-live-ready`、`production-ready`、`retired`。
- 支持模拟盘账户、订单、成交、持仓和净值。
- v1 禁用真实实盘下单。

## 本地运行

```bash
uv run --extra dev pytest -q
uv run evoquant --host 127.0.0.1 --port 8000
```

后台前端在 `frontend/`，完成后使用：

```bash
cd frontend
npm install
npm run dev
```
