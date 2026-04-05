# Framework Playbook

这份文档的目标不是“换框架”，而是把成熟开源量化框架里已经被验证过的分层思路，映射到当前项目里最该补的部分。

## 1. 数据与研究底座

- [Microsoft Qlib](https://github.com/microsoft/qlib)
  强项是研究工作流的标准化，强调数据集、特征、模型、组合和回测的一体化流水线。
- [AlphaLens](https://github.com/quantopian/alphalens)
  强项是因子诊断，适合补现在项目里还比较弱的 `IC / RankIC / 分层收益 / 换手 / 因子衰减` 分析。

对当前项目的直接借鉴：
- 把 `prices / benchmark / fundamentals / corporate actions` 做成持久化数据层，而不是运行时即抓即算。
- 因子研究要单独有一层报表，不和下单建议混在一起。
- 对每个因子都保留样本内、样本外和滚动稳定性诊断。

## 2. 回测与组合层

- [LEAN](https://github.com/QuantConnect/Lean)
  强项是事件驱动运行时、资产统一抽象、回测与实盘共享接口。
- [Zipline Reloaded](https://github.com/stefan-jansen/zipline-reloaded)
  强项是日线回测、数据 bundle、pipeline 风格的研究抽象。
- [backtrader](https://www.backtrader.com/)
  强项是策略和执行层快速试验，适合验证组合与成交模型。

对当前项目的直接借鉴：
- 回测、模拟、实盘要共享同一套订单和持仓语义。
- 组合层要独立成 `Alpha -> PortfolioConstruction -> RiskOverlay -> ExecutionModel`。
- 滑点、费用、最小交易单位、公司行为不能只做轻量标签，必须进入收益归因。

## 3. 全市场扫描与生产化

成熟框架的共同点不是“策略更神”，而是：
- 先把数据缓存和增量更新做好。
- 再把全市场横截面研究和每日生产扫描拆开。
- 最后再把研究结论接到账户和执行。

对当前项目的直接借鉴：
- 研究运行和生产运行要产出可复查 artifact。
- 全市场扫描需要本地缓存、失败重试、分批抓取和断点恢复。
- 候选池输出不应只有最终买入名单，还要保留 `top alpha`, `sector leaders`, `beta buckets`, `benchmark-relative` 这些中间层。

## 4. 当前项目建议路线

### 近阶段

- 做本地日线仓库，先覆盖 A 股和美股普通股。
- 做全市场 beta / alpha / 行业分层报表。
- 做 rolling backtest 与样本外验证。
- 做换手、容量、风格暴露和基准偏离分析。

### 中阶段

- 引入正式 fundamentals 源，替换当前代理版字段。
- 做 benchmark constituent 历史快照，而不只是最新 proxy。
- 做组合约束配置化和策略参数版本化。

### 长阶段

- 接入真实券商和订单同步。
- 把运行时改成增量更新 + 定时任务。
- 把 agent 从“解释和建议”进一步升级到“研究诊断和异常归因”。
