# 股票量化平台接口字段级定义文档

## 1. 文档说明

### 1.1 文档目标

本文档在实施版 API 清单基础上，进一步明确核心接口的请求字段、响应字段、校验规则、分页规则、鉴权要求和异步任务规范，作为 OpenAPI 文档设计和前后端联调依据。

### 1.2 关联文档

- `docs/quant_implementation_spec.md`
- `docs/quant_er_model.md`

### 1.3 范围说明

本文档优先覆盖 P0 和 P1 主链路接口：

- 认证与权限
- 数据同步
- 研究与因子
- 策略与回测
- 账户与交易
- 风险与审批
- 运维与报表

---

## 2. 通用接口规范

## 2.1 基础 URL

建议统一前缀：

- `/api/v1`

## 2.2 鉴权方式

建议：

- 用户接口：`Bearer Token`
- 系统接口：`API Key + Signature`

### 请求头建议

| Header | 必填 | 说明 |
|---|---|---|
| Authorization | 是 | `Bearer <token>` |
| X-Request-Id | 否 | 请求追踪 ID |
| X-Idempotency-Key | 否 | 幂等键，写接口推荐必传 |
| Content-Type | 是 | `application/json` |

## 2.3 通用响应结构

```json
{
  "code": "0",
  "message": "success",
  "data": {},
  "request_id": "req_123456"
}
```

字段定义：

| 字段 | 类型 | 说明 |
|---|---|---|
| code | string | 返回码，`0` 表示成功 |
| message | string | 返回消息 |
| data | object | 返回数据 |
| request_id | string | 请求追踪 ID |

## 2.4 分页结构

```json
{
  "items": [],
  "page_no": 1,
  "page_size": 20,
  "total": 100,
  "has_next": true
}
```

字段定义：

| 字段 | 类型 | 说明 |
|---|---|---|
| items | array | 当前页数据 |
| page_no | integer | 页码，从 1 开始 |
| page_size | integer | 每页条数 |
| total | integer | 总条数 |
| has_next | boolean | 是否有下一页 |

## 2.5 异步任务返回结构

```json
{
  "task_id": "task_001",
  "task_type": "BACKTEST_RUN",
  "status": "PENDING"
}
```

字段定义：

| 字段 | 类型 | 说明 |
|---|---|---|
| task_id | string | 任务 ID |
| task_type | string | 任务类型 |
| status | string | 任务状态 |

## 2.6 错误码建议

| 错误码 | 说明 |
|---|---|
| `AUTH_001` | 未登录 |
| `AUTH_002` | 无权限 |
| `REQ_001` | 参数缺失 |
| `REQ_002` | 参数格式错误 |
| `DATA_001` | 数据不存在 |
| `DATA_002` | 数据状态非法 |
| `TASK_001` | 重复任务 |
| `TASK_002` | 任务运行中 |
| `RISK_001` | 风险校验失败 |
| `APPROVAL_001` | 审批未通过 |
| `ORDER_001` | 订单状态非法 |
| `SYS_001` | 系统内部错误 |

---

## 3. 认证与权限接口

## 3.1 登录

### `POST /api/v1/auth/login`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| username | string | 是 | 用户名 |
| password | string | 是 | 密码 |

响应体 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| access_token | string | 访问令牌 |
| refresh_token | string | 刷新令牌 |
| expires_in | integer | 过期秒数 |
| user | object | 当前用户信息 |

`user` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 用户 ID |
| username | string | 用户名 |
| display_name | string | 显示名 |
| roles | array[string] | 角色列表 |

校验规则：

- 用户名不能为空
- 密码不能为空

## 3.2 获取当前用户

### `GET /api/v1/auth/me`

响应体 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 用户 ID |
| username | string | 用户名 |
| display_name | string | 显示名 |
| email | string | 邮箱 |
| roles | array[string] | 角色列表 |
| permissions | array[string] | 权限列表 |

---

## 4. 数据平台接口

## 4.1 创建数据源

