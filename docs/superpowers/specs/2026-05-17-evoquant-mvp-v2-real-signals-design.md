# EvoQuant MVP v2 真实信号闭环设计

## 目标

EvoQuant MVP v2 要从“策略研究控制台”升级为“真实数据驱动的多市场信号研究系统”。系统应能拉取并缓存美股和 A 股日线数据，运行可解释的横截面动量策略，输出 `buy / hold / sell` 策略信号，保存扫描快照，并把候选信号转成模拟盘订单草稿。

v2 仍然不是实盘交易系统。系统不接真实券商或交易所，不发真实订单，所有订单都停留在模拟盘草稿或纸面交易层。`buy / hold / sell` 是策略信号，不构成投资建议。

## 范围

### 市场

- 美股：S&P 500。
- A 股：沪深 300。

### 数据频率

- 第一版使用日线。
- 历史窗口默认 5 年。
- 架构预留分钟级别，但 v2 不实现分钟级策略。

### 数据源

- 美股第一版 provider：`yfinance`。
- A 股第一版 provider：`AKShare`。
- 保留 `CsvMarketDataProvider`，用于本地导入、fallback 和测试 fixture。
- provider 只负责同步数据，策略和扫描只读取本地缓存。

## 总体架构

```text
免费数据源
  -> MarketDataProvider
  -> 本地缓存 / SQLite
  -> 数据质量检查
  -> 股票池 / Instrument Master
  -> Strategy Engine
  -> Signal Scanner
  -> Score Weighted Portfolio
  -> Backtest Engine
  -> Signals 页面
  -> Paper Order Draft
  -> Paper Trading 人工确认
```

核心原则：

- 多市场统一接口，市场差异通过 `MarketRules` 和 provider 适配。
- 策略统一输出标准 `Signal`，后续趋势突破、均值回归、复合因子和自进化策略都复用同一信号消费链路。
- 外部数据全部落本地缓存，避免页面打开时直接依赖网络。
- 扫描、订单草稿和状态变化都要写入审计事件。

## 数据层

### Provider 接口

定义统一 provider：

```text
MarketDataProvider
- sync_instruments(index_id)
- sync_bars(symbols, market, start, end, timeframe="1d")
- incremental_sync(symbols, market)
```

第一版 provider：

- `YahooFinanceProvider`：同步 S&P 500 美股日线。
- `AkshareProvider`：同步沪深 300 成分和 A 股日线。
- `CsvMarketDataProvider`：本地 CSV 导入和测试数据。

provider 失败时不直接影响已缓存数据。扫描默认使用最近一次成功缓存。

### Instrument Master

维护标的基础信息：

```text
symbol
market
name
name_zh
exchange
currency
sector
index_membership
tradable
lot_size
```

美股也显示中文名。第一版中文名来自 CSV 维护：

```text
data/instruments/us_sp500.csv
data/instruments/cn_csi300.csv
```

示例字段：

```csv
symbol,market,name,name_zh,exchange,currency,sector,index_membership
AAPL,US,Apple Inc.,苹果公司,NASDAQ,USD,Technology,SP500
MSFT,US,Microsoft Corporation,微软,NASDAQ,USD,Technology,SP500
600519,CN,Kweichow Moutai Co. Ltd.,贵州茅台,SSE,CNY,Consumer Staples,CSI300
```

provider 拉到的名称可以补充，但 `name_zh` 以本地 CSV 为准。

### 行情缓存

日线字段：

```text
symbol
market
date
open
high
low
close
volume
amount
adjusted
suspended
limit_up
limit_down
source
```

同步规则：

- 首次同步拉近 5 年日线。
- 后续按 symbol 增量更新，只补最新日期之后的数据。
- 每个 symbol 记录最新同步日期。
- 每次同步记录 `sync_job_id`、成功数、失败数、覆盖率、失败样例和最近更新时间。
- 单只股票拉取失败时跳过该股票，并记录失败原因。
- 某个市场有效覆盖率大于等于 70% 时，允许生成该市场信号。
- 某个市场有效覆盖率低于 70% 时，该市场扫描失败，不输出候选。

### 数据质量报告

每次同步后生成质量报告：

- 缺失 K 线数量。
- 重复 K 线数量。
- OHLC 异常数量。
- 停牌或不可交易数量。
- 涨跌停数量。
- 覆盖率。
- 最近更新时间。
- 失败 symbol 样例。

Signals 页面和 Data Health 页面都展示同步状态和质量摘要。

## 市场规则

市场规则集中在配置中，回测、订单草稿和模拟盘共用。

示例默认值：

```yaml
US:
  commission_rate: 0.0005
  tax_rate_sell: 0
  slippage_rate: 0.0005
  min_fee: 0
  lot_size: 1
  t_plus_one: false

CN:
  commission_rate: 0.0003
  tax_rate_sell: 0.0005
  slippage_rate: 0.0005
  min_fee: 5
  lot_size: 100
  t_plus_one: true
```

