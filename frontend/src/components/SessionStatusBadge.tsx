import { useEffect, useState } from "react";
import { getSessionStatus, Job, SessionStatus, startLogin } from "../api/client";
import { JobProgress } from "./JobProgress";

export function SessionStatusBadge() {
  const [status, setStatus] = useState<SessionStatus | null>(null);
  const [loginJob, setLoginJob] = useState<Job | null>(null);

  async function refresh() {
    try {
      setStatus(await getSessionStatus());
    } catch {
      setStatus(null);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleLogin() {
    const job = await startLogin();
    setLoginJob(job);
  }

  const dotClass = status?.exists ? "ok" : "warn";
  const label = status?.exists
    ? `Session saved${status.modified_at ? ` · ${new Date(status.modified_at).toLocaleDateString()}` : ""}`
    : "No LinkedIn session";

  return (
    <div>
      <div className="status-line">
        <span className={`status-dot ${dotClass}`} />
        <span style={{ color: "var(--ink-dim)", fontSize: 12 }}>{label}</span>
      </div>
      {!loginJob && (
        <button className="btn btn-ghost btn-sm" style={{ marginTop: 8 }} onClick={handleLogin}>
          {status?.exists ? "Re-authenticate" : "Start login"}
        </button>
      )}
      {loginJob && (
        <div style={{ marginTop: 8 }}>
          <p style={{ fontSize: 11, color: "var(--ink-faint)" }}>
            A browser window opened on this machine — finish logging in there.
          </p>
          <JobProgress
            jobId={loginJob.id}
            onSettled={() => {
              refresh();
              setLoginJob(null);
            }}
          />
        </div>
      )}
    </div>
  );
}
