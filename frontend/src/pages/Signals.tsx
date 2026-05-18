import { CheckCircle2, FilePlus2, Play, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "../api";

type Market = "US" | "CN" | "CRYPTO";
type SignalSide = "buy" | "hold" | "sell";

type Account = { id: string; name: string; cash: number; nav: number };
type SignalScan = {
  id: string;
  strategy_template: string;
  market_scope: Market[];
  as_of_date: string;
  coverage: Record<string, number>;
  status: string;
  error_message: string;
  created_at: string;
};
type SignalResult = {
  scan_id: string;
  symbol: string;
  market: Market;
  name: string;
  name_zh: string;
  close: number;
  signal: SignalSide;
  score: number;
  target_weight: number;
  reason: string;
  risk_flags: string[];
  as_of_date: string;
  rank: number;
};
type Draft = {
  id: string;
  symbol: string;
  market: Market;
  side: SignalSide;
  estimated_quantity: number;
  reference_price: number;
  status: string;
};

const defaultParameters = {
  lookback_long: 120,
  lookback_short: 20,
  top_n: 20,
  hold_rank: 50,
  max_weight: 0.08,
  min_amount: 10000000,
  max_volatility: 0.45,
  max_drawdown: 0.35,
};

const fallbackResults: SignalResult[] = [
  {
    scan_id: "offline",
    symbol: "AAPL",
    market: "US",
    name: "Apple",
    name_zh: "苹果",
    close: 189.72,
    signal: "buy",
    score: 0.91,
    target_weight: 0.08,
    reason: "120日动量排名靠前，20日动量确认，风险过滤通过",
    risk_flags: [],
    as_of_date: "2026-05-15",
    rank: 1,
  },
  {
    scan_id: "offline",
    symbol: "600519",
    market: "CN",
    name: "贵州茅台",
    name_zh: "贵州茅台",
    close: 1492.8,
    signal: "hold",
    score: 0.76,
    target_weight: 0.052,
    reason: "仍在Top50内，维持持仓观察",
    risk_flags: [],
    as_of_date: "2026-05-15",
    rank: 2,
  },
  {
    scan_id: "offline",
    symbol: "TSLA",
    market: "US",
    name: "Tesla",
    name_zh: "特斯拉",
    close: 176.24,
    signal: "sell",
    score: 0.18,
    target_weight: 0,
    reason: "跌出Top50并触发回撤风险，退出候选",
    risk_flags: ["drawdown_limit"],
    as_of_date: "2026-05-15",
    rank: 58,
  },
];

const pct = (value: number) => `${(value * 100).toFixed(1)}%`;

function Signals() {
  const [scans, setScans] = useState<SignalScan[]>([]);
  const [selectedScanId, setSelectedScanId] = useState("");
  const [results, setResults] = useState<SignalResult[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedAccount, setSelectedAccount] = useState("");
  const [marketMode, setMarketMode] = useState<"global" | Market>("global");
  const [state, setState] = useState("loading");
  const [message, setMessage] = useState<string | null>(null);

  const loadScans = () => {
    setState("loading");
    Promise.all([apiGet<SignalScan[]>("/api/signals/scans"), apiGet<Account[]>("/api/paper/accounts")])
      .then(([scanRows, accountRows]) => {
        setScans(scanRows);
        setAccounts(accountRows);
        setSelectedAccount((current) => current || accountRows[0]?.id || "");
        const nextScanId = selectedScanId || scanRows[0]?.id || "";
        setSelectedScanId(nextScanId);
        setMessage(null);
        setState("ready");
        if (nextScanId) {
          loadResults(nextScanId);
        } else {
          setResults([]);
        }
      })
      .catch(() => {
        setScans([]);
        setAccounts([]);
        setResults(fallbackResults);
        setSelectedScanId("offline");
        setMessage("API unavailable or no scan history yet. Showing offline example signals.");
        setState("fallback");
      });
  };

  const loadResults = (scanId: string) => {
    if (scanId === "offline") return;
    apiGet<SignalResult[]>(`/api/signals/scans/${scanId}/results`)
      .then(setResults)
      .catch((error: Error) => setMessage(error.message));
  };

  useEffect(() => {
    loadScans();
  }, []);

  const visibleResults = useMemo(() => {
    const rows = marketMode === "global"
      ? results
      : results.filter((result) => result.market === marketMode);
    return rows
      .slice()
      .sort((left, right) => {
        if (left.market !== right.market && marketMode !== "global") return left.market.localeCompare(right.market);
        return right.score - left.score;
      })
      .slice(0, marketMode === "global" ? 40 : 20);
  }, [marketMode, results]);

  const runScan = () => {
    setState("running");
    setMessage(null);
    apiPost<SignalScan>("/api/signals/scans", {
      strategy_template: "cross_sectional_momentum",
      markets: ["US", "CN"],
      parameters: defaultParameters,
    })
      .then((scan) => {
        setScans((rows) => [scan, ...rows.filter((row) => row.id !== scan.id)]);
        setSelectedScanId(scan.id);
        setState("ready");
        loadResults(scan.id);
      })
      .catch((error: Error) => {
        setMessage(error.message);
        setState("ready");
        loadScans();
      });
  };

  const selectScan = (scanId: string) => {
    setSelectedScanId(scanId);
    loadResults(scanId);
  };

  const createDraft = (result: SignalResult) => {
    if (!selectedAccount) {
      setMessage("需要先创建或选择一个 paper account。");
      return;
    }
    setState("drafting");
    setMessage(null);
    apiPost<Draft>("/api/paper/drafts", {
      scan_id: result.scan_id,
      account_id: selectedAccount,
      strategy_id: "cross_sectional_momentum",
      symbol: result.symbol,
      market: result.market,
      side: result.signal,
      target_weight: result.target_weight,
      current_weight: result.signal === "sell" ? 0.08 : 0,
      reference_price: result.close,
      reason: result.reason,
      risk_flags: result.risk_flags,
      trade_session: result.as_of_date,
    })
      .then((draft) => {
        setMessage(`已生成 ${draft.symbol} ${draft.side} 草稿，数量 ${draft.estimated_quantity}，状态 ${draft.status}。`);
        setState("ready");
      })
      .catch((error: Error) => {
        setMessage(error.message);
        setState("ready");
      });
  };

  const latestScan = scans.find((scan) => scan.id === selectedScanId);
  const buys = results.filter((result) => result.signal === "buy").length;
  const holds = results.filter((result) => result.signal === "hold").length;
  const sells = results.filter((result) => result.signal === "sell").length;

  return (
    <div className="page-stack">
      <div className="toolbar signal-toolbar">
        <span className={`pill ${state === "fallback" ? "warning" : "ok"}`}>{state}</span>
        <div className="segmented" role="group" aria-label="Signal market scope">
          {(["global", "US", "CN"] as const).map((mode) => (
            <button
              aria-pressed={marketMode === mode}
              className={marketMode === mode ? "active" : ""}
              key={mode}
              onClick={() => setMarketMode(mode)}
              type="button"
            >
              {mode === "global" ? "Global Top40" : `${mode} Top20`}
            </button>
          ))}
        </div>
        <select value={selectedScanId} onChange={(event) => selectScan(event.target.value)} aria-label="Signal scan">
          {selectedScanId === "offline" && <option value="offline">offline example</option>}
          {scans.map((scan) => (
            <option key={scan.id} value={scan.id}>{scan.as_of_date} - {scan.status}</option>
          ))}
        </select>
        <select value={selectedAccount} onChange={(event) => setSelectedAccount(event.target.value)} aria-label="Paper account">
          <option value="">No paper account</option>
          {accounts.map((account) => (
            <option key={account.id} value={account.id}>{account.name}</option>
          ))}
        </select>
        <button className="primary-button" disabled={state === "running"} type="button" onClick={runScan}>
          <Play size={16} /> Run Scan
        </button>
        <button className="icon-button" type="button" title="Refresh" onClick={loadScans}>
          <RefreshCw size={16} />
        </button>
      </div>
      {message && <p className="inline-message" role="status">{message}</p>}

      <div className="kpi-grid signal-kpis">
        <div className="kpi-tile"><CheckCircle2 size={18} /><span>Scan</span><strong>{latestScan?.status ?? state}</strong></div>
        <div className="kpi-tile"><span>Buy</span><strong>{buys}</strong></div>
        <div className="kpi-tile"><span>Hold</span><strong>{holds}</strong></div>
        <div className="kpi-tile"><span>Sell</span><strong>{sells}</strong></div>
      </div>

      <section className="panel">
        <div className="panel-header">
          <h2>Signal Snapshot</h2>
          <span>{latestScan ? `${latestScan.as_of_date} coverage ${Object.entries(latestScan.coverage).map(([key, value]) => `${key} ${pct(value)}`).join(" / ")}` : "no scan"}</span>
        </div>
        <div className="table-wrap embedded">
          <table className="data-table signal-table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Symbol</th>
                <th>Market</th>
                <th>Signal</th>
                <th>Score</th>
                <th>Weight</th>
                <th>Close</th>
                <th>Risk</th>
                <th>Reason</th>
                <th>Draft</th>
              </tr>
            </thead>
            <tbody>
              {visibleResults.length === 0 ? (
                <tr>
                  <td colSpan={10}>
                    <div className="empty-state compact">
                      <strong>No signals yet</strong>
                      <span>Run a scan after market data is synced.</span>
                    </div>
                  </td>
                </tr>
              ) : visibleResults.map((result) => (
                <tr key={`${result.scan_id}-${result.market}-${result.symbol}-${result.rank}`}>
                  <td>{result.rank}</td>
                  <td><strong>{result.symbol}</strong><small>{result.name_zh || result.name}</small></td>
                  <td>{result.market}</td>
                  <td><span className={`badge ${result.signal}`}>{result.signal}</span></td>
                  <td>{result.score.toFixed(3)}</td>
                  <td>{pct(result.target_weight)}</td>
                  <td>{result.close.toFixed(2)}</td>
                  <td>{result.risk_flags.length ? result.risk_flags.join(", ") : "pass"}</td>
                  <td title={result.reason}>{result.reason}</td>
                  <td>
                    <button
                      className="small-button"
                      disabled={state === "fallback" || state === "drafting" || result.signal === "hold"}
                      onClick={() => createDraft(result)}
                      type="button"
                    >
                      <FilePlus2 size={14} /> Draft
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export default Signals;
