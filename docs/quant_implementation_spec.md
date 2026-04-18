# 股票量化平台实施版文档

## 1. 文档说明

### 1.1 文档目标

本文档将系统设计和需求设计进一步收敛为可执行的实施方案，重点覆盖以下四部分：

1. 开发任务清单
2. 模块优先级
3. 数据库表设计
4. API 清单

本文档面向项目经理、技术负责人、后端工程师、前端工程师、数据工程师和测试工程师，用于直接支持排期、分工、开发和联调。

### 1.2 关联文档

- `docs/quant_framework_system_design.md`
- `docs/quant_requirements_design.md`
- `docs/quant_development_plan.md`

### 1.3 实施原则

- 先打通主链路，再做高级能力
- 先交付可运行闭环，再做局部优化
- 先冻结核心对象，再扩展模块细节
- 先保证研究和交易安全，再提高自动化程度

---

## 2. 实施范围

本阶段实施目标是建设一套可投入内部使用的股票量化平台基础版，覆盖以下主链路：

1. 数据接入与数据治理
2. 研究与因子开发
3. 策略管理与回测验证
4. 组合构建与风险校验
5. 模拟盘与实盘建议链路
6. 订单、账户、审批、运维闭环

不在本阶段强制交付的内容：

- 高频交易
- 复杂衍生品
- 跨境清算
- 多资产保证金撮合
- 全自动无人值守大规模生产部署

---

## 3. 模块优先级

## 3.1 P0 模块

P0 表示没有这些模块，整个平台主链路无法成立。

### P0-01 数据平台基础版

- 数据源管理
- 日线行情同步
- 基准指数同步
- 财务数据同步
- 交易日历
- 数据质量校验
- 数据快照

### P0-02 主数据与市场规则

- 证券主数据
- 行业分类
- 公司行为
- 市场规则配置
- 市场规则版本管理

### P0-03 研究与因子平台基础版

- 股票池管理
- 因子注册
- 因子计算
- 因子诊断
- 研究项目管理

### P0-04 策略工厂基础版

- 策略模板
- 策略参数集
- 策略版本冻结
- 策略评分卡

### P0-05 回测与验证中心基础版

- 单期回测
- 滚动回测
- train / validate / test
- walk-forward
- 参数稳定性分析

### P0-06 组合与风险基础版

- Alpha 合成
- 目标组合生成
- 权重约束
- 集中度控制
- 市场规则校验
- 交易风控

### P0-07 订单与账户基础版

- 调仓计划
- 订单意图
- 模拟撮合
- 订单状态机
- 账户快照
- 持仓更新

### P0-08 运维基础版

- 任务调度
- 任务锁
- 日志
- 健康检查
- 告警
- 审计日志

## 3.2 P1 模块

P1 表示平台进入内部生产和团队协作阶段必须补齐的能力。

### P1-01 审批与发布治理

- 策略上线审批
- 风险豁免审批
- 配置发布审批
- 版本回滚

### P1-02 多账户与资金管理

- 多账户绑定
- 资金分配
- 账户分层管理
- 账户绩效对比

### P1-03 报表与归因中心

- 策略收益报表
- 因子归因
- 风格归因
- 交易成本归因
- 风险事件报表

### P1-04 券商集成与对账

- 券商适配器
- 订单回报同步
- 成交回写
- 撤单和改单
- 对账与补偿

### P1-05 开放 API 与权限中心

- API Key
- 角色权限
- Webhook
- 外部系统接入

## 3.3 P2 模块

P2 表示中长期增强能力。

- 机器学习训练平台
- 多资产支持
- 市场中性与多空框架
- 高级优化器
- 事件驱动平台
- 多租户与策略商店

---

## 4. 开发任务清单

以下任务清单按实施顺序组织，建议作为项目 WBS 基础。

## 4.1 阶段一：平台底座与数据层

### T1-01 建立项目基础工程骨架

目标：

- 建立服务目录结构
- 建立配置体系
- 建立环境区分
- 建立日志和异常处理基础设施

交付物：

- 服务启动骨架
- 配置加载模块
- 环境变量规范
- 日志中间件
- 通用异常码

### T1-02 建立统一认证与权限骨架

目标：

- 支持用户、角色、资源的权限模型

交付物：

- 用户表
- 角色表
- 权限表
- 登录鉴权接口

