# EvoQuant

EvoQuant 是面向美股和 A 股日线研究的量化研究与模拟交易平台。当前实现覆盖股票池及行情同步、横截面动量信号、回测、参数候选、人工审批的模拟订单草稿、风险模式和审计；不连接券商或交易所，不能真实下单。

## 快速开始

需要 Python 3.11+、`uv`、Node.js 20+ 和 PostgreSQL 16。

```bash
createdb evoquant
export EVOQUANT_DB_URL='postgresql://localhost:5432/evoquant'
uv sync --extra dev
uv run evoquant --host 127.0.0.1 --port 8000
```

另开终端启动前端：

```bash
cd frontend
npm install
npm run dev
```

管理台默认在 `http://127.0.0.1:5173`，API 在 `http://127.0.0.1:8000`。也可设置 `POSTGRES_PASSWORD` 后运行 `docker compose up --build`，管理台端口为 8080。

美股默认使用 Yahoo Finance；设置 `TIINGO_API_KEY` 后使用 Tiingo。A 股使用 BaoStock。完整安装、数据同步和操作流程见 [平台使用指南](docs/平台使用指南.md)。

## 验证

数据库测试只会在显式提供测试库时运行，并为每个测试创建独立临时 schema：

```bash
EVOQUANT_TEST_DB_URL='postgresql://localhost:5432/evoquant_test' uv run --extra dev pytest -q
cd frontend && npm run typecheck && npm run build
uv run python tools/export_openapi.py --check
```

## 文档

现行文档统一从 [docs/README.md](docs/README.md) 进入，包括平台使用指南、PRD、系统架构、数据库设计、API 设计和开发规范。旧版设计和实施计划可通过 Git 历史追溯，不代表当前功能承诺。