A 股必须处理：

- 100 股一手。
- T+1，当天买入不可当天卖出。
- 涨停不新买入。
- 跌停不假设可卖出。
- 停牌不可交易。

美股第一版按整数股处理，暂不做融资融券和复杂结算。

## 策略和信号层

### 策略接口

策略输入：

```text
market
universe
bars
current_positions
parameters
market_rules
```

策略输出：

```text
Signal
- symbol
- market
- signal: buy / hold / sell
- score
- target_weight
- reason
- risk_flags
- as_of_date
```

回测、扫描、订单草稿都只消费标准 `Signal`，不依赖具体策略内部实现。

### 第一版策略：cross_sectional_momentum

第一版实现横截面多因子动量策略：

```text
score =
  0.50 * 120日动量排名分
+ 0.25 * 20日动量排名分
- 0.15 * 波动率惩罚
- 0.10 * 最大回撤惩罚
```

硬过滤：

- 数据缺失剔除。
- 停牌剔除。
- 成交额低于阈值剔除。
- 波动率高于阈值剔除。
- 最大回撤超过阈值剔除。
- A 股涨停不新买入。
- A 股跌停不假设可卖出。

### 买卖规则

每个市场单独排名：

- 买入：
  - 进入每个市场 Top 20。
  - 分数大于最小阈值。
  - 通过风险过滤。
- 持有：
  - 已持仓。
  - 仍在 Top 50。
  - 未触发止损或风险过滤。
- 卖出：
  - 跌出 Top 50。
  - 或触发止损。
  - 或触发风险过滤。
  - 或数据质量异常。

### 权重构建

默认权重策略是 `score_weighted`：

- 每个市场 Top 20 参与权重分配。
- 正分按分数归一化。
- 单票最大权重 8%。
- 单市场资金预算可配置。
- 低于最小目标权重不生成订单草稿。

保留扩展：

- `equal_weight`
- `volatility_inverse`
- `risk_parity`

## Signals 扫描

### 手动扫描

Signals 页面支持手动运行：

- 选择市场：US / CN / Both。
- 选择策略：默认 `cross_sectional_momentum`。
- 读取本地缓存，必要时可先刷新数据。
- 生成 `scan_id` 和候选榜单。

### 定时扫描

默认按市场收盘后扫描：

- A 股：15:30 Asia/Shanghai。
- 美股：16:30 America/New_York。

第一版使用轻量本地 scheduler：

- 进程运行时按配置触发扫描。
- 扫描结果写入 SQLite。
- 后台展示 last run、next run、status、error message 和 coverage。
- 如果本地进程没运行，定时任务不会补跑；后续生产化再做 durable job queue。

### 快照保存

每次扫描保存历史快照：

```text
scan_id
strategy_template
parameters
market_scope
dataset_version
as_of_date
coverage
created_at
```

每个候选保存：

```text
symbol
market
name
name_zh
close
signal
score
target_weight
reason
risk_flags
as_of_date
```

Signals 页面默认展示：

- US Top 20。
- CN Top 20。

可切换到：

- Global Top 40。
- 全市场视图使用标准化分数，并标注“跨市场排名仅供研究比较”。

## 回测引擎

v2 回测消费真实行情和策略信号：

```text
BacktestEngine
- 输入：strategy_id、market、universe、bars、parameters、market_rules
- 每个交易日生成 signals
- 根据信号生成目标仓位
- 按市场规则撮合
- 输出：equity curve、drawdown curve、trades、positions、metrics
```

输出指标：

- total_return
- CAGR
- volatility
- Sharpe
- Sortino
- max_drawdown
- Calmar
- turnover
- win_rate
- avg_holding_days

回测必须使用同一套市场规则，包括交易成本、滑点、A 股 T+1、涨跌停、停牌和 100 股一手。

## 模拟盘订单草稿

Signals 页面只生成模拟盘订单草稿，不直接提交订单。

```text
PaperOrderDraft
- draft_id
- scan_id
- account_id
- strategy_id
- symbol
- market
- side
- target_weight
- current_weight
- estimated_quantity
- reference_price
- reason
- risk_flags
- status: draft / approved / cancelled / submitted / blocked
```

Paper Trading 页面负责人工作流：

```text
draft -> approved -> submitted -> paper order/fill
```

阻断规则：

- A 股 T+1 锁定数量不足时，草稿标记 `blocked`。
- 涨跌停或停牌时，草稿标记 `blocked`。
- 单票权重超过 8% 时，裁剪权重并记录 reason。
- 数据过期时，不生成草稿。

## 后台页面

### Signals / Research Candidates

新增核心页面。

顶部状态：

- 当前策略。
- 数据窗口。
- 最新扫描时间。
- 覆盖率。
- 数据源状态。

操作：

- Run Scan。
- Refresh Data。
- 市场筛选：US / CN / Both。
- 视图切换：分市场 Top 20 / 全市场 Top 40。

