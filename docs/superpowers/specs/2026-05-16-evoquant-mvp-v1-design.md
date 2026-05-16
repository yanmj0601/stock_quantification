# EvoQuant MVP v1 设计文档

## 目标

建设一个多市场通用、支持策略自进化的量化研究平台。系统需要能够生成候选策略、运行回测、验证稳健性、登记策略版本、运行模拟盘，并通过一个简单的后台管理台把完整闭环暴露出来。

第一版优先保证可复现和可运营。每一个候选策略都必须能追踪到数据版本、策略参数、验证指标、审批记录、模拟盘表现和淘汰原因。

## 已确认决策

- 平台按多市场通用设计，不写死 A 股、美股或币圈。
- MVP v1 优先建设研究自进化闭环，并把模拟盘提前纳入第一版。
- 真实实盘交易不进入 v1 范围，执行适配器只保留接口边界。
- 后台管理台要做成可反复使用的投研运营工具，不做装饰性大屏。
- 策略页面必须展示收益和风险指标，包括年化收益率、Sharpe、最大回撤、Calmar、换手率、验证状态和模拟盘衰减。

## MVP 范围

### v1 要做

#### Data Hub

- 多市场数据适配器接口。
- K 线、标的元数据、交易日历引用和数据集版本。
- 数据质量检查：新鲜度、缺失 K 线、重复数据、价格异常。
- 初始存储可以使用本地文件和 SQLite 元数据，但 schema 要保持方便迁移到 Postgres。

#### Strategy Factory

- 带明确参数空间的策略模板。
- 通过确定性的模板展开和参数搜索生成候选策略。
- v1 不允许无限制的 LLM 自动写生产策略代码。

#### Backtest Runner

- 基于任务的回测执行。
- 支持交易成本、滑点、仓位约束和调仓频率。
- 输出指标包括：年化收益率、波动率、Sharpe、Sortino、最大回撤、Calmar、换手率、胜率、盈亏比和暴露摘要。

#### Robustness Gate

- 样本外验证。
- Walk-forward 验证。
- 参数稳定性检查。
- 成本敏感性检查。
- 与已批准策略的相关性检查。

#### Strategy Registry

- 记录策略 id、名称、版本、市场范围、资产类别、模板、参数、代码 hash、数据集版本、状态、指标和审计轨迹。
- 策略状态包括：`research`、`candidate`、`paper`、`small-live-ready`、`production-ready`、`retired`。
- v1 可以使用 `small-live-ready` 和 `production-ready` 作为审批状态，但这些状态不能触发真实实盘订单。

#### Paper Trading

- 模拟账户：现金、权益、已实现盈亏、未实现盈亏和净值。
- 模拟组合：持仓、平均成本、市值和持仓盈亏。
- 模拟订单：订单意图、模拟成交、成交价格、费用和时间戳。
- 将模拟盘表现与回测指标对比，用于发现策略衰减。

#### Risk Gate

- 全局模式：`research-only`、`paper-only`、`paused`。
- 策略级暂停和淘汰动作。
- 候选策略晋级必须有验证结果和人工审批。
- v1 始终禁用真实实盘交易。

#### Admin Console

- Overview。
- Strategies。
- Backtests。
- Evolution。
- Paper Trading。
- Data Health。
- Risk。
- Audit Log。

### v1 明确不做

- 真实券商或交易所实盘下单。
- 不受限制的 LLM 自动生成策略并直接写入策略注册表。
- 强化学习生产策略。
- 完整 RBAC 或组织级权限体系。
- 大规模分布式训练或搜索集群。
- 直接绑定某一个交易引擎，例如 NautilusTrader、LEAN、vn.py 或 Freqtrade。

## 架构

平台需要保持清晰边界，让每个子系统都能独立测试和替换。

```text
Data Adapters
  -> Data Hub
  -> Dataset Registry
  -> Strategy Factory
  -> Backtest Runner
  -> Robustness Gate
  -> Strategy Registry
  -> Admin Approval
  -> Paper Trading
  -> Feedback Loop
```

反馈闭环会把模拟盘表现、验证失败原因和淘汰原因写回策略注册表。这些记录会成为后续候选策略生成和参数搜索的输入。

## 多市场模型

市场差异应该放在适配器和规则对象里，不应该散落在策略逻辑或注册表逻辑中。

核心抽象：

- `Market`：交易市场或资产域，例如 `US`、`CN`、`CRYPTO`。
- `Instrument`：symbol、市场、资产类别、币种、交易所、最小交易单位和可交易性元数据。
- `Calendar`：交易日、节假日、交易时间和结算假设。
- `FeeModel`：佣金、税费、点差、资金费率和融券成本假设。
- `SlippageModel`：价格冲击和成交假设。
- `PositionRule`：最小交易单位、是否只能做多、是否可卖空、杠杆、集中度和市场特有约束。
- `Bar`：时间戳、开高低收、成交量、复权标记和数据源元数据。

