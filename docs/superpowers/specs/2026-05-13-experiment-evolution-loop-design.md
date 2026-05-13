# 自进化策略实验最小闭环设计

## 目标

在现有 `策略实验` 流程上增加一个最小可用的自进化闭环：单轮实验完成后，系统基于本轮归因自动生成下一轮候选实验参数，并重新加入实验队列，形成可追踪的实验代次链。

## 范围

本版只做最小闭环：

- 在 `策略实验 / 创建` 中增加自动迭代开关与最大代次数。
- 因子实验成功后，根据本轮归因生成一份下一轮 payload。
- 如果未达到代次上限，则自动重新入队一个新的 `factor_backtest` 任务。
- 在历史页和详情页展示：
  - 当前代次
  - 最大代次
  - 派生来源
  - 派生原因
- 失败/中断的任务继续保留现有 checkpoint 续跑能力。

## 不做的内容

- 不做多分支搜索。
- 不做 Bayesian / evolutionary optimization。
- 不做自动晋升 candidate 或自动切换 champion。
- 不做自动上线到模拟盘。

## 设计

### 1. 任务元数据扩展

`factor_backtest` job payload 和 metadata 增加：

- `auto_iterate: bool`
- `max_generations: int`
- `generation: int`
- `lineage_id: str`
- `parent_job_id: Optional[str]`
- `mutation_reason: Optional[str]`

这样每次自动派生的新实验都能沿着 lineage 被追踪。

### 2. 迭代器

新增独立模块，负责从实验结果生成下一轮 payload。

第一版采用规则驱动：

- 若 `decision == DROP`，停止自动迭代。
- 若 `momentum` 暴露过高且 `UP` 状态下超额为负：
  - 降低 `trend / rel_ret_20 / rel_ret_60 / momentum_acceleration` 中最拥挤因子的 tilt
  - 提高 `breakout_strength / price_volume_confirmation / pullback_resilience`
- 若回撤或风险退出过高：
  - 提高 `drawdown / volatility / volatility_contraction`
- 若流动性与趋势都较弱：
  - 提高 `volume_expansion / liquidity`

该模块同时返回：

- 下一轮参数
- `mutation_reason`
- 人类可读的 `iteration_summary`

### 3. 历史展示

`策略实验 / 历史` 中的 job/event/result 卡片增加：

- `Generation / 代次`
- `Lineage / 进化链`
- `Mutation / 派生原因`

运行中的 job 卡片继续显示进度条；自动派生的任务在标题或详情中明确标记为“自动续跑实验”。

### 4. 详情展示

`策略实验 / 详情` 增加一个小面板：

- 当前代次 / 最大代次
- 是否启用自动迭代
- 派生来源 job
- 本轮驱动下一轮的原因

### 5. 停止条件

自动迭代在以下情况停止：

- `generation >= max_generations`
- 本轮 `decision == DROP`
- 迭代器无法生成有效下一轮参数

## 验证

- 创建页能配置自动迭代。
- 单轮实验成功后，若启用自动迭代，能自动入队下一轮。
- 历史页能看到最新的自动派生实验任务。
- 详情页能看到代次与派生原因。
