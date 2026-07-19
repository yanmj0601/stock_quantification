import {
  Activity,
  Award,
  BookOpen,
  ClipboardList,
  DatabaseZap,
  GitBranch,
  Info,
  LineChart,
  ListChecks,
  ListTree,
  Play,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import { useState } from "react";

type SectionKey = "intro" | "data" | "scan" | "paper" | "evolution";

function Manual() {
  const [activeSec, setActiveSec] = useState<SectionKey>("intro");

  const sections = [
    { key: "intro", label: "1. 平台简介", icon: Sparkles },
    { key: "data", label: "2. 数据源同步", icon: DatabaseZap },
    { key: "scan", label: "3. 信号扫描", icon: ListChecks },
    { key: "paper", label: "4. 模拟交易", icon: LineChart },
    { key: "evolution", label: "5. 参数进化候选人", icon: GitBranch },
  ] as const;

  return (
    <div className="page-stack manual-container" style={{ display: "flex", gap: "24px", minHeight: "calc(100vh - 120px)" }}>
      {/* 左侧文档目录导航 */}
      <aside className="panel" style={{ width: "240px", flexShrink: 0, padding: "16px", height: "fit-content", position: "sticky", top: "24px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px", color: "#0f766e" }}>
          <BookOpen size={20} />
          <h3 style={{ margin: 0, fontSize: "16px", fontWeight: "bold" }}>操作手册目录</h3>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {sections.map((sec) => {
            const Icon = sec.icon;
            const isActive = activeSec === sec.key;
            return (
              <button
                key={sec.key}
                onClick={() => setActiveSec(sec.key)}
                className={`menu-item ${isActive ? "active" : ""}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  padding: "10px 12px",
                  width: "100%",
                  border: "none",
                  borderRadius: "6px",
                  background: isActive ? "#0f766e" : "transparent",
                  color: isActive ? "#ffffff" : "#4b5563",
                  textAlign: "left",
                  fontSize: "14px",
                  fontWeight: isActive ? "600" : "500",
                  cursor: "pointer",
                  transition: "all 0.2s ease",
                }}
              >
                <Icon size={16} />
                {sec.label}
              </button>
            );
          })}
        </div>
      </aside>

      {/* 右侧文档详细正文 */}
      <main className="panel" style={{ flex: 1, padding: "32px", overflowY: "auto" }}>
        {activeSec === "intro" && (
          <div>
            <div style={{
              background: "linear-gradient(135deg, #0f766e 0%, #115e59 100%)",
              padding: "24px",
              borderRadius: "12px",
              color: "#ffffff",
              marginBottom: "24px",
            }}>
              <h1 style={{ margin: 0, fontSize: "24px", fontWeight: "bold", display: "flex", alignItems: "center", gap: "10px" }}>
                <Sparkles size={24} /> EvoQuant 量化科研平台操作手册
              </h1>
              <p style={{ margin: "8px 0 0 0", opacity: 0.9, fontSize: "14px" }}>
                欢迎使用 EvoQuant MVP v2 自进化多市场量化科研平台。本手册将带您熟悉从数据源接入、信号扫描到模拟成交、参数进化的完整量化生命周期。
              </p>
            </div>

            <h2 style={{ fontSize: "18px", color: "#111827", borderBottom: "1px solid #e5e7eb", paddingBottom: "8px" }}>核心业务闭环流程</h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "16px", margin: "20px 0" }}>
              <div style={{ padding: "16px", border: "1px solid #e5e7eb", borderRadius: "8px", background: "#f9fafb" }}>
                <div style={{ color: "#0f766e", fontWeight: "bold", display: "flex", alignItems: "center", gap: "6px", marginBottom: "8px" }}>
                  <DatabaseZap size={16} /> 1. 数据准备
                </div>
                <small style={{ color: "#6b7280" }}>在 Data Sources 页面一键同步美股与 A 股全市场的历史价格数据。</small>
              </div>
              <div style={{ padding: "16px", border: "1px solid #e5e7eb", borderRadius: "8px", background: "#f9fafb" }}>
                <div style={{ color: "#0f766e", fontWeight: "bold", display: "flex", alignItems: "center", gap: "6px", marginBottom: "8px" }}>
                  <ListChecks size={16} /> 2. 策略扫描
                </div>
                <small style={{ color: "#6b7280" }}>运行信号扫描器对成分股进行横截面动量评分，生产最新一期交易决策。</small>
              </div>
              <div style={{ padding: "16px", border: "1px solid #e5e7eb", borderRadius: "8px", background: "#f9fafb" }}>
                <div style={{ color: "#0f766e", fontWeight: "bold", display: "flex", alignItems: "center", gap: "6px", marginBottom: "8px" }}>
                  <LineChart size={16} /> 3. 模拟盘成交
                </div>
                <small style={{ color: "#6b7280" }}>在 Paper Trading 中对生成的交易草稿执行 Approve 并 Submit 成交，清算持仓。</small>
              </div>
              <div style={{ padding: "16px", border: "1px solid #e5e7eb", borderRadius: "8px", background: "#f9fafb" }}>
                <div style={{ color: "#0f766e", fontWeight: "bold", display: "flex", alignItems: "center", gap: "6px", marginBottom: "8px" }}>
                  <GitBranch size={16} /> 4. 参数自进化
                </div>
                <small style={{ color: "#6b7280" }}>利用进化 candidate 寻找最优回测参数，注册新版本候选策略并部署上线。</small>
              </div>
            </div>

            <div className="inline-message" style={{ display: "flex", gap: "12px", background: "#f0fdf4", border: "1px solid #bbf7d0", padding: "16px", borderRadius: "8px", marginTop: "24px" }}>
              <Info size={20} style={{ color: "#16a34a", flexShrink: 0 }} />
              <div style={{ fontSize: "14px", color: "#166534" }}>
                <strong>提示：</strong> 本系统包含完整的本地 SQLite 数据缓存与模拟盘资金模型。进行测试时，推荐先切换至 <strong>Data Sources</strong> 同步数据以提供回测和扫描源。
              </div>
            </div>
          </div>
        )}

        {activeSec === "data" && (
          <div>
            <h2 style={{ fontSize: "20px", color: "#111827", display: "flex", alignItems: "center", gap: "8px", margin: "0 0 16px 0" }}>
              <DatabaseZap size={22} style={{ color: "#0f766e" }} /> 数据源接入与同步 (Data Sources)
            </h2>
            <p style={{ color: "#4b5563", fontSize: "14px", lineHeight: "1.6" }}>
              数据是量化策略的血液。在 <strong>Data Sources</strong> 菜单中，您可以一键拉取或自动定时获取最新的证券信息（Instruments）和日 K 线历史数据（Bars）。
            </p>

            <h3 style={{ fontSize: "15px", color: "#374151", marginTop: "20px" }}>美股 (US Market)</h3>
            <ul style={{ paddingLeft: "20px", color: "#4b5563", fontSize: "14px", lineHeight: "1.8" }}>
              <li><strong>股票池 (SP500)</strong>：基于 Yahoo Finance 抓取的标普 500 指数成分股。</li>
              <li><strong>数据同步 (Bars)</strong>：使用 Yahoo Finance 或专业的 Tiingo API。若配置了环境变量 <code>TIINGO_API_KEY</code>，系统将自动使用专业高精度的 Tiingo 接口进行同步。</li>
            </ul>

            <h3 style={{ fontSize: "15px", color: "#374151", marginTop: "20px" }}>A 股 (CN Market)</h3>
            <ul style={{ paddingLeft: "20px", color: "#4b5563", fontSize: "14px", lineHeight: "1.8" }}>
              <li><strong>股票池 (CSI300 / ALL)</strong>：目前采用 <strong>Baostock</strong> 接口，支持同步上证与深证的 <strong>4,700+ 只全市场全量 A 股个股</strong>！</li>
              <li><strong>数据同步 (Bars)</strong>：调用 Baostock 的 TCP 专属网络柜台下载日线，具备极强的网络防封锁性能。支持后台分批增量落盘与隔离式断点续传。</li>
            </ul>

            <div style={{ background: "#fef3c7", border: "1px solid #fde68a", padding: "16px", borderRadius: "8px", margin: "24px 0", color: "#92400e", fontSize: "14px" }}>
              <strong>⚠️ 注意事项：</strong> 首次使用 A 股扫描前，由于全市场数据量庞大（4700多只股票 1 年数据约 113 万条），数据增量同步可能耗时约 30 分钟。中途刷新页面不会打断后台下载进程。
            </div>
          </div>
        )}

        {activeSec === "scan" && (
          <div>
            <h2 style={{ fontSize: "20px", color: "#111827", display: "flex", alignItems: "center", gap: "8px", margin: "0 0 16px 0" }}>
              <ListChecks size={22} style={{ color: "#0f766e" }} /> 横截面策略信号扫描 (Signals Center)
            </h2>
            <p style={{ color: "#4b5563", fontSize: "14px", lineHeight: "1.6" }}>
              在 <strong>Signals</strong> 面板中，我们可以手动触发策略信号扫描。扫描器会利用数据库里缓存的日 K 线，对股票池内所有可用股票进行打分。
            </p>

            <h3 style={{ fontSize: "15px", color: "#374151", marginTop: "20px" }}>动量策略参数配置：</h3>
            <ul style={{ paddingLeft: "20px", color: "#4b5563", fontSize: "14px", lineHeight: "1.8" }}>
              <li><strong>lookback_long（长回溯期）</strong>：计算动量排名的历史天数（如默认 120 天，即最近半年）。</li>
              <li><strong>lookback_short（短回溯期）</strong>：用于近端动量反转剔除的历史天数（如 20 天）。</li>
              <li><strong>top_n（买入数量上限）</strong>：动量得分最高的排名前 N 只股票（如买入前 20 只）。</li>
              <li><strong>max_weight（单只持仓上限）</strong>：防止个股仓位过重（如单只最高 8% 仓位）。</li>
            </ul>

            <div style={{ border: "1px solid #e5e7eb", borderRadius: "8px", padding: "16px", marginTop: "24px" }}>
              <h4 style={{ margin: "0 0 8px 0", color: "#111827", fontSize: "14px" }}>核心打分公式：</h4>
              <p style={{ margin: 0, background: "#f3f4f6", padding: "12px", borderRadius: "6px", fontFamily: "monospace", fontSize: "13px", color: "#1f2937" }}>
                Score = (Price_t - Price_(t-lookback_long)) / Price_(t-lookback_long)
              </p>
              <small style={{ color: "#6b7280", marginTop: "8px", display: "block" }}>
                筛选出的 Top 20 标的会生成买入信号（buy），仓位超出的标的会产生卖出信号（sell），其余标的默认为不操作（hold）。
              </small>
            </div>
          </div>
        )}

        {activeSec === "paper" && (
          <div>
            <h2 style={{ fontSize: "20px", color: "#111827", display: "flex", alignItems: "center", gap: "8px", margin: "0 0 16px 0" }}>
              <LineChart size={22} style={{ color: "#0f766e" }} /> 模拟盘账户与订单清算 (Paper Trading)
            </h2>
            <p style={{ color: "#4b5563", fontSize: "14px", lineHeight: "1.6" }}>
              EvoQuant 采用了独特的**“人工决策网关 (Approve Gateway)”**机制，以模拟最真实的多因子研究工作流。
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: "16px", margin: "20px 0" }}>
              <div style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>
                <span style={{ background: "#0f766e", color: "#fff", width: "24px", height: "24px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, fontWeight: "bold", fontSize: "13px" }}>1</span>
                <div>
                  <h4 style={{ margin: "0 0 4px 0", fontSize: "14px", color: "#111827" }}>信号产生草稿 (Drafts)</h4>
                  <small style={{ color: "#4b5563" }}>信号扫描运行成功后，会在 Paper Trading 页面的 <strong>Signal Drafts</strong> 列表中产生一批待批量的交易草稿。</small>
                </div>
              </div>

              <div style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>
                <span style={{ background: "#0f766e", color: "#fff", width: "24px", height: "24px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, fontWeight: "bold", fontSize: "13px" }}>2</span>
                <div>
                  <h4 style={{ margin: "0 0 4px 0", fontSize: "14px", color: "#111827" }}>交易审批 (Approve)</h4>
                  <small style={{ color: "#4b5563" }}>点击草稿旁的 <strong>Approve</strong>，确认此信号符合量化研究员的偏好，将其状态流转为待提交订单。</small>
                </div>
              </div>

              <div style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>
                <span style={{ background: "#0f766e", color: "#fff", width: "24px", height: "24px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, fontWeight: "bold", fontSize: "13px" }}>3</span>
                <div>
                  <h4 style={{ margin: "0 0 4px 0", fontSize: "14px", color: "#111827" }}>提交成交 (Submit)</h4>
                  <small style={{ color: "#4b5563" }}>点击 <strong>Submit</strong> 确认成交。后端清算程序会自动将订单状态更新为 <code>filled</code>，扣减模拟盘现金账户资金，并在 <strong>Positions</strong> 表中建立并累加当前持仓。</small>
                </div>
              </div>
            </div>

            <div style={{ background: "#ecfdf5", border: "1px solid #a7f3d0", padding: "16px", borderRadius: "8px", color: "#065f46", fontSize: "14px" }}>
              <strong>💡 实战贴士：</strong> 在页面右下角的 <strong>Order Ticket</strong> 中，您也可以选择特定标的进行手动紧急挂单，快速补仓或进行仓位对冲调整。
            </div>
          </div>
        )}

        {activeSec === "evolution" && (
          <div>
            <h2 style={{ fontSize: "20px", color: "#111827", display: "flex", alignItems: "center", gap: "8px", margin: "0 0 16px 0" }}>
              <GitBranch size={22} style={{ color: "#0f766e" }} /> 自进化策略参数工厂 (Evolution candidates)
            </h2>
            <p style={{ color: "#4b5563", fontSize: "14px", lineHeight: "1.6" }}>
              当市场发生转换（如动量切换为震荡）时，原策略的 lookback 天数可能失效。<strong>Evolution</strong> 面板允许我们配置一个多维度参数空间来进行回测搜索。
            </p>

            <ul style={{ paddingLeft: "20px", color: "#4b5563", fontSize: "14px", lineHeight: "1.8" }}>
              <li><strong>参数生成 (Generate)</strong>：配置 lookback 列表（如 20,60,120），系统会自动笛卡尔乘积形成多组自进化候选人（Candidates）。</li>
              <li><strong>回测筛选 (Backtest PASS)</strong>：在回测实验室中挑选 Sharpe 比率大于 1.0 的候选者。</li>
              <li><strong>注册入库 (Register)</strong>：对合格的候选人点击 **Register**，将其一键升级为具有唯一策略编码的在线策略，即可在 <strong>Strategies</strong> 列表中启用并部署至模拟盘！</li>
            </ul>

            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "24px", padding: "16px", border: "1px solid #e5e7eb", borderRadius: "8px", background: "#f9fafb" }}>
              <Award size={20} style={{ color: "#eab308" }} />
              <div style={{ fontSize: "14px", color: "#374151" }}>
                <strong>进阶功能：</strong> 注册成功的候选策略会自动获得一个更高的 v版本（例如从 v1 进化到 v2 ），保证策略逻辑迭代有迹可循。
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default Manual;