### T1-03 建立数据源接入框架

目标：

- 统一接入市场数据、财务数据、基准数据、交易日历

交付物：

- 数据源配置表
- 数据源适配器接口
- 拉取任务框架
- 重试与熔断机制

### T1-04 建立数据仓库基础表

目标：

- 存储证券主数据、行情、财务、公司行为、交易日历

交付物：

- 数据库初始化脚本
- 核心表结构
- 分区和索引策略

### T1-05 建立数据质量规则引擎

目标：

- 对数据同步结果进行完整性和口径校验

交付物：

- 规则配置表
- 校验执行器
- 数据质量报告

### T1-06 建立数据同步调度链路

目标：

- 支持定时同步和手工补跑

交付物：

- 调度任务
- 任务状态表
- 手工触发接口
- 失败重跑机制

## 4.2 阶段二：研究与策略底座

### T2-01 建立研究项目管理

目标：

- 支持研究项目、研究范围、实验任务管理

交付物：

- 研究项目表
- 研究任务表
- 研究结果快照

### T2-02 建立股票池管理模块

目标：

- 支持全市场、指数、自定义股票池和黑白名单

交付物：

- 股票池表
- 股票池成分表
- 股票池生成服务

### T2-03 建立因子注册与版本管理

目标：

- 支持因子定义、依赖、版本和状态管理

交付物：

- 因子定义表
- 因子版本表
- 因子注册 API

### T2-04 建立因子计算引擎

目标：

- 批量计算日频因子并落库

交付物：

- 因子执行框架
- 因子结果表
- 因子运行日志

### T2-05 建立因子诊断模块

目标：

- 输出因子有效性和稳定性报告

交付物：

- IC 计算
- 分层收益计算
- 覆盖率分析
- 因子诊断报告

### T2-06 建立策略模板与版本管理

目标：

- 管理策略模板、参数集、版本和状态

交付物：

- 策略模板表
- 参数集表
- 策略版本表
- 策略评分卡表

### T2-07 建立组合构建模块

目标：

- 将策略评分转化为目标组合

交付物：

- Alpha 合成器
- 权重求解器
- 组合约束引擎
- 目标持仓输出

## 4.3 阶段三：回测与验证

### T3-01 建立单期回测引擎

目标：

- 对单个策略版本在指定区间运行回测

交付物：

- 回测任务
- 回测结果表
- 回测报告

### T3-02 建立滚动回测引擎

目标：

- 支持多期滚动回测与净值曲线输出

交付物：

- 滚动回测任务
- 日度净值表
- 统计汇总表

### T3-03 建立样本内外验证能力

目标：

- 支持 train / validate / test 切分

交付物：

- 数据切分模块
- 样本内外结果对比

### T3-04 建立 walk-forward 验证能力

目标：

- 支持多窗口滚动验证

交付物：

- 窗口生成器
- 窗口结果表
- 汇总报告

### T3-05 建立参数稳定性与消融分析

目标：

- 支持参数集比较和因子消融

交付物：

- 稳定性评分模块
- 消融实验模块
- 推荐场景输出

## 4.4 阶段四：交易与风控

### T4-01 建立账户中心

目标：

- 管理账户、资金、持仓和约束

交付物：

- 账户表
- 账户快照表
- 持仓快照表

### T4-02 建立调仓计划模块

目标：

- 比较目标组合与当前持仓并生成调仓建议

交付物：

- 调仓计划表
- 调仓明细表
- 调仓生成服务

### T4-03 建立订单意图与订单状态机

目标：

- 支持从建议到订单的完整生命周期管理

交付物：

- 订单意图表
- 订单表
- 状态流转规则

### T4-04 建立模拟撮合与执行引擎

目标：

- 支持 PAPER 环境下的费用、滑点和成交模拟

交付物：

- 撮合器
- 成交表
- 账户更新器

### T4-05 建立交易风控引擎

目标：

- 对订单进行交易前和交易中校验

交付物：

- 风控规则表
- 风控执行器
- 风控事件表

### T4-06 建立市场规则校验器

目标：

- 按市场规则校验订单可执行性

交付物：

- 涨跌停校验
- T+1 校验
- 最小交易单位校验
- 黑白名单校验

## 4.5 阶段五：治理、运维与开放能力

### T5-01 建立审批流引擎

目标：

