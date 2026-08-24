import { useMemo, useState } from "react";
import { Candidate } from "../api/client";

interface Props {
  candidates: Candidate[];
}

type SortKey = "fit_score" | "name";

export function CandidateTable({ candidates }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("fit_score");
  const [descending, setDescending] = useState(true);

  const sorted = useMemo(() => {
    const copy = [...candidates];
    copy.sort((a, b) => {
      const dir = descending ? -1 : 1;
      if (sortKey === "fit_score") return (a.fit_score - b.fit_score) * dir;
      return a.name.localeCompare(b.name) * dir;
    });
    return copy;
  }, [candidates, sortKey, descending]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setDescending((d) => !d);
    } else {
      setSortKey(key);
      setDescending(true);
    }
  }

  const maxScore = Math.max(1, ...candidates.map((c) => c.fit_score));

  if (candidates.length === 0) {
    return <p style={{ color: "var(--ink-dim)" }}>No candidates yet.</p>;
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table className="candidate-table">
        <thead>
          <tr>
            <th onClick={() => toggleSort("name")}>Name</th>
            <th>Headline</th>
            <th>Location</th>
            <th onClick={() => toggleSort("fit_score")}>Fit score</th>
            <th>Signals</th>
            <th>Profile</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((c) => (
            <tr key={c.linkedin_url}>
              <td>{c.name}</td>
              <td>{c.headline ?? "—"}</td>
              <td>{c.location ?? "—"}</td>
              <td>
                <span className="fit-score">{c.fit_score}</span>
                <span className="fit-bar-track">
                  <span
                    className="fit-bar-fill"
                    style={{ width: `${(c.fit_score / maxScore) * 100}%` }}
                  />
                </span>
              </td>
              <td className="fit-indicators">{c.fit_indicators.join(", ") || "—"}</td>
              <td>
                <a href={c.linkedin_url} target="_blank" rel="noreferrer">
                  Open ↗
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
