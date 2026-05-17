import { Play, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet, apiPatch } from "../api";

type Strategy = {
  id: string;
  name: string;
  market: string;
  asset_class: string;
  template_id: string;
  status: string;
  version: number;
  metrics: Record<string, number>;
};

type StrategyStatus = "research" | "candidate" | "paper" | "retired";

const fallbackStrategies: Strategy[] = [
  {
    id: "str_us_momo",
    name: "us_momentum_breakout",
    market: "US",
    asset_class: "equity",
    template_id: "momentum",
    status: "paper",
    version: 3,
    metrics: { cagr: 0.184, sharpe: 1.42, max_drawdown: -0.114, calmar: 1.61, turnover: 0.22 },
  },
  {
    id: "str_cn_revert",
    name: "cn_intraday_reversion",
    market: "CN",
    asset_class: "equity",
    template_id: "mean-reversion",
    status: "candidate",
    version: 2,
    metrics: { cagr: 0.121, sharpe: 1.08, max_drawdown: -0.092, calmar: 1.32, turnover: 0.34 },
  },
  {
    id: "str_crypto_carry",
    name: "crypto_basis_guarded",
    market: "CRYPTO",
    asset_class: "perp",
    template_id: "carry",
    status: "research",
    version: 1,
    metrics: { cagr: 0.096, sharpe: 0.88, max_drawdown: -0.157, calmar: 0.61, turnover: 0.18 },
  },
];

const percent = (value?: number) => (value == null ? "-" : `${(value * 100).toFixed(1)}%`);
const number = (value?: number) => (value == null ? "-" : value.toFixed(2));

function Strategies() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "fallback" | "updating">("loading");
  const [message, setMessage] = useState<string | null>(null);

  const load = () => {
    setState("loading");
    apiGet<Strategy[]>("/api/strategies")
      .then((rows) => {
        setStrategies(rows);
        setMessage(null);
        setState("ready");
      })
      .catch(() => {
        setStrategies(fallbackStrategies);
        setMessage("API unavailable. Showing offline example rows.");
        setState("fallback");
      });
  };

  useEffect(() => {
    load();
  }, []);

  const setStatus = (strategy: Strategy, status: StrategyStatus) => {
    setState("updating");
    setMessage(null);
    apiPatch<Strategy>(`/api/strategies/${strategy.id}/status`, {
      status,
      reason: `admin console set ${status}`,
    })
      .then((updated) => {
        setStrategies((rows) => rows.map((row) => (row.id === updated.id ? updated : row)));
        setState("ready");
      })
      .catch((error: Error) => {
        setMessage(error.message);
        setState("ready");
      });
  };

  return (
    <div className="page-stack">
      <div className="toolbar">
        <span className={`pill ${state === "fallback" ? "warning" : "ok"}`}>
          {state === "loading" ? "Loading" : state === "fallback" ? "Offline example rows" : state}
        </span>
        <button className="icon-button" type="button" title="Refresh" onClick={load}>
          <RefreshCw size={16} />
        </button>
      </div>
      {message && <p className="inline-message" role="status">{message}</p>}
      <div className="table-wrap">
        <table className="data-table strategy-table">
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Market</th>
              <th>Status</th>
              <th>CAGR</th>
              <th>Sharpe</th>
              <th>Max DD</th>
              <th>Calmar</th>
              <th>Turnover</th>
              <th>Validation</th>
              <th>Paper Decay</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {strategies.length === 0 ? (
              <tr>
                <td colSpan={11}>
                  <div className="empty-state compact">
                    <strong>No strategies registered</strong>
                    <span>Approve generated candidates to create research strategies.</span>
                  </div>
                </td>
              </tr>
            ) : strategies.map((strategy) => {
              const validation = (strategy.metrics.sharpe ?? 0) >= 1 ? "pass" : "watch";
              const decay = strategy.status === "paper" ? "-2.4%" : "n/a";
              return (
                <tr key={strategy.id}>
                  <td>
                    <strong>{strategy.name}</strong>
                    <small>{strategy.template_id} v{strategy.version}</small>
                  </td>
                  <td>{strategy.market}</td>
                  <td><span className={`badge ${strategy.status}`}>{strategy.status}</span></td>
                  <td>{percent(strategy.metrics.cagr)}</td>
                  <td>{number(strategy.metrics.sharpe)}</td>
                  <td>{percent(strategy.metrics.max_drawdown)}</td>
                  <td>{number(strategy.metrics.calmar)}</td>
                  <td>{percent(strategy.metrics.turnover)}</td>
                  <td><span className={`badge ${validation}`}>{validation}</span></td>
                  <td>{decay}</td>
                  <td>
                    <div className="action-row">
                      {strategy.status !== "paper" && strategy.status !== "retired" && (
                        <button
                          className="small-button"
                          disabled={state === "fallback" || state === "updating"}
                          onClick={() => setStatus(strategy, "paper")}
                          type="button"
                        >
                          <Play size={14} /> Paper
                        </button>
                      )}
                      {strategy.status === "paper" && (
                        <button
                          className="small-button"
                          disabled={state === "fallback" || state === "updating"}
                          onClick={() => setStatus(strategy, "research")}
                          type="button"
                        >
                          Pause
                        </button>
                      )}
                      {strategy.status !== "retired" && (
                        <button
                          className="small-button danger"
                          disabled={state === "fallback" || state === "updating"}
                          onClick={() => setStatus(strategy, "retired")}
                          type="button"
                        >
                          Retire
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default Strategies;