表格字段：

- symbol。
- 中文名。
- market。
- close。
- signal：buy / hold / sell。
- score。
- target_weight。
- reason。
- risk_flags。
- as_of_date。

操作：

- 查看详情。
- 生成模拟盘订单草稿。

### Data Health

增强内容：

- provider 状态。
- S&P 500 / 沪深 300 成分数量。
- 行情同步覆盖率。
- 同步失败 symbol 样例。
- 最新同步时间。
- 数据质量报告。

### Backtests

增加真实回测入口：

- 选择策略模板。
- 选择市场。
- 选择历史窗口。
- 运行真实回测。
- 展示净值曲线、回撤曲线、指标表、交易记录和持仓变化。

### Paper Trading

增加订单草稿区：

- Draft Orders。
- 来源 scan_id。
- symbol / 中文名。
- side。
- target_weight。
- estimated_quantity。
- reference_price。
- risk_flags。
- approve / cancel / submit。

保留现有模拟账户、纸面订单、成交和持仓。

### Strategies / Evolution

Strategies：

- 关联最新 scan。
- 展示真实回测指标。
- 展示信号策略参数。
- 支持策略状态流转。

Evolution：

- v2 不做复杂 AI 生成策略代码。
- 先支持对 `cross_sectional_momentum` 参数做搜索：
  - `lookback_long`
  - `lookback_short`
  - `volatility_window`
  - `max_weight`
  - `top_n`
  - `exit_rank`
- 候选参数进入回测和扫描流程后再人工审核。

## API 能力

v2 API 需要覆盖：

- 数据同步：
  - 启动同步。
  - 查看同步状态。
  - 查看覆盖率和失败样例。
- Signals：
  - 启动扫描。
  - 查看最新扫描。
  - 查看扫描历史。
  - 查看单个 scan 详情。
- 订单草稿：
  - 从 scan 生成草稿。
  - 查看草稿。
  - approve / cancel / submit。
- 回测：
  - 启动真实回测。
  - 查看结果指标、交易和持仓。
- 调度：
  - 查看 schedule。
  - 暂停 / 启用 schedule。

## 测试策略

后端单元测试：

- Provider 接口：
  - yfinance 和 AKShare 使用 fake client，不在单元测试里打真实网络。
  - CSV provider 使用 fixture 数据测试。
- 数据同步：
  - 首次同步 5 年窗口。
  - 增量同步只补最新日期之后的数据。
  - 覆盖率低于 70% 时市场扫描失败。
- 数据质量：
  - 缺失 K 线。
  - 重复 K 线。
  - OHLC 异常。
  - 停牌和涨跌停标记。
- 策略信号：
  - Top 20 buy。
  - Top 50 hold。
  - 跌出 Top 50 sell。
  - 风险过滤剔除。
  - 分数加权权重上限 8%。
- A 股市场规则：
  - T+1。
  - 100 股一手。
  - 涨停不买。
  - 跌停不卖。
- 订单草稿：
  - Signals 只生成 draft。
  - Paper Trading 人工确认后才提交。
- API：
  - 数据同步状态。
  - Signals scan。
  - scan history。
  - order draft lifecycle。
  - backtest result。

前端验证：

- Signals 页面能运行 scan，并展示 US / CN / Global。
- Data Health 能展示覆盖率和失败 symbol。
- Paper Trading 能看到 draft 并人工提交。
- 空数据、provider 失败、覆盖率不足都有明确状态。

## 安全边界

- 不接真实券商。
- 不发真实实盘订单。
- `buy / hold / sell` 是策略信号，不是投资建议。
- 所有订单都是模拟盘 draft 或 paper order。
- 免费数据源只用于研究，数据可能延迟或不完整。
- 覆盖率不足不输出该市场信号。
- 所有 scan、draft、状态变化写审计事件。

## v2 不做的事情

- 分钟级策略实盘化。
- LLM 自动生成并执行任意策略代码。
- 真实 broker / exchange API。
- 完整生产任务队列。
- 行业暴露、相关性、Beta 风险约束。
- RBAC 和多用户权限。
- 通知系统。
- 复杂组合优化器。

## 成功标准

v2 完成时，系统应该能做到：

1. 拉取并缓存 S&P 500 / 沪深 300 近 5 年日线。
2. 数据覆盖率达标时，运行 `cross_sectional_momentum` 扫描。
3. Signals 页面显示 US Top 20、CN Top 20、Global Top 40。
4. 每个候选有中文名、分数、权重、`buy / hold / sell`、原因和风险标签。
5. 扫描结果保存历史快照。
6. 可以从信号生成模拟盘订单草稿。
7. Paper Trading 页面人工确认草稿后生成纸面订单。
8. A 股回测和订单草稿尊重 T+1、涨跌停、停牌和 100 股一手。
9. 后端测试、前端 typecheck 和前端 build 通过。
10. 文档清楚说明数据源限制和非投资建议边界。
