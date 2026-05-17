import { GitBranch, Play } from "lucide-react";
import { useState } from "react";
import { apiPost } from "../api";

type Candidate = {
  id: string;
  name: string;
  market: string;
  status: string;
  template_id: string;
  parameters: Record<string, unknown>;
};

const fallbackCandidates: Candidate[] = [
  {
    id: "cand_001",
    name: "momentum_lb20_stop8",
    market: "US",
    status: "research",
    template_id: "momentum",
    parameters: { lookback: 20, risk: { stop: 0.08 } },
  },
  {
    id: "cand_002",
    name: "momentum_lb60_stop10",
    market: "US",
    status: "research",
    template_id: "momentum",
    parameters: { lookback: 60, risk: { stop: 0.1 } },
  },
];

function Evolution() {
  const [candidates, setCandidates] = useState<Candidate[]>(fallbackCandidates);
  const [state, setState] = useState("ready");

  const generate = () => {
    setState("generating");
    apiPost<{ candidates: Candidate[] }>("/api/evolution", {
      template_id: "momentum",
      parameter_space: {
        lookback: [20, 60, 120],
        risk: [{ stop: 0.08 }, { stop: 0.1 }],
        markets: [["US"]],
      },
      max_candidates: 6,
    })
      .then((payload) => {
        setCandidates(payload.candidates.length ? payload.candidates : fallbackCandidates);
        setState("generated");
      })
      .catch(() => {
        setCandidates(fallbackCandidates);
        setState("fallback");
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
          <div>
            <strong>Template</strong>
            <span>momentum</span>
          </div>
          <div>
            <strong>Search Space</strong>
            <span>lookback x stop x market</span>
          </div>
          <button className="primary-button" type="button" onClick={generate}>
            <Play size={16} /> Generate
          </button>
        </div>
      </section>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Candidate</th>
              <th>Template</th>
              <th>Market</th>
              <th>Status</th>
              <th>Parameters</th>
              <th>Lineage</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate, index) => (
              <tr key={candidate.id}>
                <td><strong>{candidate.name}</strong><small>{candidate.id}</small></td>
                <td>{candidate.template_id}</td>
                <td>{candidate.market ?? "US"}</td>
                <td><span className={`badge ${candidate.status}`}>{candidate.status}</span></td>
                <td><code>{JSON.stringify(candidate.parameters)}</code></td>
                <td><GitBranch size={15} /> gen-{index + 1}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default Evolution;
