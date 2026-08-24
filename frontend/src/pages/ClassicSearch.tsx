import { useState } from "react";
import { DEFAULT_XRAY_REQUEST, Job, startXraySearch, XraySearchRequest } from "../api/client";
import { TagListInput } from "../components/TagListInput";
import { JobProgress } from "../components/JobProgress";

function set<K extends keyof XraySearchRequest>(
  req: XraySearchRequest,
  key: K,
  value: XraySearchRequest[K]
): XraySearchRequest {
  return { ...req, [key]: value };
}

export function ClassicSearch() {
  const [req, setReq] = useState<XraySearchRequest>(DEFAULT_XRAY_REQUEST);
  const [job, setJob] = useState<Job | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const running = job !== null && (job.status === "pending" || job.status === "running");

  const canSubmit =
    !submitting &&
    (!!req.jd_text?.trim() || !!req.jd_file?.trim() || req.title.length > 0 || req.must_have.length > 0);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    setSubmitting(true);
    try {
      const startedJob = await startXraySearch(req);
      setJob(startedJob);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <header className="page-header">
        <div className="eyebrow">Classic search</div>
        <h1>X-ray candidate search</h1>
        <p>
          Every parameter the CLI accepts is a field below — leave anything blank to use its
          default. Runs the same pipeline as <code>search_xray_jd.py</code>.
        </p>
      </header>

      <form onSubmit={handleSubmit}>
        <section className={`panel ${running ? "scanning" : ""}`}>
          <div className="panel-label">Job description</div>
          <div className="field-row">
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <label>JD text</label>
              <textarea
                value={req.jd_text ?? ""}
                onChange={(e) => setReq(set(req, "jd_text", e.target.value))}
                placeholder="Paste the job description here…"
              />
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <label>Or: path to a JD file</label>
              <input
                type="text"
                value={req.jd_file ?? ""}
                onChange={(e) => setReq(set(req, "jd_file", e.target.value))}
                placeholder="jd.txt"
              />
            </div>
            <div className="field checkbox-field" style={{ alignSelf: "end" }}>
              <input
                type="checkbox"
                id="no_llm"
                checked={req.no_llm}
                onChange={(e) => setReq(set(req, "no_llm", e.target.checked))}
              />
              <label htmlFor="no_llm">Skip LLM extraction (use manual fields only)</label>
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-label">Titles &amp; skills</div>
          <div className="field-row">
            <div className="field">
              <label>Titles</label>
              <TagListInput
                values={req.title}
                onChange={(v) => setReq(set(req, "title", v))}
                placeholder="Founding Engineer, press Enter"
              />
            </div>
            <div className="field">
              <label>Must-have skills</label>
              <TagListInput
                values={req.must_have}
                onChange={(v) => setReq(set(req, "must_have", v))}
                placeholder="TypeScript, press Enter"
              />
            </div>
            <div className="field">
              <label>Nice-to-have skills</label>
              <TagListInput
                values={req.nice_to_have}
                onChange={(v) => setReq(set(req, "nice_to_have", v))}
                placeholder="AWS, press Enter"
              />
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <label>Seniority</label>
              <select
                value={req.seniority ?? ""}
                onChange={(e) => setReq(set(req, "seniority", e.target.value || null))}
              >
                <option value="">(unspecified)</option>
                <option value="junior">junior</option>
                <option value="mid">mid</option>
                <option value="senior">senior</option>
                <option value="staff+">staff+</option>
              </select>
            </div>
            <div className="field">
              <label>Locations</label>
              <TagListInput
                values={req.location}
                onChange={(v) => setReq(set(req, "location", v))}
                placeholder="Bangalore, press Enter"
              />
            </div>
            <div className="field">
              <label>Colleges</label>
              <input
                type="text"
                value={req.colleges}
                onChange={(e) => setReq(set(req, "colleges", e.target.value))}
                placeholder="IIT,NIT,BITS"
              />
              <span className="hint">Comma-separated, ORed into every query</span>
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <label>Min years</label>
              <input
                type="number"
                value={req.min_years ?? ""}
                onChange={(e) => setReq(set(req, "min_years", e.target.value === "" ? null : Number(e.target.value)))}
              />
            </div>
            <div className="field">
              <label>Max years</label>
              <input
                type="number"
                value={req.max_years ?? ""}
                onChange={(e) => setReq(set(req, "max_years", e.target.value === "" ? null : Number(e.target.value)))}
              />
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-label">Query tuning</div>
          <div className="field-row">
            <NumberField label="Limit" value={req.limit} onChange={(v) => setReq(set(req, "limit", v))} />
            <NumberField label="Min score" value={req.min_score} onChange={(v) => setReq(set(req, "min_score", v))} />
            <NumberField label="Max queries" value={req.max_queries} onChange={(v) => setReq(set(req, "max_queries", v))} />
          </div>
          <div className="field-row">
            <NumberField
              label="Max title clauses"
              value={req.max_title_clauses}
              onChange={(v) => setReq(set(req, "max_title_clauses", v))}
            />
            <NumberField
              label="Max skill clauses"
              value={req.max_skill_clauses}
              onChange={(v) => setReq(set(req, "max_skill_clauses", v))}
            />
            <div className="field checkbox-field" style={{ alignSelf: "end" }}>
              <input
                type="checkbox"
                id="no_skill_filter"
                checked={req.no_skill_filter}
                onChange={(e) => setReq(set(req, "no_skill_filter", e.target.checked))}
              />
              <label htmlFor="no_skill_filter">Don't AND skills into query</label>
            </div>
          </div>
          <div className="field-row">
            <NumberField
              label="Results per query"
              value={req.results_per_query}
              onChange={(v) => setReq(set(req, "results_per_query", v))}
            />
            <NumberField
              label="Pages per query"
              value={req.pages_per_query}
              onChange={(v) => setReq(set(req, "pages_per_query", v))}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel-label">Reference profiles</div>
          <div className="field-row">
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <label>Reference profile URLs (one per line)</label>
              <textarea
                value={req.reference_profiles_file ?? ""}
                onChange={(e) => setReq(set(req, "reference_profiles_file", e.target.value || null))}
                placeholder="https://www.linkedin.com/in/…"
              />
              <span className="hint">Requires a saved LinkedIn session</span>
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <label>Reference cache path</label>
              <input
                type="text"
                value={req.reference_cache}
                onChange={(e) => setReq(set(req, "reference_cache", e.target.value))}
              />
            </div>
            <div className="field checkbox-field" style={{ alignSelf: "end" }}>
              <input
                type="checkbox"
                id="refresh_references"
                checked={req.refresh_references}
                onChange={(e) => setReq(set(req, "refresh_references", e.target.checked))}
              />
              <label htmlFor="refresh_references">Refresh references (skip cache)</label>
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-label">Enrichment &amp; output</div>
          <div className="field-row">
            <NumberField
              label="Enrich top N"
              value={req.enrich_top}
              onChange={(v) => setReq(set(req, "enrich_top", v))}
            />
            <div className="field">
              <label>LinkedIn session file</label>
              <input
                type="text"
                value={req.session}
                onChange={(e) => setReq(set(req, "session", e.target.value))}
              />
            </div>
            <div className="field">
              <label>Output Excel path</label>
              <input
                type="text"
                value={req.output}
                onChange={(e) => setReq(set(req, "output", e.target.value))}
                placeholder="candidates/xray_<date>.xlsx"
              />
            </div>
          </div>
        </section>

        {submitError && <div className="error-box">{submitError}</div>}

        <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
          {running ? "Searching…" : "Run search"}
        </button>
      </form>

      {job && (
        <div style={{ marginTop: 24 }}>
          <JobProgress jobId={job.id} />
        </div>
      )}
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      <input type="number" value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </div>
  );
}