### `POST /api/v1/data-sources`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| source_code | string | 是 | 数据源编码 |
| source_name | string | 是 | 数据源名称 |
| source_type | string | 是 | `MARKET` / `FUNDAMENTAL` / `BROKER` / `CALENDAR` |
| market_scope | array[string] | 否 | 支持市场 |
| config | object | 是 | 配置对象 |
| priority | integer | 否 | 优先级，越小越高 |
| status | string | 否 | 默认 `ACTIVE` |

响应体 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| source_id | string | 数据源 ID |
| source_code | string | 数据源编码 |
| status | string | 状态 |

## 4.2 触发数据同步

### `POST /api/v1/data-sync/jobs`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| job_type | string | 是 | 任务类型 |
| market | string | 否 | `CN` / `US` |
| start_date | string(date) | 否 | 起始日期 |
| end_date | string(date) | 否 | 结束日期 |
| instrument_codes | array[string] | 否 | 指定证券列表 |
| snapshot_name | string | 否 | 快照名 |
| force_full_sync | boolean | 否 | 是否全量同步 |

响应体 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| task_id | string | 任务 ID |
| task_type | string | 任务类型 |
| status | string | 任务状态 |

校验规则：

- `job_type` 必填
- `market`、`instrument_codes` 至少二选一或由 `job_type` 决定默认范围
- `start_date <= end_date`

## 4.3 查询数据质量报告

### `GET /api/v1/data-quality/reports`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| data_domain | string | 否 | 数据域 |
| market | string | 否 | 市场 |
| check_date | string(date) | 否 | 检查日期 |
| severity | string | 否 | 严重级别 |
| page_no | integer | 否 | 页码 |
| page_size | integer | 否 | 每页条数 |

返回项 `items[]`：

| 字段 | 类型 | 说明 |
|---|---|---|
| report_id | string | 报告 ID |
| data_domain | string | 数据域 |
| market | string | 市场 |
| check_date | string(date) | 检查日期 |
| severity | string | 严重级别 |
| issue_type | string | 问题类型 |
| issue_count | integer | 问题数量 |
| detail | object | 明细 |

---

## 5. 研究与因子接口

## 5.1 创建研究项目

### `POST /api/v1/research/projects`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| project_code | string | 是 | 项目编码 |
| project_name | string | 是 | 项目名称 |
| market_scope | array[string] | 是 | 市场范围 |
| benchmark_code | string | 否 | 基准代码 |
| start_date | string(date) | 是 | 研究起始 |
| end_date | string(date) | 是 | 研究结束 |
| description | string | 否 | 描述 |

响应体 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| project_id | string | 项目 ID |
| status | string | 状态 |

## 5.2 创建股票池定义

### `POST /api/v1/research/universes`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| project_id | string | 是 | 项目 ID |
| universe_type | string | 是 | `ALL` / `INDEX` / `CUSTOM` / `SCREENED` |
| benchmark_code | string | 否 | 指数股票池时使用 |
| instrument_codes | array[string] | 否 | 自定义股票池时使用 |
| filter_config | object | 否 | 过滤条件 |

`filter_config` 建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| min_listed_days | integer | 最小上市天数 |
| min_average_turnover | number | 最小平均成交额 |
| min_price | number | 最低价格 |
| max_price | number | 最高价格 |
| exclude_st | boolean | 是否剔除 ST |
| allowed_instrument_types | array[string] | 允许证券类型 |

## 5.3 注册因子

### `POST /api/v1/research/factors`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| factor_code | string | 是 | 因子编码 |
| factor_name | string | 是 | 因子名称 |
| factor_group | string | 是 | 因子组 |
| market_scope | array[string] | 是 | 适用市场 |
| description | string | 否 | 描述 |

响应体 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| factor_id | string | 因子 ID |
| status | string | 状态 |

## 5.4 创建因子版本

### `POST /api/v1/research/factors/{factor_id}/versions`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| version | string | 是 | 版本号 |
| formula_config | object | 是 | 公式配置 |
| dependency_config | object | 是 | 依赖配置 |
| normalization_config | object | 否 | 标准化配置 |
| missing_value_policy | string | 否 | 缺失值策略 |

