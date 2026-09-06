import { FlaskConical, Play, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiGet, apiPost } from "../api";

type Strategy = { id: string; name: string; market: string };
type BacktestResult = { strategy_id: string; metrics: Record<string, number> };
type SignalBacktestResult = {
  metrics: Record<string, number>;
  trades: unknown[];
  equity_curve: number[];
};

const fallbackStrategies: Strategy[] = [
  { id: "str_us_momo", name: "us_momentum_breakout", market: "US" },
  { id: "str_cn_revert", name: "cn_intraday_reversion", market: "CN" },
];

const equity = [100000, 100480, 101020, 100760, 102300, 103120, 104050, 103780];
const metricValue = (result: SignalBacktestResult | BacktestResult | null, metric: string) => {
  if (!result) return "-";
  return Number(result.metrics[metric] ?? 0).toFixed(3);
};

function Backtests() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selected, setSelected] = useState("");
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [signalResult, setSignalResult] = useState<SignalBacktestResult | null>(null);
  const [signalMarket, setSignalMarket] = useState<"US" | "CN">("US");
  const [universeText, setUniverseText] = useState("AAPL,MSFT,NVDA");
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    apiGet<Strategy[]>("/api/strategies")
      .then((rows) => {
        setStrategies(rows);
        setSelected(rows[0]?.id ?? "");
        setMessage(null);
      })
      .catch(() => {
        setStrategies(fallbackStrategies);
        setSelected(fallbackStrategies[0].id);
        setMessage("API unavailable. Showing offline example strategies.");
        setStatus("fallback");
      });
  }, []);

  const chartData = useMemo(
    () => (signalResult?.equity_curve ?? equity).map((value, index) => ({ step: index + 1, equity: value })),
    [signalResult],
  );

  const run = () => {
    if (!selected) {
      setMessage("Register a strategy before running a backtest.");
      return;
    }
    setStatus("running");
    setMessage(null);
    setSignalResult(null);
    apiPost<BacktestResult>("/api/backtests", {
      strategy_id: selected,
      equity,
      turnovers: [0.12, 0.18, 0.16, 0.11],
    })
      .then((payload) => {
        setResult(payload);
        setStatus("complete");
      })
      .catch((error: Error) => {
        if (status === "fallback") {
          setResult({
            strategy_id: selected,
            metrics: { cagr: 0.139, sharpe: 1.18, max_drawdown: -0.031, calmar: 4.48, turnover: 0.14 },
          });
          setStatus("fallback result");
          return;
        }
        setMessage(error.message);
        setStatus("idle");
      });
  };

  const runSignalBacktest = () => {
    const universe = universeText.split(",").map((item) => item.trim().toUpperCase()).filter(Boolean);
    if (universe.length === 0) {
      setMessage("Enter at least one symbol for the signal backtest.");
      return;
    }
    setStatus("running signal");
    setMessage(null);
    setResult(null);
    apiPost<SignalBacktestResult>("/api/backtests/signal", {
      market: signalMarket,
      universe,
      parameters: {
        lookback_long: 120,
        lookback_short: 20,
        top_n: 20,
        exit_rank: 50,
        max_weight: 0.08,
      },
      starting_cash: 100000,
    })
      .then((payload) => {
        setSignalResult(payload);
        setStatus("complete");
      })
      .catch((error: Error) => {
        setMessage(error.message);
        setStatus("idle");
      });
  };

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-header">
          <h2>Backtest Run</h2>
          <span>{status}</span>
        </div>
        {message && <p className="inline-message" role="status">{message}</p>}
        <div className="form-grid">
          <label>
            Strategy
            <select value={selected} onChange={(event) => setSelected(event.target.value)}>
              {strategies.map((strategy) => (
                <option key={strategy.id} value={strategy.id}>{strategy.name} - {strategy.market}</option>
              ))}
            </select>
          </label>
          <label>
            Scenario
            <select defaultValue="baseline">
              <option value="baseline">baseline equity sample</option>
              <option value="stress">liquidity stress sample</option>
            </select>
          </label>
          <button className="primary-button" disabled={!selected || status === "running"} type="button" onClick={run}>
            <Play size={16} /> Run
          </button>
        </div>
        {strategies.length === 0 && (
          <div className="empty-state compact">
            <strong>No strategies available</strong>
            <span>Register an evolution candidate before submitting a backtest.</span>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Signal Backtest</h2>
          <span>cached daily bars</span>
        </div>
        <div className="form-grid signal-backtest-form">
          <label>
            Market
            <select value={signalMarket} onChange={(event) => setSignalMarket(event.target.value as "US" | "CN")}>
              <option value="US">US</option>
              <option value="CN">CN</option>
            </select>
          </label>
          <label>
            Universe
            <input value={universeText} onChange={(event) => setUniverseText(event.target.value)} />
          </label>
          <button className="primary-button" disabled={status === "running signal"} type="button" onClick={runSignalBacktest}>
            <TrendingUp size={16} /> Run Signal
          </button>
        </div>
      </section>

      <div className="panel-grid two">
        <section className="panel">
          <div className="panel-header">
            <h2>Equity Path</h2>
            <span>{chartData.length} observations</span>
          </div>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height="100%" minHeight={240} minWidth={240}>
              <LineChart data={chartData}>
                <XAxis dataKey="step" tickLine={false} axisLine={false} />
                <YAxis tickLine={false} axisLine={false} width={58} />
                <Tooltip />
                <Line type="monotone" dataKey="equity" stroke="#0f766e" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
        <section className="panel">
          <div className="panel-header">
            <h2>Result Metrics</h2>
            <FlaskConical size={18} />
          </div>
          <div className="metric-grid compact">
            {["cagr", "sharpe", "max_drawdown", "calmar", "turnover"].map((metric) => (
              <div key={metric}>
                <span>{metric}</span>
                <strong>{metricValue(signalResult ?? result, metric)}</strong>
              </div>
            ))}
            {signalResult && (
              <>
                <div><span>trades</span><strong>{signalResult.trades.length}</strong></div>
                <div><span>sessions</span><strong>{signalResult.equity_curve.length}</strong></div>
              </>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

export default Backtests;