- 支持策略上线、风险豁免、订单审批、配置发布审批

交付物：

- 审批流表
- 审批节点表
- 审批动作接口

### T5-02 建立配置中心

目标：

- 管理市场、策略、风控和系统配置

交付物：

- 配置表
- 配置版本表
- 配置发布接口

### T5-03 建立运维面板

目标：

- 提供任务、服务、告警、审计和运行状态可视化

交付物：

- 运维首页
- 任务中心
- 告警中心
- 审计中心

### T5-04 建立报表与归因中心

目标：

- 提供策略、订单、账户和风险的统一分析能力

交付物：

- 报表中心
- 指标服务
- 导出能力

### T5-05 建立开放 API 和 Webhook

目标：

- 支持与第三方系统对接

交付物：

- API Key 管理
- 回调订阅
- 外部通知接口

---

## 5. 建议迭代顺序

建议拆成 6 个里程碑。

### M1：平台底座

- T1-01
- T1-02
- T1-03
- T1-04

完成标准：

- 项目可启动
- 可完成基础鉴权
- 可完成数据接入和落库

### M2：研究底座

- T1-05
- T1-06
- T2-01
- T2-02
- T2-03
- T2-04

完成标准：

- 可完成研究项目创建
- 可完成因子计算
- 可完成研究数据调度

### M3：策略与回测

- T2-05
- T2-06
- T2-07
- T3-01
- T3-02

完成标准：

- 可完成策略版本管理
- 可完成目标组合构建
- 可输出标准回测结果

### M4：验证与风控

- T3-03
- T3-04
- T3-05
- T4-05
- T4-06

完成标准：

- 可完成样本外验证
- 可完成稳定性分析
- 可完成交易前风险拦截

### M5：交易闭环

- T4-01
- T4-02
- T4-03
- T4-04

完成标准：

- 可完成模拟盘运行
- 可完成账户与持仓更新
- 可追踪订单生命周期

### M6：治理与运营

- T5-01
- T5-02
- T5-03
- T5-04
- T5-05

完成标准：

- 可完成审批和配置发布
- 可查看任务、审计和告警
- 可输出统一分析报表

---

## 6. 数据库设计总原则

### 6.1 分库分域建议

建议按照业务域拆分 schema：

- `mdm`
  - 主数据与市场规则
- `market_data`
  - 行情、财务、基准、公司行为
- `research`
  - 研究项目、因子、实验、回测、验证
- `strategy`
  - 策略模板、策略版本、组合目标
- `trading`
  - 账户、调仓、订单、成交、对账
- `risk`
  - 风控规则、风险事件、豁免记录
- `platform`
  - 用户、角色、配置、任务、审计、告警

### 6.2 审计字段约定

业务表统一带以下字段：

- `id`
- `created_at`
- `created_by`
- `updated_at`
- `updated_by`
- `is_deleted`

对于版本化对象，统一增加：

- `version`
- `status`
- `effective_from`
- `effective_to`

---

## 7. 数据库表设计

以下只列核心表。字段类型可根据技术栈最终调整。

## 7.1 平台与权限域

### 7.1.1 `platform_user`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| username | 用户名 |
| display_name | 显示名 |
| email | 邮箱 |
| phone | 手机号 |
| password_hash | 密码摘要 |
| status | 状态 |
| last_login_at | 最后登录时间 |
| created_at | 创建时间 |

### 7.1.2 `platform_role`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| role_code | 角色编码 |
| role_name | 角色名称 |
| status | 状态 |
| created_at | 创建时间 |

### 7.1.3 `platform_permission`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| permission_code | 权限编码 |
| permission_name | 权限名称 |
| resource_type | 资源类型 |
| action | 操作类型 |

### 7.1.4 `platform_user_role`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| user_id | 用户 ID |
| role_id | 角色 ID |

### 7.1.5 `platform_config`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| config_key | 配置键 |
| config_scope | 配置范围 |
| config_value | 配置内容 JSON |
| version | 版本 |
| status | 状态 |

### 7.1.6 `platform_task_run`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| task_type | 任务类型 |
| task_name | 任务名称 |
| run_key | 幂等键 |
| status | 任务状态 |
| started_at | 开始时间 |
| finished_at | 结束时间 |
| error_message | 错误信息 |
| payload | 输入参数 JSON |
| result_summary | 结果摘要 JSON |

