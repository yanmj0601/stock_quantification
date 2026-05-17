import { CircleDollarSign, Plus, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api";

type Account = { id: string; name: string; cash: number; nav: number };
type Order = {
  id: string;
  account_id: string;
  symbol: string;
  market: string;
  quantity: number;
  limit_price: number;
  status: string;
  created_at: string;
};
type Fill = {
  id: string;
  order_id: string;
  account_id: string;
  symbol: string;
  market: string;
  quantity: number;
  fill_price: number;
  fee: number;
  created_at: string;
};
type Position = {
  account_id: string;
  symbol: string;
  market: string;
  quantity: number;
  average_cost: number;
};

const fallbackAccounts: Account[] = [
  { id: "paper_us", name: "paper-us", cash: 49820, nav: 103420 },
  { id: "paper_cn", name: "paper-cn", cash: 25000, nav: 25140 },
];
const fallbackOrders: Order[] = [
  {
    id: "ord_offline_001",
    account_id: "paper_us",
    symbol: "AAPL",
    market: "US",
    quantity: 10,
    limit_price: 185,
    status: "filled",
    created_at: "2026-05-17T09:30:00Z",
  },
];

function PaperTrading() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [fills, setFills] = useState<Fill[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [selected, setSelected] = useState("");
  const [state, setState] = useState("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [symbol, setSymbol] = useState("AAPL");
  const [market, setMarket] = useState("US");
  const [quantity, setQuantity] = useState(10);
  const [limitPrice, setLimitPrice] = useState(185);

  const load = (nextSelected?: string) => {
    setState("loading");
    Promise.all([
      apiGet<Account[]>("/api/paper/accounts"),
      apiGet<Order[]>("/api/paper/orders"),
      apiGet<Fill[]>("/api/paper/fills"),
    ])
      .then(([accountRows, orderRows, fillRows]) => {
        const selectedId = nextSelected ?? selected;
        const accountId = accountRows.some((account) => account.id === selectedId)
          ? selectedId
          : accountRows[0]?.id ?? "";
        setAccounts(accountRows);
        setOrders(orderRows);
        setFills(fillRows);
        setSelected(accountId);
        setMessage(null);
        setState("ready");
        if (!accountId) {
          setPositions([]);
          return;
        }
        apiGet<Position[]>(`/api/paper/accounts/${accountId}/positions`)
          .then(setPositions)
          .catch(() => setPositions([]));
      })
      .catch(() => {
        setAccounts(fallbackAccounts);
        setOrders(fallbackOrders);
        setFills([]);
        setPositions([]);
        setSelected(fallbackAccounts[0].id);
        setMessage("API unavailable. Showing offline example paper account data.");
        setState("fallback");
      });
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!selected || state === "fallback") return;
    apiGet<Position[]>(`/api/paper/accounts/${selected}/positions`)
      .then(setPositions)
      .catch(() => setPositions([]));
  }, [selected, state]);

  const createAccount = () => {
    setState("creating");
    apiPost<Account>("/api/paper/accounts", { name: `paper-${accounts.length + 1}`, starting_cash: 100000 })
      .then((account) => {
        load(account.id);
      })
      .catch((error: Error) => {
        setMessage(error.message);
        setState("ready");
      });
  };

  const submitOrder = () => {
    if (!selected) {
      setMessage("Create a paper account before submitting an order.");
      return;
    }
    setState("submitting");
    setMessage(null);
    apiPost<Order>("/api/paper/orders", {
      account_id: selected,
      symbol,
      market,
      quantity,
      limit_price: limitPrice,
    })
      .then(() => {
        setMessage(`Submitted and filled ${quantity} ${symbol} @ ${limitPrice}.`);
        load(selected);
      })
      .catch((error: Error) => {
        setMessage(error.message);
        setState("ready");
      });
  };

  const selectedOrders = orders.filter((order) => !selected || order.account_id === selected);
  const selectedFills = fills.filter((fill) => !selected || fill.account_id === selected);
  const paperNotional = positions.reduce(
    (sum, position) => sum + position.quantity * position.average_cost,
    0,
  );

  return (
    <div className="page-stack">
      <div className="toolbar">
        <span className={`pill ${state === "fallback" ? "warning" : "ok"}`}>
          {state === "fallback" ? "offline example data" : state}
        </span>
        <button
          className="primary-button"
          disabled={state === "fallback" || state === "creating"}
          type="button"
          onClick={createAccount}
        >
          <Plus size={16} /> Account
        </button>
      </div>
      {message && <p className="inline-message" role="status">{message}</p>}
      <div className="panel-grid two">
        <section className="panel">
          <div className="panel-header">
            <h2>Accounts</h2>
            <CircleDollarSign size={18} />
          </div>
          <div className="account-list">
            {accounts.length === 0 ? (
              <div className="empty-state compact">
                <strong>No paper accounts</strong>
                <span>Create an account to stage paper orders.</span>
              </div>
            ) : (
              accounts.map((account) => (
                <button
                  aria-pressed={selected === account.id}
                  className={`account-row ${selected === account.id ? "selected" : ""}`}
                  key={account.id}
                  onClick={() => setSelected(account.id)}
                  type="button"
                >
                  <span>{account.name}</span>
                  <strong>${account.nav.toLocaleString()}</strong>
                  <small>cash ${account.cash.toLocaleString()}</small>
                </button>
              ))
            )}
          </div>
        </section>
        <section className="panel">
          <div className="panel-header">
            <h2>Order Ticket</h2>
            <span>paper-only</span>
          </div>
          <div className="form-grid ticket">
            <label>Account<select value={selected} onChange={(event) => setSelected(event.target.value)}>{accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label>
            <label>Symbol<input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} /></label>
            <label>Market<select value={market} onChange={(event) => setMarket(event.target.value)}><option>US</option><option>CN</option><option>CRYPTO</option></select></label>
            <label>Qty<input min={1} value={quantity} type="number" onChange={(event) => setQuantity(Number(event.target.value))} /></label>
            <label>Limit<input min={0} step="0.01" value={limitPrice} type="number" onChange={(event) => setLimitPrice(Number(event.target.value))} /></label>
            <button
              className="primary-button"
              disabled={state === "fallback" || state === "submitting" || !selected}
              onClick={submitOrder}
              type="button"
            >
              <Send size={16} /> Submit
            </button>
          </div>
        </section>
      </div>

      <div className="panel-grid two">
        <section className="panel">
          <div className="panel-header">
            <h2>Positions</h2>
            <span>${paperNotional.toLocaleString()} cost basis</span>
          </div>
          {positions.length === 0 ? (
            <div className="empty-state compact">
              <strong>No positions</strong>
              <span>Filled paper orders will update positions here.</span>
            </div>
          ) : (
            <div className="compact-table">
              {positions.map((position) => (
                <div key={`${position.account_id}-${position.symbol}-${position.market}`}>
                  <strong>{position.symbol}</strong>
                  <span>{position.market}</span>
                  <span>{position.quantity} @ ${position.average_cost.toFixed(2)}</span>
                </div>
              ))}
            </div>
          )}
        </section>
        <section className="panel">
          <div className="panel-header">
            <h2>Paper vs Backtest</h2>
            <span>decay monitor</span>
          </div>
          <div className="metric-grid compact">
            <div><span>Backtest CAGR</span><strong>-</strong></div>
            <div><span>Paper CAGR</span><strong>-</strong></div>
            <div><span>Decay</span><strong>{selectedFills.length ? "warming" : "-"}</strong></div>
            <div><span>Filled orders</span><strong>{selectedFills.length}</strong></div>
          </div>
        </section>
      </div>

      <div className="table-wrap">
        <table className="data-table paper-table">
          <thead>
            <tr>
              <th>Order</th>
              <th>Symbol</th>
              <th>Market</th>
              <th>Qty</th>
              <th>Limit</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {selectedOrders.length === 0 ? (
              <tr>
                <td colSpan={7}>
                  <div className="empty-state compact">
                    <strong>No paper orders</strong>
                    <span>Submit from the order ticket to create an auditable paper order.</span>
                  </div>
                </td>
              </tr>
            ) : selectedOrders.map((order) => (
              <tr key={order.id}>
                <td><strong>{order.id}</strong><small>{order.account_id}</small></td>
                <td>{order.symbol}</td>
                <td>{order.market}</td>
                <td>{order.quantity}</td>
                <td>${order.limit_price.toFixed(2)}</td>
                <td><span className={`badge ${order.status}`}>{order.status}</span></td>
                <td>{new Date(order.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default PaperTrading;
