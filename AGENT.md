# AGENT.md

## 1. 项目定位

本项目是一个面向 A 股和美股的股票量化平台，当前重点是中低频、long-only 的研究、回测、模拟盘和实盘建议链路。

系统设计、模块规划和建设路线请优先参考：

- `docs/quant_framework_system_design.md`
- `docs/framework_playbook.md`
- `docs/strategy_map.md`

`AGENT.md` 只定义协作约束，不重复展开系统设计正文。

## 2. 工作目标

参与本项目时，优先保证以下目标：

1. 正确性优先于速度
2. 风险控制优先于功能堆叠
3. 可追溯优先于“先跑起来”
4. 可解释优先于黑盒化
5. 尽量复用现有抽象，不随意绕过分层

## 3. 核心边界

### 3.1 研究、风控、执行分层

不要把以下职责混在一起：

- 研究层：股票池、因子、评分、验证、归因
- 策略层：信号、目标仓位、调仓计划
- 风控层：约束校验、违规拦截、风险提示
- 执行层：订单意图、成交模拟、券商路由、账户更新
- 展示层：CLI、Web、报表、运维页

### 3.2 Agent 的职责边界

当前项目中的 Agent 主要负责：

- 研究分析
- 策略提案
- 结果复核

不要让 Agent 直接承担以下职责：

- 最终风险放行
- 绕过执行模式限制
- 直接提交不受控的实盘订单

风险审批和订单提交控制必须保留在 Agent 之外。

## 4. 修改原则

### 4.1 改策略时

如果修改策略逻辑，通常需要同时检查这些内容：

- `src/stock_quantification/pipeline.py`
- `src/stock_quantification/engine.py`
- `src/stock_quantification/strategy_catalog.py`
- `docs/strategy_map.md`
- 对应测试

需要同步考虑：

- 适用市场
- 因子定义
- 权重逻辑
- 调仓频率与换手
- 集中度和暴露风险
- 报表输出是否仍可解释

### 4.2 改运行时或执行逻辑时

涉及 `runtime.py`、`broker.py`、`local_paper.py`、`state.py` 的改动，必须同时考虑：

- `BACKTEST`
- `PAPER`
- `LIVE`

至少核对这些影响：

- 滑点
- 费用
- 订单审批语义
- 状态更新方式
- 部分成交
- 多账户隔离
- 幂等与去重

### 4.3 改风控时

风控逻辑必须保守、显式、可测试。

不要：

- 为了让策略通过而放松风控
- 把市场规则写死在策略里
- 把风控逻辑偷偷塞进 UI 或脚本层

### 4.4 改 Web 或报表时

Web 和报表层只负责展示、触发和归档，不应重新定义核心交易语义。

不要把核心组合、风控或执行逻辑放进 `web.py`。

## 5. 禁止事项

以下行为默认禁止：

- 绕过风险校验
- 绕过 advisory / auto / live 语义边界
- 引入未来函数或样本泄漏
- 用静默降级掩盖数据缺失问题
- 把券商逻辑扩散到整个代码库
- 直接硬编码账户、凭证或密钥
- 默认新增不受控自动交易路径
- 把 A 股和美股规则混用

## 6. 倾向做法

优先采用：

- 小而清晰的函数
- 明确的数据结构和类型
- 可复现的输出
- 增量式重构
- 紧贴改动点的测试
- 解释性强的策略和报表

避免采用：

- 无边界的大重构
- 隐式全局状态
- 到处散落的 magic number
- CLI / Web / 核心逻辑相互穿透
- 重复造一套与现有接口平行的抽象

## 7. 测试要求

只要改动影响以下任一内容，就应补测试或更新测试：

- 策略逻辑
- 风控逻辑
- 执行语义
- Agent 编排
- 回测与验证结果
- 报表输出结构

常用命令：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m unittest tests.test_agents -v
PYTHONPATH=src python3 -m unittest tests.test_platform -v
PYTHONPATH=src python3 -m unittest tests.test_backtest -v
PYTHONPATH=src python3 -m unittest tests.test_validation -v
```

如果改动横跨策略、执行或风控，尽量补一条端到端测试。

## 8. 文档同步要求

以下变更应同步更新文档：

- 新增或删除策略
- 修改市场支持范围
- 修改回测/验证口径
- 修改运行模式语义
- 修改重要输出字段

优先检查：

- `README.md`
- `docs/strategy_map.md`
- `docs/quant_framework_system_design.md`

## 9. 完成标准

一个改动可以认为基本完成，当且仅当：

- 逻辑放在正确的分层里
- 没有引入新的不安全交易路径
- 相关测试通过或已补齐
- 相关文档已同步
- 输出结果仍然可解释、可复查、可追踪
