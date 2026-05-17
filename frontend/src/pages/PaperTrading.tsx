import { CircleDollarSign, Plus, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api";

type Account = { id: string; name: string; cash: number; nav: number };

const fallbackAccounts: Account[] = [
  { id: "paper_us", name: "paper-us", cash: 49820, nav: 103420 },
  { id: "paper_cn", name: "paper-cn", cash: 25000, nav: 25140 },
];

function PaperTrading() {
  const [accounts, setAccounts] = useState<Account[]>(fallbackAccounts);
  const [selected, setSelected] = useState(fallbackAccounts[0].id);
  const [state, setState] = useState("loading");

  useEffect(() => {
    apiGet<Account[]>("/api/paper/accounts")
      .then((rows) => {
        if (rows.length) {
          setAccounts(rows);
          setSelected(rows[0].id);
        }
        setState("ready");
      })
      .catch(() => setState("fallback"));
  }, []);

  const createAccount = () => {
    setState("creating");
    apiPost<Account>("/api/paper/accounts", { name: `paper-${accounts.length + 1}`, starting_cash: 100000 })
      .then((account) => {
        setAccounts((rows) => [...rows, account]);
        setSelected(account.id);
        setState("ready");
      })
      .catch(() => setState("fallback"));
  };

  return (
    <div className="page-stack">
      <div className="toolbar">
        <span className={`pill ${state === "fallback" ? "warning" : "ok"}`}>{state}</span>
        <button className="primary-button" type="button" onClick={createAccount}>
          <Plus size={16} /> Account
        </button>
      </div>
      <div className="panel-grid two">
        <section className="panel">
          <div className="panel-header">
            <h2>Accounts</h2>
            <CircleDollarSign size={18} />
          </div>
          <div className="account-list">
            {accounts.map((account) => (
              <button
                className={`account-row ${selected === account.id ? "selected" : ""}`}
                key={account.id}
                onClick={() => setSelected(account.id)}
                type="button"
              >
                <span>{account.name}</span>
                <strong>${account.nav.toLocaleString()}</strong>
                <small>cash ${account.cash.toLocaleString()}</small>
              </button>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="panel-header">
            <h2>Order Ticket</h2>
            <span>paper-only</span>
          </div>
          <div className="form-grid ticket">
            <label>Account<select value={selected} onChange={(event) => setSelected(event.target.value)}>{accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label>
            <label>Symbol<input defaultValue="AAPL" /></label>
            <label>Market<select defaultValue="US"><option>US</option><option>CN</option><option>CRYPTO</option></select></label>
            <label>Qty<input defaultValue="10" type="number" /></label>
            <label>Limit<input defaultValue="185.00" type="number" /></label>
            <button className="primary-button" type="button">
              <Send size={16} /> Stage
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

export default PaperTrading;
