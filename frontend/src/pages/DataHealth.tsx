import { Clock3, DatabaseZap, HardDrive, RadioTower, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api";

type DataHealthPayload = { dataset_count: number };
type SyncJob = {
  id: string;
  market: string;
  provider: string;
  status: string;
  started_at: string;
  finished_at?: string;
  message: string;
};
type ScheduleConfig = {
  market: string;
  enabled: boolean;
  local_time: string;
  timezone: string;
};

const offlineFeeds = [
  ["bars.us.daily", "fresh", "offline example"],
  ["bars.cn.daily", "watch", "offline example"],
  ["crypto.ohlcv.1h", "fresh", "offline example"],
  ["corporate.actions", "empty", "offline example"],
];

function DataHealth() {
  const [payload, setPayload] = useState<DataHealthPayload>({ dataset_count: 0 });
  const [jobs, setJobs] = useState<SyncJob[]>([]);
  const [schedules, setSchedules] = useState<ScheduleConfig[]>([]);
  const [state, setState] = useState("loading");
  const [message, setMessage] = useState<string | null>(null);

  const load = () => {
    setState("loading");
    Promise.all([
      apiGet<DataHealthPayload>("/api/data-health"),
      apiGet<SyncJob[]>("/api/data-sync/jobs"),
      apiGet<ScheduleConfig[]>("/api/schedules"),
    ])
      .then(([data, jobRows, scheduleRows]) => {
        setPayload(data);
        setJobs(jobRows);
        setSchedules(scheduleRows);
        setMessage(null);
        setState("ready");
      })
      .catch(() => {
        setPayload({ dataset_count: 3 });
        setJobs([]);
        setSchedules([
          { market: "CN", enabled: true, local_time: "15:30", timezone: "Asia/Shanghai" },
          { market: "US", enabled: true, local_time: "16:30", timezone: "America/New_York" },
        ]);
        setMessage("API unavailable. Showing offline example data health.");
        setState("fallback");
      });
  };

  useEffect(() => {
    load();
  }, []);

  const requestSync = (market: "US" | "CN") => {
    setMessage(null);
    setState("syncing");
    apiPost(`/api/data-sync/${market}`, {})
      .then(() => load())
      .catch((error: Error) => {
        setMessage(error.message);
        setState("ready");
      });
  };

  return (
    <div className="page-stack">
      <div className="toolbar">
        <span className={`pill ${state === "fallback" ? "warning" : "ok"}`}>{state}</span>
        <button className="small-button" type="button" onClick={() => requestSync("US")}>Sync US</button>
        <button className="small-button" type="button" onClick={() => requestSync("CN")}>Sync CN</button>
        <button className="icon-button" type="button" title="Refresh" onClick={load}><RefreshCw size={16} /></button>
      </div>
      {message && <p className="inline-message" role="status">{message}</p>}
      <div className="kpi-grid">
        <div className="kpi-tile"><DatabaseZap size={18} /><span>Datasets</span><strong>{payload.dataset_count}</strong></div>
        <div className="kpi-tile"><RadioTower size={18} /><span>Sync Jobs</span><strong>{jobs.length}</strong></div>
        <div className="kpi-tile"><Clock3 size={18} /><span>Schedules</span><strong>{schedules.filter((schedule) => schedule.enabled).length}</strong></div>
        <div className="kpi-tile"><HardDrive size={18} /><span>Storage</span><strong>SQLite</strong></div>
      </div>
      <div className="panel-grid two">
        <section className="panel">
          <div className="panel-header">
            <h2>Sync Jobs</h2>
            <span>{state === "fallback" ? "offline examples" : `${jobs.length} jobs`}</span>
          </div>
          {jobs.length === 0 && state !== "fallback" ? (
            <div className="empty-state">
              <strong>No sync jobs yet</strong>
              <span>Run a manual sync after configuring provider credentials or local data source.</span>
            </div>
          ) : state === "fallback" ? (
            <div className="health-grid">
              {offlineFeeds.map(([feed, status, note]) => (
                <div className="health-row" key={feed}>
                  <span>{feed}</span>
                  <span className={`badge ${status}`}>{status}</span>
                  <small>{note}</small>
                </div>
              ))}
            </div>
          ) : (
            <div className="health-grid">
              {jobs.map((job) => (
                <div className="health-row" key={job.id}>
                  <span>{job.market} / {job.provider}</span>
                  <span className={`badge ${job.status}`}>{job.status}</span>
                  <small>{job.message || job.started_at}</small>
                </div>
              ))}
            </div>
          )}
        </section>
        <section className="panel">
          <div className="panel-header">
            <h2>Schedules</h2>
            <span>manual scheduler</span>
          </div>
          <div className="health-grid">
            {schedules.map((schedule) => (
              <div className="health-row schedule-row" key={schedule.market}>
                <span>{schedule.market}</span>
                <span className={`badge ${schedule.enabled ? "active" : "paused"}`}>
                  {schedule.enabled ? "active" : "paused"}
                </span>
                <small>{schedule.local_time} {schedule.timezone}</small>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

export default DataHealth;
