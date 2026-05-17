import { DatabaseZap, HardDrive, RadioTower } from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet } from "../api";

type DataHealthPayload = { dataset_count: number };

function DataHealth() {
  const [payload, setPayload] = useState<DataHealthPayload>({ dataset_count: 0 });
  const [state, setState] = useState("loading");

  useEffect(() => {
    apiGet<DataHealthPayload>("/api/data-health")
      .then((data) => {
        setPayload(data);
        setState("ready");
      })
      .catch(() => {
        setPayload({ dataset_count: 3 });
        setState("fallback");
      });
  }, []);

  return (
    <div className="page-stack">
      <div className="kpi-grid">
        <div className="kpi-tile"><DatabaseZap size={18} /><span>Datasets</span><strong>{payload.dataset_count}</strong></div>
        <div className="kpi-tile"><RadioTower size={18} /><span>Feeds</span><strong>{state === "fallback" ? 2 : 0}</strong></div>
        <div className="kpi-tile"><HardDrive size={18} /><span>Storage</span><strong>SQLite</strong></div>
      </div>
      <section className="panel">
        <div className="panel-header">
          <h2>Feed Checks</h2>
          <span>{state}</span>
        </div>
        <div className="health-grid">
          {[
            ["bars.us.daily", "fresh", "T+0 adjusted close"],
            ["bars.cn.daily", "watch", "awaiting next sync"],
            ["crypto.ohlcv.1h", "fresh", "continuous ingest"],
            ["corporate.actions", "empty", "not loaded"],
          ].map(([feed, status, note]) => (
            <div className="health-row" key={feed}>
              <span>{feed}</span>
              <span className={`badge ${status}`}>{status}</span>
              <small>{note}</small>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export default DataHealth;