`formula_config` 示例：

```json
{
  "type": "EXPRESSION",
  "expression": "(ret_20 * 0.6) + (ret_60 * 0.4)"
}
```

## 5.5 触发因子计算

### `POST /api/v1/research/factor-runs`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| factor_version_id | string | 是 | 因子版本 |
| market | string | 是 | 市场 |
| start_date | string(date) | 是 | 开始日期 |
| end_date | string(date) | 是 | 结束日期 |
| universe_id | string | 否 | 股票池定义 |
| snapshot_id | string | 否 | 数据快照 |

返回：

- 异步任务结构

## 5.6 查询因子值

### `GET /api/v1/research/factor-values`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| factor_version_id | string | 是 | 因子版本 |
| trade_date | string(date) | 否 | 交易日 |
| instrument_code | string | 否 | 证券代码 |
| page_no | integer | 否 | 页码 |
| page_size | integer | 否 | 页大小 |

返回项：

| 字段 | 类型 | 说明 |
|---|---|---|
| instrument_code | string | 证券代码 |
| trade_date | string(date) | 交易日 |
| factor_value | number | 原始因子值 |
| normalized_value | number | 标准化值 |

## 5.7 查询因子诊断报告

### `GET /api/v1/research/factor-diagnostics`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| factor_version_id | string | 是 | 因子版本 |
| report_type | string | 否 | 报告类型 |

返回 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| report_id | string | 报告 ID |
| factor_version_id | string | 因子版本 |
| report_type | string | 报告类型 |
| summary | object | 报告摘要 |
| payload | object | 报告明细 |

---

## 6. 策略与回测接口

## 6.1 创建策略模板

### `POST /api/v1/strategies`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| strategy_code | string | 是 | 策略编码 |
| strategy_name | string | 是 | 策略名称 |
| strategy_family | string | 是 | 策略家族 |
| market_scope | array[string] | 是 | 市场范围 |
| description | string | 否 | 描述 |

## 6.2 创建参数集

### `POST /api/v1/strategies/{strategy_id}/parameter-sets`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| param_name | string | 是 | 参数集名称 |
| param_payload | object | 是 | 参数 JSON |
| notes | string | 否 | 备注 |

`param_payload` 建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| top_n | integer | 选股数量 |
| rebalance_freq | string | 调仓频率 |
| holding_days | integer | 持有周期 |
| alpha_weights | object | 因子权重 |
| max_position_weight | number | 单票上限 |
| max_sector_weight | number | 行业上限 |
| turnover_cap | number | 换手上限 |
| cash_buffer | number | 现金缓冲 |

## 6.3 生成策略版本

### `POST /api/v1/strategies/{strategy_id}/versions`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| version | string | 是 | 版本号 |
| parameter_set_id | string | 是 | 参数集 ID |
| factor_version_refs | array[string] | 是 | 因子版本列表 |
| data_snapshot_id | string | 是 | 数据快照 |
| notes | string | 否 | 备注 |

响应体：

| 字段 | 类型 | 说明 |
|---|---|---|
| strategy_version_id | string | 策略版本 ID |
| status | string | 状态 |

## 6.4 生成策略信号

### `POST /api/v1/strategy-versions/{version_id}/signals`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| trade_date | string(date) | 是 | 交易日 |
| universe_id | string | 否 | 股票池 |
| force_refresh | boolean | 否 | 强制重算 |

返回：

- 异步任务结构

## 6.5 查询策略信号

### `GET /api/v1/strategy-signals`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| strategy_version_id | string | 是 | 策略版本 |
| trade_date | string(date) | 是 | 交易日 |
| page_no | integer | 否 | 页码 |
| page_size | integer | 否 | 页大小 |

返回项：

| 字段 | 类型 | 说明 |
|---|---|---|
| instrument_code | string | 证券代码 |
| signal_score | number | 信号分数 |
| direction | string | 方向 |
| rank_no | integer | 排名 |
| reason | string | 原因 |