### 7.1.7 `platform_audit_event`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| event_type | 事件类型 |
| operator_id | 操作人 |
| resource_type | 资源类型 |
| resource_id | 资源 ID |
| action | 操作 |
| detail | 详情 JSON |
| created_at | 创建时间 |

### 7.1.8 `platform_alert_event`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| alert_type | 告警类型 |
| severity | 严重级别 |
| source | 来源 |
| resource_type | 资源类型 |
| resource_id | 资源 ID |
| message | 告警内容 |
| status | 状态 |
| created_at | 创建时间 |

## 7.2 主数据与市场域

### 7.2.1 `mdm_instrument`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| instrument_code | 平台统一代码 |
| ticker | 交易代码 |
| market | 市场 |
| exchange | 交易所 |
| instrument_type | 证券类型 |
| currency | 币种 |
| list_date | 上市日期 |
| delist_date | 退市日期 |
| status | 状态 |
| attributes | 扩展属性 JSON |

### 7.2.2 `mdm_sector_classification`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| instrument_id | 证券 ID |
| classification_type | 分类体系 |
| sector_code | 行业编码 |
| sector_name | 行业名称 |
| effective_from | 生效开始 |
| effective_to | 生效结束 |

### 7.2.3 `mdm_market_rule`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| market | 市场 |
| rule_type | 规则类型 |
| rule_name | 规则名 |
| rule_value | 规则值 JSON |
| version | 版本 |
| status | 状态 |
| effective_from | 生效开始 |
| effective_to | 生效结束 |

### 7.2.4 `mdm_trading_calendar`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| market | 市场 |
| trade_date | 交易日 |
| is_open | 是否开市 |
| open_time | 开盘时间 |
| close_time | 收盘时间 |

## 7.3 市场数据域

### 7.3.1 `market_data_price_bar_daily`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| instrument_id | 证券 ID |
| trade_date | 交易日 |
| open_price | 开盘价 |
| high_price | 最高价 |
| low_price | 最低价 |
| close_price | 收盘价 |
| adj_close_price | 复权收盘价 |
| volume | 成交量 |
| turnover | 成交额 |
| source_id | 数据源 |
| snapshot_id | 快照 ID |

唯一键建议：

- `instrument_id + trade_date + snapshot_id`

### 7.3.2 `market_data_benchmark_bar_daily`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| benchmark_code | 基准代码 |
| market | 市场 |
| trade_date | 交易日 |
| close_price | 收盘点位 |
| return_pct | 日收益 |
| source_id | 数据源 |

### 7.3.3 `market_data_fundamental_snapshot`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| instrument_id | 证券 ID |
| report_date | 报告期 |
| publish_date | 公告日 |
| metric_code | 指标编码 |
| metric_value | 指标值 |
| source_id | 数据源 |
| snapshot_id | 快照 ID |

### 7.3.4 `market_data_corporate_action`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| instrument_id | 证券 ID |
| action_type | 行为类型 |
| ex_date | 除权除息日 |
| effective_date | 生效日 |
| action_value | 行为参数 JSON |

### 7.3.5 `market_data_snapshot`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| snapshot_name | 快照名 |
| snapshot_type | 快照类型 |
| market | 市场 |
| as_of_date | 截止日期 |
| source_summary | 来源摘要 JSON |
| status | 状态 |

### 7.3.6 `market_data_quality_report`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| data_domain | 数据域 |
| market | 市场 |
| check_date | 检查日期 |
| severity | 严重程度 |
| issue_type | 问题类型 |
| issue_count | 问题数量 |
| detail | 明细 JSON |

## 7.4 研究域

### 7.4.1 `research_project`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| project_code | 项目编码 |
| project_name | 项目名称 |
| owner_id | 负责人 |
| market_scope | 市场范围 |
| benchmark_code | 基准 |
| start_date | 研究开始 |
| end_date | 研究结束 |
| status | 状态 |

### 7.4.2 `research_universe_definition`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| project_id | 项目 ID |
| universe_type | 股票池类型 |
| filter_config | 过滤配置 JSON |
| status | 状态 |

### 7.4.3 `research_factor_definition`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| factor_code | 因子编码 |
| factor_name | 因子名称 |
| factor_group | 因子组 |
| market_scope | 市场范围 |
| description | 描述 |
| status | 状态 |

