import { useEffect, useRef, useState } from "react";
import { downloadUrl, getJob, Job, XraySearchOutcome } from "../api/client";
import { CandidateTable } from "./CandidateTable";

interface Props {
  jobId: string;
  onSettled?: (job: Job) => void;
}

const POLL_MS = 1500;

export function JobProgress({ jobId, onSettled }: Props) {
  const [job, setJob] = useState<Job | null>(null);
  const settledRef = useRef(false);

  useEffect(() => {
    settledRef.current = false;
    let cancelled = false;

    async function poll() {
      try {
        const latest = await getJob(jobId);
        if (cancelled) return;
        setJob(latest);
        if (latest.status === "succeeded" || latest.status === "failed") {
          if (!settledRef.current) {
            settledRef.current = true;
            onSettled?.(latest);
          }
          return;
        }
        setTimeout(poll, POLL_MS);
      } catch {
        if (!cancelled) setTimeout(poll, POLL_MS);
      }
    }

    poll();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  if (!job) {
    return <p className="progress-message">Connecting…</p>;
  }

  const running = job.status === "pending" || job.status === "running";

  return (
    <div>
      {running && (
        <>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${job.progress_percent}%` }} />
          </div>
          <p className="progress-message">{job.progress_message || "Working…"}</p>
        </>
      )}

      {job.status === "failed" && (
        <div className="error-box">{job.error ?? "Job failed with no error detail."}</div>
      )}

      {job.status === "succeeded" && job.result && isXrayOutcome(job.result) && (
        <XrayResult jobId={job.id} outcome={job.result} />
      )}
    </div>
  );
}

function isXrayOutcome(result: Job["result"]): result is XraySearchOutcome {
  return !!result && "candidates" in result;
}

function XrayResult({ jobId, outcome }: { jobId: string; outcome: XraySearchOutcome }) {
  return (
    <div>
      <div className="summary-strip">
        <span>
          collected <strong>{outcome.collected_count}</strong>
        </span>
        <span>
          above min-score <strong>{outcome.after_score_count}</strong>
        </span>
        <span>
          in years band <strong>{outcome.after_years_count}</strong>
        </span>
        <span>
          exported <strong>{outcome.candidates.length}</strong>
        </span>
      </div>
      <div className="download-row">
        <a className="btn btn-ghost btn-sm" href={downloadUrl(jobId, "excel")}>
          Download Excel
        </a>
        <a className="btn btn-ghost btn-sm" href={downloadUrl(jobId, "json")}>
          Download JSON
        </a>
      </div>
      <CandidateTable candidates={outcome.candidates} />
    </div>
  );
}
