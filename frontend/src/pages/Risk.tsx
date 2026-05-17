import { Lock, PauseCircle, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet, apiPatch } from "../api";

type RiskState = {
  mode: "research-only" | "paper-only" | "paused";
  live_enabled: boolean;
  updated_at?: string;
};

const fallbackRisk: RiskState = { mode: "research-only", live_enabled: false };

function Risk() {
  const [risk, setRisk] = useState<RiskState>(fallbackRisk);
  const [state, setState] = useState("loading");

  useEffect(() => {
    apiGet<RiskState>("/api/risk")
      .then((payload) => {
        setRisk({ ...payload, live_enabled: false });
        setState("ready");
      })
      .catch(() => setState("fallback"));
  }, []);

  const setMode = (mode: RiskState["mode"]) => {
    setState("updating");
    apiPatch<RiskState>("/api/risk", { mode, reason: `admin console set ${mode}`, live_enabled: false })
      .then((payload) => {
        setRisk({ ...payload, live_enabled: false });
        setState("ready");
      })
      .catch(() => {
        setRisk({ mode, live_enabled: false });
        setState("fallback");
      });
  };

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-header">
          <h2>Mode Control</h2>
          <span>{state}</span>
        </div>
        <div className="risk-layout">
          <div className="risk-state">
            <ShieldCheck size={22} />
            <span>Current mode</span>
            <strong>{risk.mode}</strong>
          </div>
          <label className="live-lock">
            <input checked={false} disabled type="checkbox" readOnly />
            <Lock size={16} />
            <span>Live disabled</span>
          </label>
          <div className="segmented">
            {(["research-only", "paper-only", "paused"] as const).map((mode) => (
              <button
                className={risk.mode === mode ? "active" : ""}
                key={mode}
                onClick={() => setMode(mode)}
                type="button"
              >
                {mode === "paused" && <PauseCircle size={15} />}
                {mode}
              </button>
            ))}
          </div>
        </div>
      </section>

      <div className="panel-grid two">
        <section className="panel">
          <div className="panel-header">
            <h2>Guards</h2>
            <span>MVP v1</span>
          </div>
          <div className="guard-list">
            <div><span className="badge pass">locked</span><strong>Live order path</strong><small>Hard disabled by API risk service</small></div>
            <div><span className="badge pass">active</span><strong>Paper gate</strong><small>Blocked when mode is research-only or paused</small></div>
            <div><span className="badge pass">active</span><strong>Audit reason</strong><small>Mode changes include reason payloads</small></div>
          </div>
        </section>
        <section className="panel">
          <div className="panel-header">
            <h2>Exposure Budget</h2>
            <span>research limits</span>
          </div>
          <div className="metric-grid compact">
            <div><span>Gross</span><strong>0.0x</strong></div>
            <div><span>Net</span><strong>0.0x</strong></div>
            <div><span>Single name</span><strong>5%</strong></div>
            <div><span>Kill switch</span><strong>armed</strong></div>
          </div>
        </section>
      </div>
    </div>
  );
}

export default Risk;