### 7.4.4 `research_factor_version`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| factor_id | 因子 ID |
| version | 版本 |
| formula_config | 公式配置 JSON |
| dependency_config | 依赖配置 JSON |
| status | 状态 |
| effective_from | 生效开始 |

### 7.4.5 `research_factor_value_daily`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| factor_version_id | 因子版本 |
| instrument_id | 证券 ID |
| trade_date | 交易日 |
| factor_value | 因子值 |
| normalized_value | 标准化值 |
| snapshot_id | 数据快照 |

### 7.4.6 `research_factor_diagnostic_report`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| factor_version_id | 因子版本 |
| market | 市场 |
| start_date | 开始日期 |
| end_date | 结束日期 |
| report_type | 报告类型 |
| report_payload | 结果 JSON |

### 7.4.7 `research_experiment_run`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| project_id | 项目 ID |
| experiment_name | 实验名称 |
| scenario_name | 场景名称 |
| parameter_snapshot | 参数快照 JSON |
| status | 状态 |
| started_at | 开始时间 |
| finished_at | 结束时间 |
| result_summary | 结果摘要 JSON |

## 7.5 策略域

### 7.5.1 `strategy_template`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| strategy_code | 策略编码 |
| strategy_name | 策略名 |
| strategy_family | 策略家族 |
| market_scope | 市场范围 |
| description | 描述 |
| owner_id | 负责人 |
| status | 状态 |

### 7.5.2 `strategy_parameter_set`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| strategy_id | 策略 ID |
| param_name | 参数集名称 |
| param_payload | 参数 JSON |
| score | 评分 |
| status | 状态 |

### 7.5.3 `strategy_version`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| strategy_id | 策略 ID |
| version | 版本 |
| parameter_set_id | 参数集 ID |
| factor_version_refs | 因子版本引用 JSON |
| data_snapshot_id | 数据快照 |
| validation_summary | 验证摘要 JSON |
| status | 状态 |

### 7.5.4 `strategy_signal_snapshot`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| strategy_version_id | 策略版本 |
| trade_date | 交易日 |
| instrument_id | 证券 ID |
| signal_score | 信号分数 |
| direction | 方向 |
| reason | 原因 |
| rank_no | 排名 |

### 7.5.5 `strategy_portfolio_target`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| strategy_version_id | 策略版本 |
| trade_date | 交易日 |
| instrument_id | 证券 ID |
| target_weight | 目标权重 |
| target_qty | 目标数量 |
| target_notional | 目标金额 |
| diagnostics | 诊断 JSON |

## 7.6 回测与验证域

### 7.6.1 `research_backtest_run`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| strategy_version_id | 策略版本 |
| backtest_type | 回测类型 |
| start_date | 开始日期 |
| end_date | 结束日期 |
| benchmark_code | 基准 |
| status | 状态 |
| result_summary | 汇总 JSON |

### 7.6.2 `research_backtest_nav_daily`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| backtest_run_id | 回测任务 |
| trade_date | 交易日 |
| nav | 净值 |
| benchmark_nav | 基准净值 |
| period_return | 当期收益 |
| turnover | 换手 |
| fees | 费用 |

### 7.6.3 `research_validation_run`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| strategy_version_id | 策略版本 |
| validation_type | 验证类型 |
| window_config | 窗口配置 JSON |
| status | 状态 |
| result_summary | 结果 JSON |

### 7.6.4 `research_validation_window_result`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| validation_run_id | 验证任务 |
| window_index | 窗口编号 |
| scenario_name | 场景名 |
| train_return | 样本内收益 |
| validate_return | 验证收益 |
| test_return | 测试收益 |
| metrics | 结果 JSON |

## 7.7 交易域

### 7.7.1 `trading_account`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| account_code | 账户编码 |
| account_name | 账户名称 |
| market | 市场 |
| broker_code | 券商 |
| account_type | 账户类型 |
| currency | 币种 |
| status | 状态 |
| constraint_payload | 约束 JSON |

### 7.7.2 `trading_account_snapshot`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| account_id | 账户 ID |
| snapshot_time | 快照时间 |
| total_asset | 总资产 |
| cash | 现金 |
| buying_power | 可用资金 |
| market_value | 持仓市值 |
| pnl | 盈亏 |

