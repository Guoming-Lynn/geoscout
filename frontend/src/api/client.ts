export type ResearchSpec = {
  original_request: string;
  disease: string[];
  tissues: string[];
  tissue_required?: boolean;
  sample_source?: string;
  organisms: string[];
  assay_types: string[];
  assay_methods?: string[];
  required_groups: string[];
  minimum_donors_per_group: number | null;
  preferred_metadata: string[];
  processed_matrix_requirement: string;
  inclusion_criteria: { criterion_id: string; field: string; description: string; user_text: string; priority: string }[];
  unresolved_questions: string[];
};

export type RunView = {
  id: string;
  project_id: string;
  mode: string;
  status: string;
  stage: string;
  stop_reason: string;
  counters: Record<string, number>;
  token_usage: Record<string, number | boolean>;
  budget: Record<string, number>;
  error_message: string;
  spec: ResearchSpec;
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  budgetPresets: () => req<Record<string, Record<string, number>>>("/api/budget-presets"),
  health: () => req<{ ok: boolean; version: string; ncbi_mode: string; llm_mode: string; demo: boolean }>("/api/health"),
  connections: () => req<Record<string, unknown>>("/api/connections"),
  saveConnections: (body: Record<string, unknown>) => req("/api/connections", { method: "PUT", body: JSON.stringify(body) }),
  testConnections: (body: Record<string, unknown>) => req("/api/connections/test", { method: "POST", body: JSON.stringify(body) }),
  listModels: (body: Record<string, unknown>) => req<{ ok?: boolean; models?: string[]; message?: string }>("/api/connections/models", { method: "POST", body: JSON.stringify(body) }),
  clearWorkspace: () => req<{ ok: boolean }>("/api/workspace/clear", { method: "POST" }),
  projects: () => req<{ id: string; name: string; original_request: string; spec: ResearchSpec; parse_token_usage?: Record<string, number | boolean> }[]>("/api/projects"),
  createProject: (original_request: string, name?: string) =>
    req<{ id: string; name: string; spec: ResearchSpec }>("/api/projects", { method: "POST", body: JSON.stringify({ original_request, name }) }),
  parseSpec: (id: string) => req<{ spec: ResearchSpec; questions: string[] }>(`/api/projects/${id}/spec/parse`, { method: "POST" }),
  saveSpec: (id: string, spec: ResearchSpec) => req(`/api/projects/${id}/spec`, { method: "PUT", body: JSON.stringify(spec) }),
  createRun: (id: string, body: Record<string, unknown>) => req<RunView>(`/api/projects/${id}/runs`, { method: "POST", body: JSON.stringify(body) }),
  listRuns: (id: string) => req<RunView[]>(`/api/projects/${id}/runs`),
  getRun: (id: string) => req<RunView>(`/api/runs/${id}`),
  pause: (id: string) => req(`/api/runs/${id}/pause`, { method: "POST" }),
  resume: (id: string) => req(`/api/runs/${id}/resume`, { method: "POST" }),
  cancel: (id: string) => req(`/api/runs/${id}/cancel`, { method: "POST" }),
  queries: (id: string) => req<{ term: string; round_no: number; hit_count: number | null; new_unique_gse: number; status: string; query_translation: string }[]>(`/api/runs/${id}/queries`),
  datasets: (id: string, category?: string) =>
    req<{ total: number; items: Record<string, unknown>[] }>(`/api/runs/${id}/datasets${category ? `?category=${category}` : ""}`),
  dataset: (id: string, gse: string) => req<Record<string, unknown>>(`/api/runs/${id}/datasets/${gse}`),
  override: (id: string, gse: string, category: string, reason: string) =>
    req(`/api/runs/${id}/datasets/${gse}/override`, { method: "POST", body: JSON.stringify({ category, reason }) }),
  exportRun: (id: string) => req<{ id: string; filename: string; download: string; complete: boolean; status: string }>(`/api/runs/${id}/exports`, { method: "POST", body: JSON.stringify({ include_json: true }) }),
};
