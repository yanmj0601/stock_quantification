import {
  Activity,
  BarChart3,
  Beaker,
  BookOpen,
  ClipboardList,
  DatabaseZap,
  GitBranch,
  LineChart,
  ListChecks,
  ListTree,
  ScrollText,
  ShieldCheck,
} from "lucide-react";
import { useMemo, useState, type ReactElement } from "react";
import AuditLog from "./pages/AuditLog";
import Backtests from "./pages/Backtests";
import DataHealth from "./pages/DataHealth";
import Evolution from "./pages/Evolution";
import Manual from "./pages/Manual";
import Overview from "./pages/Overview";
import PaperTrading from "./pages/PaperTrading";
import Risk from "./pages/Risk";
import Signals from "./pages/Signals";
import StockPool from "./pages/StockPool";
import Strategies from "./pages/Strategies";

type PageKey =
  | "overview"
  | "strategies"
  | "stockPool"
  | "signals"
  | "backtests"
  | "evolution"
  | "paper"
  | "data"
  | "risk"
  | "audit"
  | "manual";

const navItems = [
  { key: "overview", label: "Overview", icon: Activity },
  { key: "strategies", label: "Strategies", icon: ClipboardList },
  { key: "stockPool", label: "Stock Pool", icon: ListTree },
  { key: "signals", label: "Signals", icon: ListChecks },
  { key: "backtests", label: "Backtests", icon: BarChart3 },
  { key: "evolution", label: "Evolution", icon: GitBranch },
  { key: "paper", label: "Paper Trading", icon: LineChart },
  { key: "data", label: "Data Sources", icon: DatabaseZap },
  { key: "risk", label: "Risk", icon: ShieldCheck },
  { key: "audit", label: "Audit Log", icon: ScrollText },
  { key: "manual", label: "User Manual", icon: BookOpen },
] satisfies Array<{ key: PageKey; label: string; icon: typeof Beaker }>;

const pageTitle: Record<PageKey, string> = {
  overview: "Overview",
  strategies: "Strategies",
  stockPool: "Stock Pool",
  signals: "Signals",
  backtests: "Backtests",
  evolution: "Evolution",
  paper: "Paper Trading",
  data: "Data Sources",
  risk: "Risk",
  audit: "Audit Log",
  manual: "User Manual",
};

function App() {
  const [active, setActive] = useState<PageKey>("overview");
  const ActivePage = useMemo(() => {
    const pages: Record<PageKey, ReactElement> = {
      overview: <Overview />,
      strategies: <Strategies />,
      stockPool: <StockPool />,
      signals: <Signals />,
      backtests: <Backtests />,
      evolution: <Evolution />,
      paper: <PaperTrading />,
      data: <DataHealth />,
      risk: <Risk />,
      audit: <AuditLog />,
      manual: <Manual />,
    };
    return pages[active];
  }, [active]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">EQ</div>
          <div>
            <div className="brand-name">EvoQuant</div>
            <div className="brand-subtitle">MVP v2 Admin</div>
          </div>
        </div>
        <nav className="nav-list" aria-label="Admin sections">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                aria-current={active === item.key ? "page" : undefined}
                className={`nav-item ${active === item.key ? "active" : ""}`}
                onClick={() => setActive(item.key)}
                type="button"
              >
                <Icon size={17} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <span className="status-dot" />
          Research operations
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <h1>{pageTitle[active]}</h1>
            <p>Quant research control plane</p>
          </div>
          <div className="topbar-meta">
            <span>API 127.0.0.1:8000</span>
            <span>MVP live disabled</span>
          </div>
        </header>
        <section className="page-frame">{ActivePage}</section>
      </main>
    </div>
  );
}

export default App;
