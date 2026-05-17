import { Play, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet } from "../api";

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
  const [strategies, setStrategies] = useState<Strategy[]>(fallbackStrategies);
  const [state, setState] = useState<"loading" | "ready" | "fallback">("loading");

  useEffect(() => {
    apiGet<Strategy[]>("/api/strategies")
      .then((rows) => {
        setStrategies(rows.length ? rows : fallbackStrategies);
        setState("ready");
      })
      .catch(() => setState("fallback"));
  }, []);

  return (
    <div className="page-stack">
      <div className="toolbar">
        <span className={`pill ${state === "fallback" ? "warning" : "ok"}`}>
          {state === "loading" ? "Loading" : state === "fallback" ? "Fallback rows" : "Synced"}
        </span>
        <button className="icon-button" type="button" title="Refresh">
          <RefreshCw size={16} />
        </button>
      </div>
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
            {strategies.map((strategy) => {
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
                    <button className="icon-button" type="button" title="Queue action">
                      <Play size={15} />
                    </button>
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