### 7.7.3 `trading_position_snapshot`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| account_snapshot_id | 账户快照 |
| instrument_id | 证券 ID |
| qty | 持仓数量 |
| available_qty | 可卖数量 |
| avg_cost | 平均成本 |
| market_price | 市价 |
| market_value | 市值 |
| pnl | 盈亏 |

### 7.7.4 `trading_rebalance_plan`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| account_id | 账户 ID |
| strategy_version_id | 策略版本 |
| trade_date | 交易日 |
| status | 状态 |
| plan_summary | 摘要 JSON |

### 7.7.5 `trading_rebalance_plan_item`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| plan_id | 调仓计划 |
| instrument_id | 证券 ID |
| current_qty | 当前数量 |
| target_qty | 目标数量 |
| delta_qty | 变化数量 |
| target_weight | 目标权重 |
| action | 动作 |

### 7.7.6 `trading_order_intent`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| account_id | 账户 ID |
| plan_id | 调仓计划 |
| instrument_id | 证券 ID |
| side | 买卖方向 |
| order_type | 订单类型 |
| qty | 数量 |
| price | 价格 |
| source | 来源 |
| requires_approval | 是否需审批 |
| status | 状态 |

### 7.7.7 `trading_order`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| order_intent_id | 订单意图 |
| broker_order_id | 券商订单号 |
| account_id | 账户 |
| instrument_id | 证券 |
| side | 买卖 |
| qty | 下单数量 |
| filled_qty | 已成交数量 |
| avg_fill_price | 成交均价 |
| status | 状态 |
| submitted_at | 提交时间 |
| finished_at | 结束时间 |

### 7.7.8 `trading_execution_fill`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| order_id | 订单 ID |
| fill_time | 成交时间 |
| fill_qty | 成交数量 |
| fill_price | 成交价格 |
| commission | 手续费 |
| taxes | 税费 |
| slippage_bps | 滑点 |

### 7.7.9 `trading_reconciliation_record`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| account_id | 账户 ID |
| reconcile_date | 对账日期 |
| status | 状态 |
| diff_summary | 差异摘要 JSON |

## 7.8 风险域

### 7.8.1 `risk_rule`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| rule_code | 规则编码 |
| rule_name | 规则名 |
| rule_scope | 作用范围 |
| rule_type | 规则类型 |
| rule_payload | 规则配置 JSON |
| severity | 严重级别 |
| status | 状态 |

### 7.8.2 `risk_check_run`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| check_type | 检查类型 |
| source_type | 来源类型 |
| source_id | 来源 ID |
| status | 状态 |
| summary | 汇总 JSON |
| created_at | 创建时间 |

### 7.8.3 `risk_event`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| check_run_id | 风险检查任务 |
| rule_id | 规则 ID |
| severity | 严重级别 |
| resource_type | 资源类型 |
| resource_id | 资源 ID |
| event_code | 事件编码 |
| event_message | 事件说明 |
| action_taken | 采取动作 |
| status | 状态 |

### 7.8.4 `risk_exemption_request`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| resource_type | 资源类型 |
| resource_id | 资源 ID |
| rule_id | 规则 ID |
| reason | 豁免原因 |
| applicant_id | 申请人 |
| status | 状态 |

## 7.9 审批域

### 7.9.1 `platform_approval_request`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| approval_type | 审批类型 |
| resource_type | 资源类型 |
| resource_id | 资源 ID |
| applicant_id | 申请人 |
| status | 状态 |
| current_node | 当前节点 |

### 7.9.2 `platform_approval_action`

| 字段 | 说明 |
|---|---|
| id | 主键 |
| request_id | 审批单 |
| node_code | 节点编码 |
| approver_id | 审批人 |
| action | 动作 |
| comment | 备注 |
| action_time | 操作时间 |

---

## 8. API 设计原则

### 8.1 基础原则

- 所有写接口必须带审计信息
- 所有关键异步任务接口返回任务 ID
- 所有查询接口支持分页、筛选和排序
- 所有批量任务接口支持幂等键
- 所有生产类接口必须进行权限和审批校验

### 8.2 响应规范

建议统一响应结构：

```json
{
  "code": "0",
  "message": "success",
  "data": {},
  "request_id": "xxx"
}
```

异步任务响应建议：

```json
{
  "code": "0",
  "message": "accepted",
  "data": {
    "task_id": "task_xxx",
    "status": "PENDING"
  }
}
```

