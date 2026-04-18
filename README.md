# Stock Quantification

一个面向 A 股和美股的个人量化底座最小实现，包含：

- 双市场统一领域模型
- A 股 / 美股策略与市场规则适配
- `Research Agent -> Strategy Agent -> Review Agent -> Orchestrator` 最小多 Agent 协作链
- 确定性的组合构建、风控校验、执行规划
- 多账户隔离与重复刷新去重
- `train / validate / test` 切分、`walk-forward` 验证、参数稳定性研究

## 快速运行

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m stock_quantification.demo
PYTHONPATH=src python3 -m stock_quantification.cli --market ALL
PYTHONPATH=src python3 -m stock_quantification.cli --market ALL --detail-limit 20 --history-limit 60 --beta-window 20
PYTHONPATH=src python3 -m stock_quantification.cli --market CN --symbols-cn 600000,600036,600519
PYTHONPATH=src python3 -m stock_quantification.web
PYTHONPATH=src python3 scripts/run_validation_study.py --market CN --start-date 2026-01-02 --end-date 2026-03-31
PYTHONPATH=src python3 scripts/run_strategy_suite.py --market ALL --start-date 2026-01-02 --end-date 2026-03-31
```

`cli` 会读取真实公开市场数据，并按各市场最近一个有效交易日运行策略。
每次运行会在 `artifacts/` 下写出 JSON 和 Markdown 研究报告。
`web` 会启动一个本地浏览器控制台，用来查看 artifact、触发一次本地策略运行，并保留一个聊天占位面板。
现在 `web` 还提供：

- 项目配置页：`/project/config`
- 任务日志页：`/project/logs`
- 运维中心：`/project/ops`
- 健康检查：`/healthz`
- 就绪检查：`/readyz`
- 状态 API：`/api/project/status`

运维中心会展示服务健康、运行守护、审计事件和后台任务历史；`run` / `factor-backtest` 现在也会经过单任务锁，避免后台重复触发重叠作业。
`run_validation_study.py` 会对指定市场和时间区间运行 `train / validate / test`、`walk-forward` 和参数稳定性分析，并把结果写到 `artifacts/<end-date>/`。
`run_strategy_suite.py` 会批量运行当前工程里已经接入的主流 long-only 策略，并输出收益和最大回撤对比。

## 当前范围

- 研究、选股、评分、下单建议、订单意图规划
- 回测 / 模拟 / 实盘上下文的统一语义
- 默认全市场发现，也支持手动传入局部股票池做验证
- alpha 排名、beta 估计、分层候选池输出
- 本地 artifact 与 universe cache，便于后续替换为真实数据仓库和券商接口
- 本地 `Local Paper` 账本和美股 `Alpaca Paper` 基础路由
- 月度调仓回放脚本与净值曲线图输出
- 验证工具链：样本内外切分、滚动窗口检验、参数稳定性比较

## Alpaca Paper 接入

当前工程已经支持美股 `Alpaca Paper` 的账户同步和订单路由。

开通步骤：

1. 到 Alpaca 创建 `Paper Only Account`
2. 在 Alpaca 控制台生成 paper API key
3. 在本机配置环境变量

```bash
export ALPACA_PAPER_KEY_ID="你的_key"
export ALPACA_PAPER_SECRET_KEY="你的_secret"
```

先做连通性检查：

```bash
PYTHONPATH=src python3 scripts/check_alpaca_paper.py
```

只做研究和下单建议，不发单：

```bash
PYTHONPATH=src python3 -m stock_quantification.cli \
  --market US \
  --runtime-mode LIVE \
  --execution-mode ADVISORY \
  --broker ALPACA_PAPER \
  --symbols-us AAPL,MSFT \
  --top-n 2
```

把通过风控的订单发到 Alpaca paper：

```bash
PYTHONPATH=src python3 -m stock_quantification.cli \
  --market US \
  --runtime-mode LIVE \
  --execution-mode AUTO \
  --broker ALPACA_PAPER \
  --route-orders \
  --symbols-us AAPL,MSFT \
  --top-n 2
