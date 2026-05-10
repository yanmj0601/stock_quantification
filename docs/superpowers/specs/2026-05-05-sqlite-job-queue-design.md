# SQLite 任务状态与队列设计

**目标**

把当前基于内存和 JSON 的任务守护迁到 SQLite，先解决三件事：

1. 任务状态可持久化
2. `策略实验 / 策略任务` 支持排队
3. 页面历史和任务进度不再依赖单进程临时状态

**这次不做**

- 不重写研究工件格式
- 不把模拟盘账本整体迁库
- 不做真正并行执行

## 当前问题

当前实现里，`ProjectOpsStore` 只有一个 `active_job`，写在 `artifacts/web/ops_state.json`。`策略任务` 和 `策略实验` 都先抢这把锁，抢不到就直接 `BLOCKED`。同时，任务日志和运行历史还分别写在 JSON 文件里，页面又会混合读取内存缓存和这些 JSON 文件。

这导致：

- 只能同时跑一个任务，且没有排队
- 服务重启后，内存状态丢失
- 页面历史与后台真实状态容易分叉
- 后续要做自动任务时，共享 JSON 写入风险很高

## 设计原则

1. 先迁移调度层，不一次性迁移全部业务数据
2. 保持现有页面 URL 和大部分页面结构不变
3. 优先兼容现有 `ProjectOpsStore` 的使用方式，减少 `web.py` 改动面
4. 队列先串行执行，保证稳定，再谈并行

## 新的数据模型

SQLite 文件路径：

- `artifacts/web/app_state.sqlite3`

本次新增 4 张表：

### `jobs`

记录队列中的任务主表。

关键字段：

- `job_id`
- `kind`：`strategy_run` / `factor_backtest` / `paper_auto_run`
- `status`：`QUEUED / RUNNING / SUCCESS / FAILED / STALE / MANUAL_RELEASED`
- `stage`
- `detail`
- `progress_pct`
- `metadata_json`
- `payload_json`
- `created_at`
- `started_at`
- `finished_at`
- `owner_pid`
- `owner_started_at`

### `job_events`

记录任务时间线和页面日志。

关键字段：

- `event_id`
- `job_id`（可为空，兼容非任务事件）
- `category`
- `action`
- `status`
- `detail`
- `metadata_json`
- `created_at`

### `run_history`

替代 `web/run_history.json`，存放运行历史记录。

关键字段：

- `history_id`
- `run_instance_id`
- `recorded_at`
- `record_json`

### `kv_state`

放少量轻量级状态，避免继续增加散落 JSON。

首批只迁：

- `heartbeats`

`paper_automation_state` 这次先不迁，只保留现状。

## 运行模型

### 任务提交

`策略任务` 和 `策略实验` 提交后，不再尝试直接抢单锁执行，而是：

1. 把完整可执行 payload 写入 `jobs`
2. 任务状态记为 `QUEUED`
3. 同时写一条 `job_events`
4. 页面立即显示“已入队”

### 后台 worker

Web 服务启动时，启动一个串行 job worker 线程：

1. 轮询 `jobs`
2. 按 `created_at` 取最早的 `QUEUED`
3. 原子标记为 `RUNNING`
4. 调用既有执行函数：
   - `_run_strategy_job_from_payload(...)`
   - `_run_factor_backtest_job_from_payload(...)`
5. 结束后更新状态并写事件

### 服务重启恢复

服务启动时：

- 之前残留的 `RUNNING` 任务统一标记为 `STALE`
- 已经 `QUEUED` 的任务继续保留，允许继续消费

这保证“不会丢队列”，但也不假装支持任务断点续跑。

## 与现有页面的关系

### `策略任务 / 历史`

改为读：

- `run_history`
- `job_events`

不再依赖 `run_history.json` 和 `task_logs.json`

### `策略实验 / 历史`

继续以 `result_index` 为实验结果归档来源，但 `BLOCKED / STARTED / FAILED` 等任务事件改读 `job_events`。

### 任务进度

`/api/project/status` 中的：

- `active_job`
- `recent_job`
- `job_history`
- `audit_events`

都改由 SQLite 聚合生成。

## 迁移策略

第一次初始化 SQLite 时：

1. 若存在旧 `ops_state.json`，导入：
   - `heartbeats`
   - `job_history`
   - `audit_events`
   - `active_job`（作为 `STALE` 导入）
2. 若存在旧 `task_logs.json`，导入到 `job_events`
3. 若存在旧 `run_history.json`，导入到 `run_history`
4. 导入完成后，SQLite 成为唯一读路径

旧 JSON 文件不再作为运行时状态源，只保留兼容清理窗口。

## 测试范围

至少覆盖：

1. 任务入队后状态为 `QUEUED`
2. worker 能按 FIFO 执行队列
3. 已有 `RUNNING` 任务不会阻塞新任务入队
4. 服务重启后，旧 `RUNNING` 任务被标记 `STALE`
5. 旧 JSON 能导入 SQLite
6. `策略任务 / 历史` 页面能读到 SQLite 历史与重复报错
7. `/api/project/status` 能返回 SQLite 聚合状态

## 推荐实施顺序

1. 新建 SQLite 存储层
2. 给 `ops` 补测试并切换实现
3. 把 `run_history` 和 `task_logs` 迁到同一存储
4. 接入 worker 队列
5. 改 `web.py` 页面读取路径