---

## 9. API 清单

以下 API 按业务域分组。路径仅作为建议。

## 9.1 认证与权限 API

### 9.1.1 登录

- `POST /api/v1/auth/login`

用途：

- 用户登录

### 9.1.2 获取当前用户

- `GET /api/v1/auth/me`

### 9.1.3 查询用户列表

- `GET /api/v1/users`

### 9.1.4 创建用户

- `POST /api/v1/users`

### 9.1.5 分配角色

- `POST /api/v1/users/{user_id}/roles`

## 9.2 数据平台 API

### 9.2.1 查询数据源列表

- `GET /api/v1/data-sources`

### 9.2.2 创建数据源

- `POST /api/v1/data-sources`

### 9.2.3 触发数据同步

- `POST /api/v1/data-sync/jobs`

请求体建议：

```json
{
  "job_type": "DAILY_MARKET_SYNC",
  "market": "CN",
  "start_date": "2026-01-01",
  "end_date": "2026-03-31",
  "idempotency_key": "sync-cn-20260331"
}
```

### 9.2.4 查询同步任务

- `GET /api/v1/data-sync/jobs`

### 9.2.5 查询数据质量报告

- `GET /api/v1/data-quality/reports`

### 9.2.6 查询行情数据

- `GET /api/v1/market-data/prices`

### 9.2.7 查询财务快照

- `GET /api/v1/market-data/fundamentals`

## 9.3 主数据与市场规则 API

### 9.3.1 查询证券

- `GET /api/v1/instruments`

### 9.3.2 创建或更新证券

- `POST /api/v1/instruments`

### 9.3.3 查询交易日历

- `GET /api/v1/calendars`

### 9.3.4 查询市场规则

- `GET /api/v1/market-rules`

### 9.3.5 发布市场规则版本

- `POST /api/v1/market-rules/publish`

## 9.4 研究与因子 API

### 9.4.1 创建研究项目

- `POST /api/v1/research/projects`

### 9.4.2 查询研究项目

- `GET /api/v1/research/projects`

### 9.4.3 创建股票池定义

- `POST /api/v1/research/universes`

### 9.4.4 注册因子

- `POST /api/v1/research/factors`

### 9.4.5 创建因子版本

- `POST /api/v1/research/factors/{factor_id}/versions`

### 9.4.6 触发因子计算

- `POST /api/v1/research/factor-runs`

### 9.4.7 查询因子值

- `GET /api/v1/research/factor-values`

### 9.4.8 查询因子诊断报告

- `GET /api/v1/research/factor-diagnostics`

## 9.5 策略 API

### 9.5.1 创建策略模板

- `POST /api/v1/strategies`

### 9.5.2 查询策略列表

- `GET /api/v1/strategies`

### 9.5.3 创建参数集

- `POST /api/v1/strategies/{strategy_id}/parameter-sets`

### 9.5.4 生成策略版本

- `POST /api/v1/strategies/{strategy_id}/versions`

### 9.5.5 查询策略版本

- `GET /api/v1/strategy-versions`

### 9.5.6 生成策略信号

- `POST /api/v1/strategy-versions/{version_id}/signals`

### 9.5.7 查询信号快照

- `GET /api/v1/strategy-signals`

### 9.5.8 生成目标组合

- `POST /api/v1/strategy-versions/{version_id}/portfolio-targets`

## 9.6 回测与验证 API

### 9.6.1 发起单次回测

- `POST /api/v1/backtests`

### 9.6.2 查询回测任务

- `GET /api/v1/backtests`

### 9.6.3 查询净值曲线

- `GET /api/v1/backtests/{backtest_id}/nav`

### 9.6.4 发起验证任务

- `POST /api/v1/validations`

### 9.6.5 查询验证任务

- `GET /api/v1/validations`

### 9.6.6 查询验证窗口结果

- `GET /api/v1/validations/{validation_id}/windows`

## 9.7 账户与交易 API

### 9.7.1 创建账户

- `POST /api/v1/accounts`

### 9.7.2 查询账户列表

- `GET /api/v1/accounts`

### 9.7.3 查询账户快照

- `GET /api/v1/accounts/{account_id}/snapshots`

### 9.7.4 查询持仓

- `GET /api/v1/accounts/{account_id}/positions`

### 9.7.5 生成调仓计划

