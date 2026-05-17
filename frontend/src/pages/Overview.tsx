import { AlertTriangle, CheckCircle2, CircleDollarSign, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiGet } from "../api";

type Dashboard = {
  strategy_count: number;
  strategies_by_status: Record<string, number>;
  paper_account_count: number;
  paper_total_nav: number;
  audit_event_count: number;
  risk: { mode: string; live_enabled: boolean };
};

const emptyDashboard: Dashboard = {
  strategy_count: 0,
  strategies_by_status: {},
  paper_account_count: 0,
  paper_total_nav: 0,
  audit_event_count: 0,
  risk: { mode: "research-only", live_enabled: false },
};

const fallbackDashboard: Dashboard = {
  strategy_count: 4,
  strategies_by_status: { research: 2, candidate: 1, paper: 1 },
  paper_account_count: 1,
  paper_total_nav: 103420,
  audit_event_count: 18,
  risk: { mode: "research-only", live_enabled: false },
};

const equitySeries = [
  { date: "Mon", equity: 100000, drawdown: 0 },
  { date: "Tue", equity: 100860, drawdown: -0.004 },
  { date: "Wed", equity: 101420, drawdown: -0.002 },
  { date: "Thu", equity: 100980, drawdown: -0.008 },
  { date: "Fri", equity: 103210, drawdown: -0.001 },
  { date: "Now", equity: 103420, drawdown: -0.003 },
];

function Overview() {
  const [data, setData] = useState<Dashboard>(emptyDashboard);
  const [state, setState] = useState<"loading" | "ready" | "fallback">("loading");

  useEffect(() => {
    apiGet<Dashboard>("/api/dashboard")
      .then((dashboard) => {
        setData(dashboard);
        setState("ready");
      })
      .catch(() => {
        setData(fallbackDashboard);
        setState("fallback");
      });
  }, []);

  const activeStrategies = Object.values(data.strategies_by_status).reduce(
    (sum, count) => sum + count,
    0,
  );

  return (
    <div className="page-stack">
      <div className="status-strip">
        <span className={`pill ${state === "fallback" ? "warning" : "ok"}`}>
          {state === "loading" ? "Loading API" : state === "fallback" ? "Offline example data" : "API connected"}
        </span>
        <span>Risk mode: {data.risk.mode}</span>
        <span>Live enabled: {data.risk.live_enabled ? "yes" : "no"}</span>
      </div>

      <div className="kpi-grid">
        <div className="kpi-tile">
          <CheckCircle2 size={18} />
          <span>Strategies</span>
          <strong>{data.strategy_count || activeStrategies}</strong>
        </div>
        <div className="kpi-tile">
          <CircleDollarSign size={18} />
          <span>Paper NAV</span>
          <strong>${data.paper_total_nav.toLocaleString()}</strong>
        </div>
        <div className="kpi-tile">
          <RefreshCw size={18} />
          <span>Paper Accounts</span>
          <strong>{data.paper_account_count}</strong>
        </div>
        <div className="kpi-tile">
          <AlertTriangle size={18} />
          <span>Audit Events</span>
          <strong>{data.audit_event_count}</strong>
        </div>
      </div>

      <div className="panel-grid two">
        <section className="panel">
          <div className="panel-header">
            <h2>Equity and Drawdown</h2>
            <span>{state === "fallback" ? "offline sample" : "paper telemetry"}</span>
          </div>
          {state === "fallback" ? (
            <div className="chart-box">
              <ResponsiveContainer width="100%" height="100%" minHeight={240} minWidth={240}>
                <AreaChart data={equitySeries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#d8dee4" />
                  <XAxis dataKey="date" tickLine={false} axisLine={false} />
                  <YAxis tickLine={false} axisLine={false} width={56} />
                  <Tooltip />
                  <Area dataKey="equity" stroke="#2563eb" fill="#dbeafe" strokeWidth={2} />
                  <Area dataKey="drawdown" stroke="#c2410c" fill="#ffedd5" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="empty-state">
              <strong>No paper equity series yet</strong>
              <span>Submit paper orders and backtests to populate real telemetry.</span>
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2>Strategy Status</h2>
            <span>{activeStrategies} tracked</span>
          </div>
          {activeStrategies === 0 ? (
            <div className="empty-state">
              <strong>No registered strategies</strong>
              <span>Generate candidates and register approved research strategies.</span>
            </div>
          ) : (
            <div className="status-list">
              {Object.entries(data.strategies_by_status).map(([status, count]) => (
                <div className="status-row" key={status}>
                  <span className={`badge ${status}`}>{status}</span>
                  <div className="bar-track">
                    <span style={{ width: `${Math.max(8, (count / Math.max(activeStrategies, 1)) * 100)}%` }} />
                  </div>
                  <strong>{count}</strong>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

export default Overview;