## 6.6 生成目标组合

### `POST /api/v1/strategy-versions/{version_id}/portfolio-targets`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| trade_date | string(date) | 是 | 交易日 |
| account_scope | string | 否 | 账户范围 |
| optimization_mode | string | 否 | `EQUAL` / `SCORE` / `BENCHMARK` / `OPTIMIZER` |

返回：

- 异步任务结构

## 6.7 发起回测

### `POST /api/v1/backtests`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| strategy_version_id | string | 是 | 策略版本 |
| backtest_type | string | 是 | `SINGLE` / `ROLLING` |
| start_date | string(date) | 是 | 开始日期 |
| end_date | string(date) | 是 | 结束日期 |
| benchmark_code | string | 否 | 基准 |
| initial_cash | number | 否 | 初始资金 |
| fee_profile | object | 否 | 成本模型 |
| slippage_profile | object | 否 | 滑点模型 |

返回：

- 异步任务结构

## 6.8 查询回测列表

### `GET /api/v1/backtests`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| strategy_version_id | string | 否 | 策略版本 |
| backtest_type | string | 否 | 回测类型 |
| status | string | 否 | 状态 |

返回项：

| 字段 | 类型 | 说明 |
|---|---|---|
| backtest_id | string | 回测 ID |
| strategy_version_id | string | 策略版本 |
| start_date | string(date) | 开始日期 |
| end_date | string(date) | 结束日期 |
| total_return | number | 总收益 |
| max_drawdown | number | 最大回撤 |
| sharpe_ratio | number | 夏普 |
| status | string | 状态 |

## 6.9 查询回测净值曲线

### `GET /api/v1/backtests/{backtest_id}/nav`

返回 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| backtest_id | string | 回测 ID |
| daily | array[object] | 日度净值 |

`daily[]` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| trade_date | string(date) | 交易日 |
| nav | number | 净值 |
| benchmark_nav | number | 基准净值 |
| period_return | number | 当期收益 |
| turnover | number | 换手 |
| fees | number | 费用 |

## 6.10 发起验证任务

### `POST /api/v1/validations`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| strategy_version_id | string | 是 | 策略版本 |
| validation_type | string | 是 | `TVT` / `WALK_FORWARD` / `STABILITY` / `ABLATION` |
| start_date | string(date) | 是 | 开始日期 |
| end_date | string(date) | 是 | 结束日期 |
| window_config | object | 否 | 窗口配置 |
| scenario_config | object | 否 | 场景配置 |

返回：

- 异步任务结构

## 6.11 查询验证窗口结果

### `GET /api/v1/validations/{validation_id}/windows`

返回项：

| 字段 | 类型 | 说明 |
|---|---|---|
| window_index | integer | 窗口编号 |
| scenario_name | string | 场景名 |
| train_return | number | 样本内收益 |
| validate_return | number | 验证收益 |
| test_return | number | 测试收益 |
| metrics | object | 指标明细 |

---

## 7. 账户与交易接口

## 7.1 创建账户

### `POST /api/v1/accounts`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| account_code | string | 是 | 账户编码 |
| account_name | string | 是 | 账户名称 |
| market | string | 是 | 市场 |
| broker_code | string | 是 | 券商编码 |
| account_type | string | 是 | `PAPER` / `LIVE` |
| currency | string | 是 | 币种 |
| constraint_payload | object | 否 | 账户约束 |

## 7.2 查询账户快照

### `GET /api/v1/accounts/{account_id}/snapshots`

返回项：

| 字段 | 类型 | 说明 |
|---|---|---|
| snapshot_time | string(datetime) | 快照时间 |
| total_asset | number | 总资产 |
| cash | number | 现金 |
| buying_power | number | 可用资金 |
| market_value | number | 持仓市值 |
| pnl | number | 盈亏 |

## 7.3 查询持仓

### `GET /api/v1/accounts/{account_id}/positions`

返回项：