- `POST /api/v1/rebalance-plans`

请求体建议：

```json
{
  "account_id": "acct_cn_alpha",
  "strategy_version_id": "sv_20260331_01",
  "trade_date": "2026-03-31"
}
```

### 9.7.6 查询调仓计划

- `GET /api/v1/rebalance-plans`

### 9.7.7 生成订单意图

- `POST /api/v1/order-intents`

### 9.7.8 查询订单意图

- `GET /api/v1/order-intents`

### 9.7.9 提交订单

- `POST /api/v1/orders/submit`

### 9.7.10 撤单

- `POST /api/v1/orders/{order_id}/cancel`

### 9.7.11 查询订单列表

- `GET /api/v1/orders`

### 9.7.12 查询成交列表

- `GET /api/v1/fills`

## 9.8 风险 API

### 9.8.1 查询风险规则

- `GET /api/v1/risk/rules`

### 9.8.2 创建风险规则

- `POST /api/v1/risk/rules`

### 9.8.3 触发风险检查

- `POST /api/v1/risk/check-runs`

### 9.8.4 查询风险事件

- `GET /api/v1/risk/events`

### 9.8.5 提交豁免申请

- `POST /api/v1/risk/exemptions`

## 9.9 审批 API

### 9.9.1 发起审批

- `POST /api/v1/approvals`

### 9.9.2 查询审批单

- `GET /api/v1/approvals`

### 9.9.3 审批通过

- `POST /api/v1/approvals/{request_id}/approve`

### 9.9.4 审批拒绝

- `POST /api/v1/approvals/{request_id}/reject`

## 9.10 运维与告警 API

### 9.10.1 查询系统健康

- `GET /api/v1/ops/health`

### 9.10.2 查询任务运行

- `GET /api/v1/ops/tasks`

### 9.10.3 重跑任务

- `POST /api/v1/ops/tasks/{task_id}/rerun`

### 9.10.4 释放任务锁

- `POST /api/v1/ops/tasks/{task_id}/release-lock`

### 9.10.5 查询审计日志

- `GET /api/v1/ops/audit-events`

### 9.10.6 查询告警

- `GET /api/v1/ops/alerts`

## 9.11 报表 API

### 9.11.1 查询策略收益报表

- `GET /api/v1/reports/strategy-performance`

### 9.11.2 查询因子诊断报表

- `GET /api/v1/reports/factor-diagnostics`

### 9.11.3 查询账户绩效报表

- `GET /api/v1/reports/account-performance`

### 9.11.4 查询风险报表

- `GET /api/v1/reports/risk-summary`

### 9.11.5 导出报表

- `POST /api/v1/reports/export`

---

## 10. 前后端联调建议

### 10.1 第一批优先联调接口

- 登录
- 查询研究项目
- 查询策略
- 发起回测
- 查询回测结果
- 查询账户
- 生成调仓计划
- 查询订单
- 查询任务运行

### 10.2 第二批联调接口

- 因子计算
- 验证任务
- 风险检查
- 审批流
- 报表导出

---

## 11. 测试与验收建议

### 11.1 单模块验收

每个模块至少需要：

- 接口测试
- 数据落库测试
- 权限测试
- 异常路径测试

### 11.2 主链路验收

至少验收以下闭环：

1. 数据同步 -> 数据质量检查 -> 数据落库
2. 研究项目 -> 因子计算 -> 策略版本 -> 回测
3. 策略版本 -> 目标组合 -> 调仓计划 -> 订单意图
4. 订单提交 -> 成交回写 -> 账户更新 -> 对账
5. 风险命中 -> 审批处理 -> 审计记录

### 11.3 上线前验收

- 全链路冒烟
- 权限检查
- 回滚演练
- 告警联调
- 任务重跑演练

---

## 12. 结论

这份实施版文档的作用不是再描述一次“系统应该长什么样”，而是把平台建设具体拆成可执行事项。团队可以直接基于这份文档完成：

- 里程碑排期
- 模块负责人分配
- 数据库建模
- 后端接口开发
- 前后端联调
- 测试验收设计

如果后续进入更细的设计阶段，建议在本文档基础上继续拆出：

- 数据库 ER 图文档
- API 字段级详细定义文档
- 风险规则实施细则
- 券商适配实施细则
- 回测与验证指标口径文档