```

注意：

- 当前只接了美股 `Alpaca Paper`
- `--route-orders` 只有在 `--execution-mode AUTO` 下才会真正提交订单
- 当前版本会同步账户和提交订单，但还没有补 broker 回报轮询、撤单和成交回写

## 验证研究

验证入口脚本在 [scripts/run_validation_study.py](/Users/juxiantan/ai_agent_project/stock_quantification/scripts/run_validation_study.py)。

它会做三件事：

- `train / validate / test`：把一个历史区间切成研究段、验证段和最终测试段
- `walk-forward`：用滚动窗口重复评估不同场景，避免只依赖单一时间切片
- 参数稳定性：比较不同策略场景在验证段和测试段之间的收益、超额收益、胜率和稳定性分数

示例：

```bash
PYTHONPATH=src python3 scripts/run_validation_study.py --market CN --start-date 2026-01-02 --end-date 2026-03-31
PYTHONPATH=src python3 scripts/run_validation_study.py --market US --start-date 2026-01-02 --end-date 2026-03-31 --holding-sessions 5
PYTHONPATH=src python3 scripts/run_validation_study.py --market CN --scenario-set ablation --start-date 2026-01-02 --end-date 2026-03-31
PYTHONPATH=src python3 scripts/run_validation_study.py --market US --scenario-set ablation --start-date 2026-01-02 --end-date 2026-03-31
```

输出内容包括：

- `artifacts/<end-date>/<market>_validation_study.json`
- `artifacts/<end-date>/<market>_validation_study.md`

JSON 会包含：

- 切分区间
- `walk-forward` 窗口定义
- 每个场景的样本内外平均收益、超额收益和胜率
- 参数稳定性评分与推荐场景

`--scenario-set ablation` 会额外生成因子消融场景，包括：

- `drop_<factor>`：去掉单个因子
- `group_<name>_only`：只保留某一组因子

为了避免重复跑同一个交易日和同一个场景，验证脚本现在会做进程内缓存；真实长区间研究仍然建议先控制 `start-date / end-date` 范围，再逐步放大。

## Web 与图表

本地仪表盘入口在 [src/stock_quantification/web.py](/Users/juxiantan/ai_agent_project/stock_quantification/src/stock_quantification/web.py)，页面模板在 [templates/dashboard.html](/Users/juxiantan/ai_agent_project/stock_quantification/templates/dashboard.html)。

`2026-03` 的双市场净值曲线图已输出到：

- [march_2026_backtest_nav_curve.png](/Users/juxiantan/ai_agent_project/stock_quantification/artifacts/2026-03/march_2026_backtest_nav_curve.png)

## 策略集与路线图

当前工程里已经接入的策略目录见：

- [strategy_map.md](/Users/juxiantan/ai_agent_project/stock_quantification/docs/strategy_map.md)

批量回测入口是：

```bash
PYTHONPATH=src python3 scripts/run_strategy_suite.py --market ALL --start-date 2026-01-02 --end-date 2026-03-31
```

输出内容包括：

- `artifacts/<end-date>/cn_strategy_suite.json`
- `artifacts/<end-date>/us_strategy_suite.json`

现在策略集输出里还会包含：

- `recommended_presets / watchlist_presets / drop_presets`
- 每个策略的 `annualized_return / sharpe_ratio / average_turnover / total_fees / fee_drag`
- `regime_summary`：上涨、震荡、下跌状态下的平均收益和超额
- `alpha_mix`：动量、质量、风控、流动性四类风格暴露
- `scorecard`：`KEEP / REVIEW / DROP` 决策和对应理由

验证研究输出里现在会附带：

- 每个场景的 `decision`
- 每个场景的 `rationale`
- 更适合做样本外筛选和预设淘汰

## 暂不包含

- 正式多券商实盘闭环
- 正式历史数据库
- 分钟级撮合与高频执行
