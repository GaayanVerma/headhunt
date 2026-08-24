// Mirrors backend/schemas.py + linkedin_scraper/sourcing/pipeline.py's
// XraySearchParams/XraySearchOutcome. Kept in one place so every field the
// backend accepts has a corresponding UI control - nothing hidden in code.

export interface XraySearchRequest {
  jd_file?: string | null;
  jd_text?: string | null;
  no_llm: boolean;
  title: string[];
  must_have: string[];
  nice_to_have: string[];
  seniority?: string | null;
  location: string[];
  colleges: string;
  min_years?: number | null;
  max_years?: number | null;
  limit: number;
  min_score: number;
  max_queries: number;
  max_title_clauses: number;
  max_skill_clauses: number;
  no_skill_filter: boolean;
  results_per_query: number;
  pages_per_query: number;
  reference_profiles_file?: string | null;
  reference_cache: string;
  refresh_references: boolean;
  enrich_top: number;
  session: string;
  output: string;
}

export const DEFAULT_XRAY_REQUEST: XraySearchRequest = {
  jd_file: null,
  jd_text: "",
  no_llm: false,
  title: [],
  must_have: [],
  nice_to_have: [],
  seniority: null,
  location: [],
  colleges: "",
  min_years: null,
  max_years: null,
  limit: 200,
  min_score: 15,
  max_queries: 20,
  max_title_clauses: 4,
  max_skill_clauses: 6,
  no_skill_filter: false,
  results_per_query: 10,
  pages_per_query: 1,
  reference_profiles_file: null,
  reference_cache: "candidates/xray_reference_profiles_cache.json",
  refresh_references: false,
  enrich_top: 0,
  session: "linkedin_session.json",
  output: "",
};

export interface JDSignals {
  titles: string[];
  must_have_skills: string[];
  nice_to_have_skills: string[];
  seniority: string | null;
  min_years: number | null;
  max_years: number | null;
  locations: string[];
  company_stage: string | null;
  excluded_terms: string[];
  raw_jd_text: string | null;
  extraction_source: string;
}

export interface Candidate {
  name: string;
  linkedin_url: string;
  headline: string | null;
  location: string | null;
  connection_degree: string | null;
  fit_score: number;
  fit_indicators: string[];
  search_query: string | null;
}

export interface XraySearchOutcome {
  signals: JDSignals;
  collected_count: number;
  after_score_count: number;
  after_years_count: number;
  candidates: Candidate[];
  excel_path: string;
  json_path: string;
  enriched: unknown[];
}

export type JobStatus = "pending" | "running" | "succeeded" | "failed";

export interface Job {
  id: string;
  kind: string;
  status: JobStatus;
  progress_percent: number;
  progress_message: string;
  result: XraySearchOutcome | Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export async function startXraySearch(req: XraySearchRequest): Promise<Job> {
  const { job } = await request<{ job: Job }>("/api/xray/search", {
    method: "POST",
    body: JSON.stringify(req),
  });
  return job;
}

export async function getJob(jobId: string): Promise<Job> {
  const { job } = await request<{ job: Job }>(`/api/jobs/${jobId}`);
  return job;
}

export function downloadUrl(jobId: string, kind: "excel" | "json"): string {
  return `/api/xray/download/${jobId}/${kind}`;
}

export interface SessionStatus {
  exists: boolean;
  modified_at: string | null;
}

export async function getSessionStatus(): Promise<SessionStatus> {
  return request<SessionStatus>("/api/session/status");
}

export async function startLogin(): Promise<Job> {
  const { job } = await request<{ job: Job }>("/api/session/login", { method: "POST" });
  return job;
}

export interface ChatTurnResult {
  conversation_id: string;
  text: string;
  pending_job_ids: string[];
}

export async function sendChatMessage(
  conversationId: string | null,
  text: string
): Promise<ChatTurnResult> {
  return request<ChatTurnResult>("/api/chat/message", {
    method: "POST",
    body: JSON.stringify({ conversation_id: conversationId, text }),
  });
}

export async function reportJobResult(conversationId: string, jobId: string): Promise<ChatTurnResult> {
  return request<ChatTurnResult>("/api/chat/job-result", {
    method: "POST",
    body: JSON.stringify({ conversation_id: conversationId, job_id: jobId }),
  });
}
