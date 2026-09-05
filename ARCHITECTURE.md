# EvoQuant 平台全栈系统架构文档

本文档全面梳理了 **EvoQuant (自进化量化交易与风险控制平台)** 的底层架构设计、模块划分、数据流动路径、存储引擎适配以及前后端组件拓扑。

---

## 目录
1. [系统整体架构](#1-系统整体架构)
2. [技术栈与项目目录结构](#2-技术栈与项目目录结构)
3. [数据存储层架构 (Storage Architecture)](#3-数据存储层架构-storage-architecture)
4. [行情数据采集与智能增量引擎 (Market Data Ingestion)](#4-行情数据采集与智能增量引擎-market-data-ingestion)
5. [策略与全市场信号扫描引擎 (Strategies & Signals Engine)](#5-策略与全市场信号扫描引擎-strategies--signals-engine)
6. [模拟盘交易与订单草稿系统 (Paper Trading & Order Drafts)](#6-模拟盘交易与订单草稿系统-paper-trading--order-drafts)
7. [策略自进化与回测框架 (Evolution & Backtest)](#7-策略自进化与回测框架-evolution--backtest)
8. [后端 RESTful API 路由映射 (FastAPI Routes)](#8-后端-restful-api-路由映射-fastapi-routes)
9. [前端 UI 架构与页面映射 (React + TypeScript)](#9-前端-ui-架构与页面映射-react--typescript)
10. [运维部署与扩展指南 (Deployment Guide)](#10-运维部署与扩展指南-deployment-guide)

---

## 1. 系统整体架构

EvoQuant 采用了模块化、解耦的分层量化架构：

```
+-------------------------------------------------------------------------+
|                         前端 Web 管理控制台                              |
|           React + TypeScript + Vite + Vanilla CSS (11大核心页面)        |
+-------------------------------------------------------------------------+
                                    |  HTTP REST / JSON
                                    v
+-------------------------------------------------------------------------+
|                       后端 REST API 服务 (FastAPI)                       |
|   /api/dashboard  |  /api/data-sync  |  /api/signals  |  /api/paper ... |
+-------------------------------------------------------------------------+
    |                 |                   |                   |
    v                 v                   v                   v
+-------------+ +---------------+ +---------------+ +-------------------+
| 股票池服务  | | 行情同步服务  | | 信号扫描引擎  | | 模拟盘与草稿服务  |
| Instruments | | MarketData    | | SignalScanner | | PaperTrading      |
+-------------+ +---------------+ +---------------+ +-------------------+
                      |                   |
                      v                   v
            +------------------------------------+
            | 行情源 (Yahoo / Baostock / SEC API)|
            +------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
|                   统一数据存储层 (Storage Layer)                         |
|   - 零侵入兼容适配器 (PostgresConnection / Cursor Wrapper)                |
|   - 双引擎支持: SQLiteStore (本地) / PostgreSQLStore (NAS/集中式)        |
+-------------------------------------------------------------------------+
```

---

## 2. 技术栈与项目目录结构

### 技术栈
*   **后端 Core**: Python 3.14+ / FastAPI / Uvicorn / Pydantic v2
*   **数据处理与统计**: Pandas / NumPy / PyTest
*   **数据库接入**: Python 内置 `sqlite3` / `psycopg2-binary` (PostgreSQL) / `paramiko` (远程DevOps)
*   **行情接口**: `yfinance` (美股/SEC API) / `baostock` (A股全市场)
*   **前端 Core**: React 18+ / TypeScript / Vite / Vanilla CSS (精美现代暗黑风 UI)

### 项目目录树
```
stock_quantification/
├── pyproject.toml              # 项目依赖与包元数据配置
├── README.md                   # 说明文档
├── agent.md                    # Agent 行为偏好与架构维护规范
├── ARCHITECTURE.md             # 本架构文档
├── scratch/                    # 运维与数据迁移实用脚本集
│   ├── migrate_to_pg.py        # SQLite ➡️ PostgreSQL 高速全量数据迁移脚本
│   ├── deploy_nas_docker.py    # 远程 NAS Docker 部署自动化脚本
│   ├── upload_tar_to_nas.py    # 离线镜像 SFTP 高速直传脚本
│   └── sync_cn_bars_3y.py      # A股3年行情增量同步脚本
├── src/
│   └── evoquant/               # 后端核心源码包
│       ├── api.py              # FastAPI 应用入口与 REST 路由定义
│       ├── domain.py           # 领域枚举与核心数据模型 (Market, SignalSide 等)
│       ├── storage.py          # 存储层 (SQLiteStore & PostgreSQLStore 及兼容适配器)
│       ├── metrics.py          # 量化性能指标计算模块 (Sharpe, MaxDrawdown 等)
│       ├── providers/          # 行情源接入适配器 (Yahoo, Baostock, Tiingo, CSV)
│       └── services/           # 核心业务服务逻辑
│           ├── instruments.py  # 股票池管理服务
│           ├── market_data.py  # K线行情存储与分批查询
│           ├── bar_sync.py     # 分批行情同步 Job 调度
│           ├── auto_sync.py    # 自动定时同步调度服务
│           ├── signals.py      # 策略信号扫描器与真实覆盖率计算
│           ├── strategies.py   # 横截面动量算法与风险打分
│           ├── paper.py        # 模拟盘账户与持仓盈亏管理
│           ├── drafts.py       # 智能调仓订单草稿生成服务
│           ├── market_rules.py # 市场交易规则 (印花税/佣金/最小交易单位)
│           ├── backtest.py     # 策略历史回测引擎
│           ├── evolution.py    # 策略参数自进化引擎
│           ├── registry.py     # 策略模板与实例注册表
│           └── risk.py         # 风险控制与指标监控
└── frontend/                   # 前端 React 应用
    ├── index.html
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── App.tsx             # 导航与路由切换组件
        ├── api.ts              # 后端 API 轮询与 HTTP 请求客户端
        ├── styles.css          # CSS 设计系统
        └── pages/              # 11 大核心功能页面
            ├── Overview.tsx    # 系统概览看板
            ├── StockPool.tsx   # 股票池管理
            ├── DataHealth.tsx  # 数据源同步与质量监控
            ├── Strategies.tsx  # 策略管理
            ├── Signals.tsx     # 信号扫描与打分 Top 20
            ├── PaperTrading.tsx# 模拟盘交易与持仓
            ├── Manual.tsx      # 订单草稿与手动调仓确认
            ├── Backtests.tsx   # 策略回测面板
            ├── Evolution.tsx   # 策略自进化
            ├── Risk.tsx        # 风险风控中心
            └── AuditLog.tsx    # 审计日志
```

---

## 3. 数据存储层架构 (Storage Architecture)

存储层在 `src/evoquant/storage.py` 中实现了**双存储引擎热切换与零侵入方言适配**：

### 双引擎设计
1.  **`SQLiteStore`**：基于单文件 `var/evoquant.db`，开箱即用，无需配置外部依赖，非常适合单元测试和轻量本地研发。
2.  **`PostgreSQLStore`**：基于集中式/NAS 数据库，当环境变量中配置了 `EVOQUANT_DB_URL`（如 `postgresql://postgres:password@192.168.124.18:45869/evoquant`）时自动激活。

### 零侵入兼容适配器 (Adapter Pattern)
为了避免修改系统中成百上千条业务 SQL，引入了 `PostgresConnectionWrapper` 与 `PostgresCursorWrapper`：
*   **占位符自动转换**：运行时自动将 SQLite 的 `?` 占位符转换为 PostgreSQL 的 `%s` 方言。
*   **元数据检查拦截**：自动将 SQLite 专有的 `PRAGMA table_info(table_name)` 翻译为 PostgreSQL 标准的 `information_schema.columns` 查询。
*   **字典/元组二合一访问**：游标使用 `psycopg2.extras.DictCursor` 包装，返回行同时支持 `row["col"]` 键名与 `row[0]` 索引访问，100% 兼容 `sqlite3.Row`。

### 变量数分批防抖 (Chunking Protection)
在 `MarketDataService` 的 `list_bars` 与 `latest_session` 方法中，对传入的 `symbols` 数组强制进行每 **500 个一组的分批 Chunk 处理**，彻底解除了 SQLite / Postgres 在大批量 `IN (...)` 查询时的变量超限崩塌 Bug。

### 核心表结构 Schema
*   `instruments`：股票池标的字典 (PRIMARY KEY: `symbol`, `market`)
*   `market_bars`：日 K 线行情数据 (PRIMARY KEY: `symbol`, `market`, `session`)
*   `bar_sync_jobs` / `market_sync_jobs`：行情同步 Job 记录
*   `signal_scans` / `signal_results`：信号扫描记录与各标的分数 Top N 结果
*   `paper_order_drafts`：模拟盘/实盘调仓订单草稿
*   `strategies` / `schedule_configs` / `audit_events`：策略与系统审计事件

---

## 4. 行情数据采集与智能增量引擎 (Market Data Ingestion)

行情服务支持全市场规模与智能增量：

1.  **全市场股票池初始化**：
    *   **美股 (Market.US)**：在 `YahooProvider` 中对接 SEC 官方 API，动态提取并清洗 7,200+ 只主板普通股。
    *   **A 股 (Market.CN)**：在 `BaostockProvider` 中获取 4,700+ 只全市场股票列表。
2.  **智能增量同步 (Incremental Sync)**：
    *   同步前自动调用 `latest_session(market, symbols)` 计算底层数据库中当前标的集合的最晚交易日。
    *   起始时间自动设定为 `latest_session + 1 天`，避免重复下载已有历史，提升同步效率。
3.  **自动前置防空逻辑**：
    *   当用户点击“同步行情”时，如果检测到股票池尚未初始化，系统会自动触发静默前置股票池同步，做到一键无忧接入。

---

## 5. 策略与全市场信号扫描引擎 (Strategies & Signals Engine)

核心扫描器位于 `src/evoquant/services/signals.py` 与 `strategies.py`：

1.  **横截面动量策略 (CrossSectionalMomentumStrategy)**：
    *   **指标计算**：对在库个股计算 120 日长周期收益率与 20 日短周期收益率，结合年化波动率与最大回撤。
    *   **分位数打分 (Percentile Ranking)**：采用 `_rank_percentiles` 对各维度指标在全市场进行归一化排序，组合算出综合动量得分 `Score`。
    *   **风险标记 (Risk Flags)**：自动检测并打上 `insufficient_data` (数据不足)、`suspended` (停牌)、`low_liquidity` (流动性差)、`high_volatility` (高波动)、`limit_up/down` (涨跌停板) 等风控标签。
2.  **真实在库数据覆盖率验证**：
    *   由 `_latest_sync_coverage` 基于数据库真实 Price 数据的在库股票占比进行覆盖率校验，解锁全市场 Top 20 优质标的选拔。

---

## 6. 模拟盘交易与订单草稿系统 (Paper Trading & Order Drafts)

1.  **模拟盘服务 (`PaperTradingService`)**：
    *   维护资金账户、资产净值 (NAV)、持仓明细与未实现盈亏。
    *   支持模拟市价单与限价单的实时撮合执行。
2.  **智能调仓订单草稿 (`OrderDraftService`)**：
    *   对比信号扫描生成的 Top N 目标权重与模拟盘当前持仓。
    *   结合 `market_rules.py` 扣除交易佣金、印花税（A股卖出千分之一）及最小交易股数（A 股 100 股一手）限制，自动生成买/卖调仓订单草稿 (Order Drafts)。
    *   用户可在前端 **Manual (手动调仓)** 页面一键审核并确认下发。

---

## 7. 策略自进化与回测框架 (Evolution & Backtest)

1.  **历史回测 (`BacktestService`)**：
    *   按时间序列回放历史 K 线，模拟信号产生、组合调仓与净值曲线生成。
    *   在 `metrics.py` 中精准计算夏普比率 (Sharpe Ratio)、索提诺比率 (Sortino Ratio)、最大回撤 (Max Drawdown) 与胜率 (Win Rate)。
2.  **策略自进化 (`EvolutionService`)**：
    *   对策略参数空间（如 lookback 窗口、Top N 筛选数等）进行网格搜索与遗传选择，自动淘汰劣质参数，选拔优胜策略实例。

---

## 8. 后端 RESTful API 路由映射 (FastAPI Routes)

| 路由路径 | HTTP 方法 | 功能描述 |
| :--- | :--- | :--- |
| `/healthz` | GET | 系统健康状态检查 |
| `/api/dashboard` | GET | 控制台概览数据 (策略数、账户NAV、风控状态) |
| `/api/instruments` | GET / POST | 查询及初始化股票池 |
| `/api/data-sync/jobs` | GET / POST | 行情数据同步任务管理与触发 |
| `/api/signals/scans` | GET / POST | 发起全市场信号扫描与历史记录查询 |
| `/api/signals/scans/{id}/results` | GET | 查询指定扫描任务的 Top N 标的打分结果 |
| `/api/paper/accounts` | GET / POST | 模拟盘账户查询与创建 |
| `/api/paper/drafts` | GET / POST / PATCH | 调仓订单草稿查询、生成与确认执行 |
| `/api/backtests` | GET / POST | 策略历史回测任务 |
| `/api/evolution` | GET / POST | 策略参数自进化选拔 |
| `/api/risk/metrics` | GET | 系统实时风控监控指标 |
| `/api/audit-logs` | GET | 审计事件日志 |

---

## 9. 前端 UI 架构与页面映射 (React + TypeScript)

前端位于 `frontend/src/`，采用极具现代感的暗黑科技风设计，主要页面组件与功能映射如下：

*   **Overview.tsx**：系统主看板，展示资金曲线、策略分布与数据健康状态。
*   **StockPool.tsx**：股票池呈现，支持美股/A股标的查看。
*   **DataHealth.tsx**：数据源同步中心，提供 Sync US / Sync CN 智能同步锁与质量检测。
*   **Strategies.tsx**：策略模板管理与实例创建。
*   **Signals.tsx**：信号扫描中心，可视化展示 Top 20 打分、调仓建议及 Risk Flags。
*   **PaperTrading.tsx**：模拟盘账户、持仓分布与实时盈亏。
*   **Manual.tsx**：调仓订单草稿审阅与一键下发执行。
*   **Backtests.tsx**：历史回测运行与 Performance 曲线绘制。
*   **Evolution.tsx**：策略自进化参数演化追踪。
*   **Risk.tsx**：风控限额与预警配置。
*   **AuditLog.tsx**：全平台操作与系统审计追溯。

---

## 10. 运维部署与扩展指南 (Deployment Guide)

### 本地轻量运行
```bash
# 后端启动 (默认 SQLite)
uv run evoquant --host 127.0.0.1 --port 8000

# 前端启动
cd frontend && npm run dev
```

### 集中式 / NAS PostgreSQL 运行
```bash
# 启动时注入 PostgreSQL 连接串
EVOQUANT_DB_URL="postgresql://postgres:password@192.168.124.18:45869/evoquant" uv run evoquant --host 127.0.0.1 --port 8000
```

### 数据一键迁移脚本
```bash
# 将 SQLite 全量无损灌入 PostgreSQL
EVOQUANT_DB_URL="postgresql://postgres:password@192.168.124.18:45869/evoquant" uv run python scratch/migrate_to_pg.py
```