| 字段 | 类型 | 说明 |
|---|---|---|
| instrument_code | string | 证券代码 |
| qty | integer | 持仓数量 |
| available_qty | integer | 可卖数量 |
| avg_cost | number | 平均成本 |
| market_price | number | 市价 |
| market_value | number | 市值 |
| pnl | number | 盈亏 |

## 7.4 生成调仓计划

### `POST /api/v1/rebalance-plans`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| account_id | string | 是 | 账户 ID |
| strategy_version_id | string | 是 | 策略版本 |
| trade_date | string(date) | 是 | 交易日 |
| target_source | string | 否 | 目标来源，默认 `STRATEGY_TARGET` |

响应体：

| 字段 | 类型 | 说明 |
|---|---|---|
| plan_id | string | 调仓计划 ID |
| status | string | 状态 |

## 7.5 查询调仓计划

### `GET /api/v1/rebalance-plans`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| account_id | string | 否 | 账户 ID |
| trade_date | string(date) | 否 | 交易日 |
| strategy_version_id | string | 否 | 策略版本 |

返回项：

| 字段 | 类型 | 说明 |
|---|---|---|
| plan_id | string | 调仓计划 ID |
| account_id | string | 账户 ID |
| strategy_version_id | string | 策略版本 |
| trade_date | string(date) | 交易日 |
| status | string | 状态 |
| item_count | integer | 明细数量 |

## 7.6 生成订单意图

### `POST /api/v1/order-intents`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| plan_id | string | 是 | 调仓计划 ID |
| auto_split | boolean | 否 | 是否自动拆单 |
| requires_approval | boolean | 否 | 是否需要审批 |

响应体：

| 字段 | 类型 | 说明 |
|---|---|---|
| intent_batch_id | string | 批次 ID |
| item_count | integer | 生成数量 |

## 7.7 查询订单意图

### `GET /api/v1/order-intents`

返回项：

| 字段 | 类型 | 说明 |
|---|---|---|
| order_intent_id | string | 订单意图 ID |
| account_id | string | 账户 |
| instrument_code | string | 证券 |
| side | string | 买卖方向 |
| qty | integer | 数量 |
| price | number | 价格 |
| requires_approval | boolean | 是否需审批 |
| status | string | 状态 |

## 7.8 提交订单

### `POST /api/v1/orders/submit`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| order_intent_ids | array[string] | 是 | 订单意图列表 |
| execution_mode | string | 是 | `ADVISORY` / `AUTO` |
| broker_route | string | 否 | 券商路由标识 |

校验规则：

- 订单意图必须处于可提交状态
- 若需要审批则必须先审批通过
- 风险检查必须通过

响应体：

| 字段 | 类型 | 说明 |
|---|---|---|
| order_ids | array[string] | 订单 ID 列表 |
| submitted_count | integer | 成功提交数量 |

## 7.9 撤单

### `POST /api/v1/orders/{order_id}/cancel`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| reason | string | 否 | 撤单原因 |

响应体：

| 字段 | 类型 | 说明 |
|---|---|---|
| order_id | string | 订单 ID |
| status | string | 最新状态 |

## 7.10 查询订单列表

### `GET /api/v1/orders`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| account_id | string | 否 | 账户 ID |
| trade_date | string(date) | 否 | 交易日 |
| status | string | 否 | 状态 |
| instrument_code | string | 否 | 证券代码 |

返回项：

| 字段 | 类型 | 说明 |
|---|---|---|
| order_id | string | 订单 ID |
| account_id | string | 账户 |
| instrument_code | string | 证券 |
| side | string | 买卖 |
| qty | integer | 下单数量 |
| filled_qty | integer | 已成交数量 |
| avg_fill_price | number | 成交均价 |
| status | string | 状态 |
| submitted_at | string(datetime) | 提交时间 |

## 7.11 查询成交列表

### `GET /api/v1/fills`

返回项：

| 字段 | 类型 | 说明 |
|---|---|---|
| fill_id | string | 成交 ID |
| order_id | string | 订单 ID |
| fill_time | string(datetime) | 成交时间 |
| instrument_code | string | 证券代码 |
| fill_qty | integer | 成交数量 |
| fill_price | number | 成交价格 |
| commission | number | 手续费 |
| taxes | number | 税费 |
| slippage_bps | number | 滑点 |

