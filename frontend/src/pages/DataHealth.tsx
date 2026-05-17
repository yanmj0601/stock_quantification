import { DatabaseZap, HardDrive, RadioTower } from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet } from "../api";

type DataHealthPayload = { dataset_count: number };

const offlineFeeds = [
  ["bars.us.daily", "fresh", "offline example"],
  ["bars.cn.daily", "watch", "offline example"],
  ["crypto.ohlcv.1h", "fresh", "offline example"],
  ["corporate.actions", "empty", "offline example"],
];

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
          <span>{state === "fallback" ? "offline examples" : state}</span>
        </div>
        {state !== "fallback" ? (
          <div className="empty-state">
            <strong>
              {payload.dataset_count === 0 ? "No datasets registered" : `${payload.dataset_count} datasets registered`}
            </strong>
            <span>Detailed freshness, missing bar, duplicate, and anomaly reports are not loaded in this API summary yet.</span>
          </div>
        ) : (
          <div className="health-grid">
            {offlineFeeds.map(([feed, status, note]) => (
              <div className="health-row" key={feed}>
                <span>{feed}</span>
                <span className={`badge ${status}`}>{status}</span>
                <small>{note}</small>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export default DataHealth;