同一个策略模板在提供兼容的数据适配器和交易规则后，应该可以运行在不同市场上。

## Admin Console

后台管理台应该信息密度高、偏运营工具风格，适合反复使用。

### Overview

- 按状态统计策略数量。
- 活跃任务数量。
- 候选策略通过/失败数量。
- 模拟账户摘要。
- 全局风险模式。
- 最近审计事件。

### Strategies

列表列字段：

- 策略名称和版本。
- 市场和资产类别。
- 状态。
- 年化收益率。
- Sharpe。
- 最大回撤。
- Calmar。
- 换手率。
- 验证状态。
- 模拟盘衰减。
- 操作：批准进入模拟盘、暂停、淘汰、打开详情。

详情页：

- 净值曲线。
- 回撤曲线。
- 月度和年度收益。
- 训练、验证、测试和模拟盘分段指标。
- 参数、模板 id、代码 hash、数据集版本和审计历史。

### Backtests

- 提交回测任务。
- 查看排队、运行中、成功和失败任务。
- 对比不同策略版本的结果指标。
- 打开生成的报告和验证诊断。

### Evolution

- 配置目标函数。
- 配置策略模板和参数空间。
- 限制最大候选策略数量。
- 候选策略进入注册表前需要人工审核。

### Paper Trading

- 模拟账户净值、现金、权益、已实现盈亏和未实现盈亏。
- 持仓表。
- 订单和模拟成交记录。
- 模拟盘指标与回测指标对比。
- 模拟盘衰减预警。

### Data Health

- 数据源新鲜度。
- 缺失 K 线数量。
- 重复 K 线数量。
- 价格异常数量。
- 数据集版本和质量报告。

### Risk

- 全局暂停。
- Paper-only 模式。
- 策略级暂停。
- 晋级门槛配置。

### Audit Log

- 不可变事件日志，记录策略创建、状态变更、回测提交、验证结果、模拟盘订单、风险模式变更和人工审批。

## 数据存储

MVP 可以使用 SQLite 加本地文件，但要通过清晰的 repository 接口封装，方便后续替换成 Postgres 和对象存储。

建议持久化记录：

- `datasets`
- `instruments`
- `bars_metadata`
- `strategies`
- `strategy_versions`
- `strategy_metrics`
- `jobs`
- `validation_reports`
- `paper_accounts`
- `paper_positions`
- `paper_orders`
- `paper_fills`
- `risk_state`
- `audit_events`

时序 K 线数据可以先用 Parquet 或 CSV 文件保存，并由数据集元数据引用。

## API 范围

初始 API 分组：

- `/api/dashboard`
- `/api/strategies`
- `/api/strategies/{id}`
- `/api/strategies/{id}/status`
- `/api/backtests`
- `/api/evolution`
- `/api/paper/accounts`
- `/api/paper/orders`
- `/api/data-health`
- `/api/risk`
- `/api/audit-events`

所有会改变状态的接口都必须写入审计事件。

## 任务模型

即使 v1 只在本地运行任务，任务也必须是显式记录。

任务类型：

- `backtest`
- `validation`
- `evolution`
- `paper_rebalance`
- `data_quality_check`

任务状态：

- `queued`
- `running`
- `success`
- `failed`
- `cancelled`

任务表需要保存请求 payload、结果 payload、错误信息、时间戳和相关实体 id。

## 安全规则

- v1 禁用真实实盘交易。
- 只有模拟盘模式可以产生模拟成交。
- 候选策略晋级必须人工审批。
- 没有验证记录的策略不能进入模拟盘。
- 所有状态流转和风险开关变更都必须审计。
- 研究任务遇到缺失或过期数据时应明确失败，不能静默降级。

## 技术方向

- 后端：FastAPI。
- 存储：MVP 使用 SQLite，repository 接口按后续迁移 Postgres 设计。
- Worker：MVP 使用本地数据库任务队列，后续可替换为 Celery、RQ 或 Ray。
- 前端：React 后台管理台，优先实现表格、详情页和图表。
- 图表：使用轻量图表库展示净值、回撤和收益视图。
- 测试：pytest，覆盖 service 层和 API 层。

## 实施说明

当前仓库里有一份在本设计定稿前提前产生的实现 spike。它只应被视为一次可丢弃的草稿。实施计划需要明确哪些文件保留、重写或删除；除非某个行为出现在本文档中，否则不视为已经批准。

## 验收标准

- 用户可以创建或导入策略模板候选。
- 用户可以运行回测任务并查看绩效指标。
- 验证门槛可以根据稳健性规则让策略通过或失败。
- 通过验证的策略可以由人工批准进入模拟盘。
- 模拟账户可以模拟持仓、订单、成交和净值。
- 后台管理台可以展示策略收益、风险指标、验证状态、模拟盘衰减、任务、数据健康、风险状态和审计事件。
- 所有重要状态变更都会写入审计事件。
- 系统启动时真实实盘交易必须处于禁用状态。