---

## 8. 风险与审批接口

## 8.1 创建风险规则

### `POST /api/v1/risk/rules`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| rule_code | string | 是 | 规则编码 |
| rule_name | string | 是 | 规则名称 |
| rule_scope | string | 是 | `RESEARCH` / `PORTFOLIO` / `TRADING` / `RUNTIME` |
| rule_type | string | 是 | 规则类型 |
| rule_payload | object | 是 | 规则配置 |
| severity | string | 是 | 严重级别 |

## 8.2 触发风险检查

### `POST /api/v1/risk/check-runs`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| check_type | string | 是 | 检查类型 |
| source_type | string | 是 | 来源类型 |
| source_id | string | 是 | 来源 ID |
| account_id | string | 否 | 账户 ID |

返回：

- 异步任务结构或同步检查结果

## 8.3 查询风险事件

### `GET /api/v1/risk/events`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| resource_type | string | 否 | 资源类型 |
| resource_id | string | 否 | 资源 ID |
| severity | string | 否 | 严重级别 |
| status | string | 否 | 状态 |

返回项：

| 字段 | 类型 | 说明 |
|---|---|---|
| event_id | string | 风险事件 ID |
| rule_code | string | 规则编码 |
| severity | string | 严重级别 |
| resource_type | string | 资源类型 |
| resource_id | string | 资源 ID |
| event_message | string | 风险说明 |
| action_taken | string | 处理动作 |
| status | string | 状态 |

## 8.4 提交豁免申请

### `POST /api/v1/risk/exemptions`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| resource_type | string | 是 | 资源类型 |
| resource_id | string | 是 | 资源 ID |
| rule_id | string | 是 | 规则 ID |
| reason | string | 是 | 申请原因 |

## 8.5 发起审批

### `POST /api/v1/approvals`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| approval_type | string | 是 | 审批类型 |
| resource_type | string | 是 | 资源类型 |
| resource_id | string | 是 | 资源 ID |
| reason | string | 否 | 原因 |
| approver_ids | array[string] | 否 | 指定审批人 |

响应体：

| 字段 | 类型 | 说明 |
|---|---|---|
| request_id | string | 审批单 ID |
| status | string | 状态 |

## 8.6 审批动作

### `POST /api/v1/approvals/{request_id}/approve`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| comment | string | 否 | 审批意见 |

### `POST /api/v1/approvals/{request_id}/reject`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| comment | string | 是 | 拒绝原因 |

---

## 9. 运维与报表接口

## 9.1 查询系统健康

### `GET /api/v1/ops/health`

响应体 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| status | string | 总体状态 |
| services | array[object] | 服务明细 |

`services[]` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| service_name | string | 服务名 |
| status | string | 状态 |
| updated_at | string(datetime) | 更新时间 |
| detail | string | 详情 |

## 9.2 查询任务列表

### `GET /api/v1/ops/tasks`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| task_type | string | 否 | 任务类型 |
| status | string | 否 | 任务状态 |
| started_after | string(datetime) | 否 | 开始时间下限 |
| started_before | string(datetime) | 否 | 开始时间上限 |

返回项：

| 字段 | 类型 | 说明 |
|---|---|---|
| task_id | string | 任务 ID |
| task_type | string | 类型 |
| task_name | string | 名称 |
| status | string | 状态 |
| started_at | string(datetime) | 开始时间 |
| finished_at | string(datetime) | 结束时间 |
| error_message | string | 错误信息 |

## 9.3 重跑任务

### `POST /api/v1/ops/tasks/{task_id}/rerun`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| reason | string | 否 | 重跑原因 |

返回：

- 异步任务结构

## 9.4 查询审计日志

### `GET /api/v1/ops/audit-events`

返回项：

