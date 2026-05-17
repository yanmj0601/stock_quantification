import { ScrollText } from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet } from "../api";

type AuditEvent = {
  id: string;
  entity_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

const fallbackEvents: AuditEvent[] = [
  {
    id: "audit_001",
    entity_id: "str_us_momo",
    event_type: "strategy.created",
    payload: { name: "us_momentum_breakout" },
    created_at: "2026-05-17T09:30:00Z",
  },
  {
    id: "audit_002",
    entity_id: "risk",
    event_type: "risk.mode_changed",
    payload: { mode: "research-only" },
    created_at: "2026-05-17T09:35:00Z",
  },
];

function AuditLog() {
  const [events, setEvents] = useState<AuditEvent[]>(fallbackEvents);
  const [state, setState] = useState("loading");

  useEffect(() => {
    apiGet<AuditEvent[]>("/api/audit-events")
      .then((rows) => {
        setEvents(rows.length ? rows : fallbackEvents);
        setState("ready");
      })
      .catch(() => setState("fallback"));
  }, []);

  return (
    <div className="page-stack">
      <div className="toolbar">
        <span className={`pill ${state === "fallback" ? "warning" : "ok"}`}>{state}</span>
        <span>{events.length} events</span>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Event</th>
              <th>Entity</th>
              <th>Payload</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.id}>
                <td>{new Date(event.created_at).toLocaleString()}</td>
                <td><ScrollText size={15} /> {event.event_type}</td>
                <td>{event.entity_id}</td>
                <td><code>{JSON.stringify(event.payload)}</code></td>
                <td><span className="badge pass">api</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default AuditLog;
