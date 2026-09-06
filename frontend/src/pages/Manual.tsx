import { BookOpen, DatabaseZap, GitBranch, LineChart, ListChecks, ShieldCheck } from "lucide-react";
import { useState } from "react";

type SectionKey = "intro" | "data" | "scan" | "paper" | "evolution";

const sections = [
  { key: "intro", label: "1. 平台简介", icon: BookOpen },
  { key: "data", label: "2. 数据同步", icon: DatabaseZap },
  { key: "scan", label: "3. 信号扫描", icon: ListChecks },
  { key: "paper", label: "4. 模拟交易", icon: LineChart },
  { key: "evolution", label: "5. 参数候选", icon: GitBranch },
] as const;

const textStyle = { color: "#4b5563", fontSize: "14px", lineHeight: "1.8" };

function Manual() {
  const [activeSec, setActiveSec] = useState<SectionKey>("intro");

  return (
    <div className="page-stack manual-container" style={{ display: "flex", gap: 24, minHeight: "calc(100vh - 120px)" }}>
      <aside className="panel" style={{ width: 240, flexShrink: 0, padding: 16, height: "fit-content" }}>
        <h3 style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 0 }}><BookOpen size={20} />操作手册</h3>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {sections.map((section) => {
            const Icon = section.icon;
            return (
              <button
                key={section.key}
                type="button"
                className={`menu-item ${activeSec === section.key ? "active" : ""}`}
                onClick={() => setActiveSec(section.key)}
                style={{ display: "flex", gap: 8, padding: 10, border: 0, borderRadius: 6, cursor: "pointer" }}
              >
                <Icon size={16} />{section.label}
              </button>
            );
          })}
        </div>
      </aside>

      <main className="panel" style={{ flex: 1, padding: 32 }}>
        {activeSec === "intro" && (
          <section>
            <h2>EvoQuant 量化研究与模拟交易平台</h2>
            <p style={textStyle}>平台把 US/CN 股票池、日线同步、横截面动量信号、回测、模拟订单草稿、风险状态和审计串成一个研究流程。系统不连接券商或交易所，不能用于真实下单。</p>
            <ol style={textStyle}>
              <li>创建模拟账户并同步股票池。</li>
              <li>创建 K 线任务，等待数据达到扫描覆盖率。</li>
              <li>运行信号扫描并检查排名、权重和风险标记。</li>
              <li>创建草稿，经人工 Approve 后再 Submit 模拟成交。</li>
            </ol>
            <p className="inline-message"><ShieldCheck size={16} /> PostgreSQL 是当前唯一运行时数据库；真实交易始终禁用。</p>
          </section>
        )}

        {activeSec === "data" && (
          <section>
            <h2>股票池与日线同步</h2>
            <p style={textStyle}>美股默认使用 Yahoo Finance；配置 TIINGO_API_KEY 后日线使用 Tiingo。A 股使用 BaoStock，并过滤 B 股。先同步 Stock Pool，再从 Data Sources 创建 US 或 CN 分批 K 线任务。</p>
            <ul style={textStyle}>
              <li>首次任务默认获取近五年日线，耗时取决于股票数量和供应商限流。</li>
              <li>任务状态为 partial 时可重试失败标的。</li>
              <li>定时计划只在已有历史 K 线时做增量同步；任务运行在 API 进程内。</li>
            </ul>
          </section>
        )}

        {activeSec === "scan" && (
          <section>
            <h2>横截面动量信号</h2>
            <p style={textStyle}>当前唯一模板是 cross_sectional_momentum。默认使用 120/20 日收益排名，减去波动率和最大回撤排名惩罚，选取 Top 20，单票权重上限 8%。市场覆盖率低于 70% 时扫描会失败。</p>
            <p style={textStyle}>结果中的 buy、hold、sell 是研究信号。生成 Draft 前应核对数据日期、原因和 suspended、limit_up、limit_down、low_liquidity 等风险标记。</p>
          </section>
        )}

        {activeSec === "paper" && (
          <section>
            <h2>模拟账户与人工审批</h2>
            <ol style={textStyle}>
              <li>在 Paper Trading 创建账户。</li>
              <li>从 Signals 选择结果并创建 Draft。</li>
              <li>审核数量、参考价和风险后点击 Approve，或点击 Cancel。</li>
              <li>对 approved 草稿点击 Submit，系统按参考价立即整笔模拟成交。</li>
            </ol>
            <p style={textStyle}>Risk 为 paused 时不能提交直接订单或草稿。当前成交费为 0，不模拟滑点、部分成交或市场深度，也不允许形成净空头。</p>
          </section>
        )}

        {activeSec === "evolution" && (
          <section>
            <h2>参数候选</h2>
            <p style={textStyle}>Evolution 对参数列表做笛卡尔积并按 max_candidates 截断。候选不会自动回测、评分、选择、注册、晋级或部署。研究员需要在 Backtests 验证结果，并在 Strategies 中人工管理策略。</p>
          </section>
        )}
      </main>
    </div>
  );
}

export default Manual;