| 字段 | 类型 | 说明 |
|---|---|---|
| event_id | string | 事件 ID |
| event_type | string | 事件类型 |
| operator | object | 操作人 |
| resource_type | string | 资源类型 |
| resource_id | string | 资源 ID |
| action | string | 操作 |
| detail | object | 详情 |
| created_at | string(datetime) | 创建时间 |

## 9.5 查询策略收益报表

### `GET /api/v1/reports/strategy-performance`

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| strategy_version_id | string | 否 | 策略版本 |
| account_id | string | 否 | 账户 ID |
| start_date | string(date) | 否 | 开始日期 |
| end_date | string(date) | 否 | 结束日期 |

响应体 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| summary | object | 汇总 |
| daily | array[object] | 日度结果 |

`summary` 字段建议：

| 字段 | 类型 | 说明 |
|---|---|---|
| total_return | number | 总收益 |
| annualized_return | number | 年化收益 |
| max_drawdown | number | 最大回撤 |
| sharpe_ratio | number | 夏普 |
| turnover | number | 平均换手 |
| fee_drag | number | 成本拖累 |

## 9.6 导出报表

### `POST /api/v1/reports/export`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| report_type | string | 是 | 报表类型 |
| format | string | 是 | `CSV` / `JSON` / `MARKDOWN` / `PDF` |
| query | object | 是 | 查询参数 |

返回：

- 异步任务结构或导出地址

---

## 10. 核心对象响应示例

## 10.1 策略版本对象

```json
{
  "strategy_version_id": "sv_20260331_01",
  "strategy_id": "st_quality_momentum",
  "strategy_code": "quality_momentum",
  "version": "2026.03.31.01",
  "market_scope": ["CN"],
  "parameter_set_id": "sp_001",
  "factor_version_refs": ["fv_mom_20_v1", "fv_quality_v2"],
  "data_snapshot_id": "snap_20260331_cn",
  "status": "REVIEW_PENDING",
  "validation_summary": {
    "test_return": 0.1234,
    "max_drawdown": -0.081,
    "stability_score": 0.72
  }
}
```

## 10.2 订单对象

```json
{
  "order_id": "ord_001",
  "order_intent_id": "oi_001",
  "account_id": "acct_cn_alpha",
  "instrument_code": "CN.600519",
  "side": "BUY",
  "qty": 100,
  "filled_qty": 60,
  "avg_fill_price": 1650.5,
  "status": "PARTIALLY_FILLED",
  "submitted_at": "2026-03-31T09:35:00+08:00",
  "finished_at": null
}
```

## 10.3 风险事件对象

```json
{
  "event_id": "risk_evt_001",
  "rule_code": "MAX_SINGLE_POSITION",
  "severity": "HIGH",
  "resource_type": "ORDER_INTENT",
  "resource_id": "oi_001",
  "event_message": "单票目标权重超过 15%",
  "action_taken": "BLOCKED",
  "status": "OPEN"
}
```

---

## 11. OpenAPI 落地建议

### 11.1 建议拆分方式

按 tag 拆分 OpenAPI：

- `Auth`
- `DataPlatform`
- `Instrument`
- `Research`
- `Factor`
- `Strategy`
- `Backtest`
- `Validation`
- `Account`
- `Trading`
- `Risk`
- `Approval`
- `Ops`
- `Report`

### 11.2 建议公共组件

可抽成 OpenAPI Components：

- `PageResponse`
- `AsyncTaskResponse`
- `StrategyVersion`
- `AccountSnapshot`
- `Order`
- `RiskEvent`
- `ErrorResponse`

---

## 12. 联调顺序建议

建议按以下顺序进行前后端联调：

1. 认证与权限
2. 研究项目与因子查询
3. 策略版本与回测结果
4. 账户、持仓、调仓计划
5. 订单和成交
6. 风险和审批
7. 运维和报表

---

## 13. 结论

这份接口字段级定义文档的目标是让接口从“有清单”进入“可实现、可联调、可自动生成 OpenAPI”的阶段。后续如果进入开发阶段，建议基于本文档继续细化：

- 字段枚举字典
- 错误码字典
- OpenAPI YAML
- Mock 数据文档
- 权限矩阵文档
