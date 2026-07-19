import { DatabaseZap, RefreshCw, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiGet } from "../api";

type MarketFilter = "ALL" | "US" | "CN";
type Instrument = {
  symbol: string;
  market: "US" | "CN" | "CRYPTO";
  name: string;
  name_zh: string;
  exchange: string;
  currency: string;
  sector: string;
  index_membership: string;
  tradable: boolean;
  lot_size: number;
  bar_count: number;
  first_session: string | null;
  latest_session: string | null;
};

function StockPool() {
  const [rows, setRows] = useState<Instrument[]>([]);
  const [market, setMarket] = useState<MarketFilter>("ALL");
  const [query, setQuery] = useState("");
  const [state, setState] = useState("loading");
  const [message, setMessage] = useState<string | null>(null);

  const load = () => {
    setState("loading");
    const path = market === "ALL" ? "/api/instruments" : `/api/instruments?market=${market}`;
    apiGet<Instrument[]>(path)
      .then((payload) => {
        setRows(payload);
        setMessage(null);
        setState("ready");
      })
      .catch((error: Error) => {
        setRows([]);
        setMessage(error.message);
        setState("error");
      });
  };

  useEffect(() => {
    load();
  }, [market]);

  const visibleRows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) =>
      [row.symbol, row.name, row.name_zh, row.sector, row.index_membership]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [query, rows]);

  const cachedCount = rows.filter((row) => row.bar_count > 0).length;
  const latestSession = rows
    .map((row) => row.latest_session)
    .filter(Boolean)
    .sort()
    .at(-1);

  return (
    <div className="page-stack">
      <div className="toolbar stock-pool-toolbar">
        <span className={`pill ${state === "error" ? "warning" : "ok"}`}>{state}</span>
        <div className="segmented" role="group" aria-label="Stock pool market">
          {(["ALL", "US", "CN"] as const).map((item) => (
            <button
              aria-pressed={market === item}
              className={market === item ? "active" : ""}
              key={item}
              onClick={() => setMarket(item)}
              type="button"
            >
              {item}
            </button>
          ))}
        </div>
        <label className="search-box">
          <Search size={15} />
          <input
            aria-label="Search stock pool"
            placeholder="Search symbol, name, sector"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <button className="icon-button" type="button" title="Refresh" onClick={load}>
          <RefreshCw size={16} />
        </button>
      </div>
      {message && <p className="inline-message" role="status">{message}</p>}

      <div className="kpi-grid">
        <div className="kpi-tile"><DatabaseZap size={18} /><span>Instruments</span><strong>{rows.length}</strong></div>
        <div className="kpi-tile"><span>Cached</span><strong>{cachedCount}</strong></div>
        <div className="kpi-tile"><span>Visible</span><strong>{visibleRows.length}</strong></div>
        <div className="kpi-tile"><span>Latest Session</span><strong>{latestSession ?? "-"}</strong></div>
      </div>

      <section className="panel">
        <div className="panel-header">
          <h2>Universe Constituents</h2>
          <span>{market === "ALL" ? "S&P 500 / CSI 300" : market}</span>
        </div>
        <div className="table-wrap embedded">
          <table className="data-table stock-pool-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Market</th>
                <th>Name</th>
                <th>Index</th>
                <th>Exchange</th>
                <th>Sector</th>
                <th>Lot</th>
                <th>Bars</th>
                <th>Range</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.length === 0 ? (
                <tr>
                  <td colSpan={10}>
                    <div className="empty-state compact">
                      <strong>No instruments loaded</strong>
                      <span>Run Sync US or Sync CN in Data Sources to populate the stock pool.</span>
                    </div>
                  </td>
                </tr>
              ) : visibleRows.map((row) => (
                <tr key={`${row.market}-${row.symbol}`}>
                  <td><strong>{row.symbol}</strong><small>{row.currency}</small></td>
                  <td>{row.market}</td>
                  <td><strong>{row.name_zh || row.name}</strong><small>{row.name}</small></td>
                  <td>{row.index_membership}</td>
                  <td>{row.exchange || "-"}</td>
                  <td>{row.sector || "-"}</td>
                  <td>{row.lot_size}</td>
                  <td>{row.bar_count}</td>
                  <td>{row.first_session && row.latest_session ? `${row.first_session} -> ${row.latest_session}` : "-"}</td>
                  <td><span className={`badge ${row.tradable && row.bar_count > 0 ? "active" : "watch"}`}>{row.tradable ? "tradable" : "blocked"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export default StockPool;
