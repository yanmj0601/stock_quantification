import { CheckCircle2, GitBranch, Play, Send } from "lucide-react";
import { useState } from "react";
import { apiPost } from "../api";

type Candidate = {
  id: string;
  template_id: string;
  parameters: Record<string, unknown>;
};

type Strategy = {
  id: string;
  status: string;
};

const offlineCandidates: Candidate[] = [
  {
    id: "cand_offline_001",
    template_id: "momentum",
    parameters: { market: "US", lookback: 20, stop: 0.08 },
  },
  {
    id: "cand_offline_002",
    template_id: "momentum",
    parameters: { market: "US", lookback: 60, stop: 0.1 },
  },
];

const numberList = (value: string) =>
  value
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item));

function Evolution() {
  const [templateId, setTemplateId] = useState("momentum");
  const [market, setMarket] = useState("US");
  const [lookback, setLookback] = useState("20,60,120");
  const [stop, setStop] = useState("0.08,0.10");
  const [maxCandidates, setMaxCandidates] = useState(6);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [registered, setRegistered] = useState<Record<string, string>>({});
  const [state, setState] = useState<"idle" | "generating" | "generated" | "fallback" | "registering">("idle");
  const [message, setMessage] = useState<string | null>(null);

  const generate = () => {
    setState("generating");
    setMessage(null);
    setRegistered({});
    apiPost<{ candidates: Candidate[] }>("/api/evolution", {
      template_id: templateId,
      parameter_space: {
        market: [market],
        lookback: numberList(lookback),
        stop: numberList(stop),
      },
      max_candidates: maxCandidates,
    })
      .then((payload) => {
        setCandidates(payload.candidates);
        setState("generated");
      })
      .catch((error: Error) => {
        setCandidates(offlineCandidates);
        setMessage(`${error.message}. Showing offline example candidates.`);
        setState("fallback");
      });
  };

  const register = (candidate: Candidate) => {
    const candidateMarket =
      typeof candidate.parameters.market === "string" ? candidate.parameters.market : market;
    setState("registering");
    setMessage(null);
    apiPost<Strategy>("/api/strategies", {
      name: `${candidate.template_id}_${candidate.id}`,
      market: candidateMarket,
      asset_class: candidateMarket === "CRYPTO" ? "crypto" : "equity",
      template_id: candidate.template_id,
      parameters: candidate.parameters,
    })
      .then((strategy) => {
        setRegistered((rows) => ({ ...rows, [candidate.id]: strategy.id }));
        setMessage(`Registered ${strategy.id} as ${strategy.status}.`);
        setState("generated");
      })
      .catch((error: Error) => {
        setMessage(error.message);
        setState("generated");
      });
  };

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-header">
          <h2>Candidate Factory</h2>
          <span>{state}</span>
        </div>
        <div className="evolution-controls">
          <label>
            Template
            <input value={templateId} onChange={(event) => setTemplateId(event.target.value)} />
          </label>
          <label>
            Market
            <select value={market} onChange={(event) => setMarket(event.target.value)}>
              <option>US</option>
              <option>CN</option>
              <option>CRYPTO</option>
            </select>
          </label>
          <label>
            Lookback
            <input value={lookback} onChange={(event) => setLookback(event.target.value)} />
          </label>
          <label>
            Stop
            <input value={stop} onChange={(event) => setStop(event.target.value)} />
          </label>
          <label>
            Max
            <input
              min={1}
              type="number"
              value={maxCandidates}
              onChange={(event) => setMaxCandidates(Number(event.target.value))}
            />
          </label>
          <button className="primary-button" type="button" onClick={generate}>
            <Play size={16} /> Generate
          </button>
        </div>
        {message && <p className="inline-message" role="status">{message}</p>}
      </section>

      <div className="table-wrap">
        <table className="data-table evolution-table">
          <thead>
            <tr>
              <th>Candidate</th>
              <th>Template</th>
              <th>Market</th>
              <th>Parameters</th>
              <th>Lineage</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            {candidates.length === 0 ? (
              <tr>
                <td colSpan={6}>
                  <div className="empty-state compact">
                    <strong>No candidates generated</strong>
                    <span>Configure the search space and generate candidates from the API.</span>
                  </div>
                </td>
              </tr>
            ) : candidates.map((candidate, index) => {
              const candidateMarket =
                typeof candidate.parameters.market === "string" ? candidate.parameters.market : market;
              const registeredId = registered[candidate.id];
              return (
                <tr key={candidate.id}>
                  <td><strong>{candidate.id}</strong></td>
                  <td>{candidate.template_id}</td>
                  <td>{candidateMarket}</td>
                  <td><code>{JSON.stringify(candidate.parameters)}</code></td>
                  <td><GitBranch size={15} /> gen-{index + 1}</td>
                  <td>
                    {registeredId ? (
                      <span className="badge pass"><CheckCircle2 size={13} /> {registeredId}</span>
                    ) : (
                      <button
                        className="small-button"
                        disabled={state === "fallback" || state === "registering"}
                        onClick={() => register(candidate)}
                        type="button"
                      >
                        <Send size={14} /> Register
                      </button>
                    )}
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

export default Evolution;
