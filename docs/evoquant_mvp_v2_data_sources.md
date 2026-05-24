# EvoQuant MVP v2 数据源说明

## 免费数据源

- 美股使用 `yfinance`。
- A 股使用 `AKShare`。
- 本地和测试使用 `CsvMarketDataProvider`。
- 免费数据源可能延迟、缺失、限流或字段变化。
- 系统只用于研究和模拟盘，不构成投资建议。

## 默认市场范围

- 美股默认同步 S&P 500。
- A 股默认同步沪深 300。
- 默认行情窗口是近 5 年日线。
- 当前信号策略是 `cross_sectional_momentum`。
- 输出是 `buy`、`hold`、`sell` 研究信号。

## 本地缓存

- 外部数据先同步到 SQLite。
- Signals 扫描默认读取本地缓存。
- 每次同步记录 provider、覆盖率、失败 symbol 和质量报告。
- 覆盖率低于 70% 的市场不输出信号。
- 重复同步会用 `(symbol, market, session)` 做 upsert，不重复插入同一根 K 线。

## 中文名称

- 美股和 A 股中文名通过 instrument master 维护。
- 美股中文名优先使用本地 CSV 覆盖；当前 provider 缺省会用 symbol 占位。
- A 股中文名优先使用 AKShare 返回值，必要时由本地 CSV 覆盖。
- Signals 页面会优先展示 `name_zh`，没有中文名时回退到英文名或 symbol。

## 同步接口

```bash
curl -X POST http://127.0.0.1:8000/api/data-sync/US
curl -X POST http://127.0.0.1:8000/api/data-sync/CN
curl -X POST http://127.0.0.1:8000/api/data-sync/US/instruments
curl -X POST http://127.0.0.1:8000/api/data-sync/US/bars/jobs
curl -X POST http://127.0.0.1:8000/api/data-sync/bar-jobs/<job_id>/retry
curl http://127.0.0.1:8000/api/data-sync/jobs
curl http://127.0.0.1:8000/api/data-sync/bar-jobs
```

返回的 sync job 包含：

- `market`
- `provider`
- `status`
- `total_symbols`
- `success_symbols`
- `failed_symbols`
- `coverage`
- `failures`

## 依赖安装

```bash
uv sync --extra dev --extra market-data
```

如果没有安装 `market-data` extra，API 会返回 400，并说明缺少 `yfinance`、`AKShare` 或 `pandas`。

## 质量和风险提示

- 免费源不是交易级行情，不适合作为真实下单依据。
- A 股涨跌停、停牌、复权字段依赖 AKShare 当前返回格式，字段变化时需要更新 adapter。
- 美股成交额用 `close * volume` 估算，因为 Yahoo 日线默认不直接给 amount。
- 数据覆盖率、异常价格、停牌、涨跌停会被记录，但更严格的缺失交易日检查还需要交易日历模块。
- 首次全量 K 线同步建议通过 `/bars/jobs` 分批执行；手动全量同步只用于初始化或补数据。
- `partial` 的批量任务可以通过 `/api/data-sync/bar-jobs/<job_id>/retry` 只重试失败标的。
- 自动增量只在已有历史 K 线的市场上运行，避免系统启动时误拉五年全量数据。
