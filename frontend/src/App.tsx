import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Download, Loader2, Pause, Play, Settings, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ResearchSpec, RunView } from "./api/client";
import {
  AuthorCredit,
  ConnectGate,
  ConnectionFields,
  connectionPayload,
  defaultConn,
  forgetWorkbench,
  hadWorkbench,
  type Conn,
} from "./Connect";
import { LanguageSelect, useI18n, type MsgKey } from "./i18n";
import { nextRunId, runOwnedByProject, totalTokens } from "./testable";

const LIVE_STATUSES = ["queued", "running", "pausing", "waiting_for_credentials"] as const;

function isLive(status?: string) {
  return !!status && LIVE_STATUSES.includes(status as (typeof LIVE_STATUSES)[number]);
}

function assayLabels(t: (key: MsgKey) => string, kinds: unknown, fallback?: unknown): string {
  const list = Array.isArray(kinds) && kinds.length ? kinds.map(String) : [String(fallback || "unknown")];
  return list.map((kind) => t(`kind_${kind}` as MsgKey)).join(" · ");
}

const emptySpec: ResearchSpec = {
  original_request: "",
  disease: [],
  tissues: [],
  organisms: [],
  assay_types: [],
  assay_methods: [],
  required_groups: [],
  minimum_donors_per_group: null,
  preferred_metadata: [],
  processed_matrix_requirement: "preferred",
  inclusion_criteria: [],
  unresolved_questions: [],
};

export default function App() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [tier, setTier] = useState<"low" | "medium" | "high" | "ultra">("medium");
  const [deepLimit, setDeepLimit] = useState("");
  const presets = useQuery({ queryKey: ["budget-presets"], queryFn: api.budgetPresets });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const [request, setRequest] = useState("");
  const [manualQuery, setManualQuery] = useState("");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [spec, setSpec] = useState<ResearchSpec>(emptySpec);
  const [tab, setTab] = useState<"recommended" | "needs_review" | "excluded">("needs_review");
  const [selected, setSelected] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [error, setError] = useState("");
  const [conn, setConn] = useState<Conn>(defaultConn);
  const [entered, setEntered] = useState(() => hadWorkbench());
  const session = useQuery({ queryKey: ["connections"], queryFn: api.connections });
  const keyPresent = Boolean(session.data?.llm_key_present);
  const ready = entered || keyPresent;

  useEffect(() => {
    const d = session.data;
    if (!d?.llm_key_present) return;
    setConn((c) => ({
      ...c,
      llm_base_url: String(d.llm_base_url || c.llm_base_url),
      llm_model: String(d.llm_model || c.llm_model),
      ncbi_email: String(d.ncbi_email || c.ncbi_email),
    }));
  }, [session.data]);

  const runs = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => api.listRuns(projectId!),
    enabled: !!projectId,
    refetchInterval: (q) => (q.state.data?.some((r) => isLive(r.status)) ? 1200 : false),
  });
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
    refetchInterval: (q) => (isLive(q.state.data?.status) ? 1200 : false),
  });
  const liveRun = isLive(run.data?.status);
  const datasets = useQuery({
    queryKey: ["datasets", runId, tab],
    queryFn: () => api.datasets(runId!, tab),
    enabled: !!runId,
    refetchInterval: liveRun ? 2000 : false,
  });
  const queries = useQuery({
    queryKey: ["queries", runId],
    queryFn: () => api.queries(runId!),
    enabled: !!runId,
    refetchInterval: liveRun ? 1200 : false,
  });

  useEffect(() => {
    if (!projectId) {
      if (runId) {
        setRunId(null);
        setSelected(null);
      }
      return;
    }
    if (runs.isFetching && !runs.data) return;
    const next = nextRunId(runs.data, runId);
    if (next !== runId) {
      setRunId(next);
      setSelected(null);
    }
  }, [projectId, runs.data, runs.isFetching, runId]);
  const detail = useQuery({
    queryKey: ["detail", runId, selected],
    queryFn: () => api.dataset(runId!, selected!),
    enabled: !!runId && !!selected,
  });

  useEffect(() => {
    if (runId && run.data?.status && !isLive(run.data.status)) {
      qc.invalidateQueries({ queryKey: ["datasets", runId] });
      qc.invalidateQueries({ queryKey: ["queries", runId] });
      qc.invalidateQueries({ queryKey: ["detail", runId] });
    }
  }, [runId, run.data?.status, qc]);

  const createProject = useMutation({
    mutationFn: () => api.createProject(request),
    onSuccess: (p) => {
      setProjectId(p.id);
      setSpec(p.spec);
      setRunId(null);
      setSelected(null);
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (e: Error) => setError(e.message),
  });
  const parseSpec = useMutation({
    mutationFn: () => api.parseSpec(projectId!),
    onSuccess: (r) => { setSpec(r.spec); qc.invalidateQueries({ queryKey: ["projects"] }); },
    onError: (e: Error) => setError(e.message),
  });
  const startRun = useMutation({
    mutationFn: async (body: Record<string, unknown>) => {
      await api.saveSpec(projectId!, spec);
      return api.createRun(projectId!, body);
    },
    onSuccess: (r) => {
      setRunId(r.id);
      qc.setQueryData(["run", r.id], r);
      setError("");
      qc.invalidateQueries({ queryKey: ["runs", projectId] });
      qc.invalidateQueries({ queryKey: ["queries"] });
      qc.invalidateQueries({ queryKey: ["datasets"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const current: RunView | undefined = run.data && runOwnedByProject(run.data, projectId) ? run.data : undefined;
  const parseUsage = projects.data?.find(p => p.id === projectId)?.parse_token_usage;
  const starting = startRun.isPending;
  const active = starting || isLive(current?.status);
  const demo = health.data?.demo;

  if (session.isPending && !entered) {
    return (
      <div className="gate">
        <div className="gate-card">
          <h1>GEOScout</h1>
          <p className="muted">{t("checking")}</p>
          <AuthorCredit />
        </div>
      </div>
    );
  }

  if (!ready) {
    return (
      <ConnectGate
        conn={conn}
        onChange={setConn}
        version={health.data?.version || "0.1.1"}
        onReady={() => {
          setEntered(true);
          qc.invalidateQueries({ queryKey: ["connections"] });
        }}
      />
    );
  }

  return (
    <div className={`app ${sidebarOpen ? "sidebar-open" : "sidebar-collapsed"}`}>
      <button className="sidebar-toggle" aria-label={t("toggleSidebar")} onClick={() => setSidebarOpen((v) => !v)}>☰</button>
      <aside className="sidebar">
        <h1>GEOScout</h1>
        <p className="muted">
          {t("workbenchTagline")} v{health.data?.version || "0.1.1"}
        </p>
        <AuthorCredit />
        <div className="row" style={{ margin: "12px 0" }}>
          <button className="secondary" onClick={() => setSettingsOpen((v) => !v)} aria-label={t("settings")}>
            <Settings size={16} /> {t("settingsBtn")}
          </button>
          <LanguageSelect />
        </div>
        {settingsOpen && (
          <div className="settings-overlay" role="dialog" aria-modal="true" aria-label={t("settings")} onClick={() => setSettingsOpen(false)}>
          <div className="card stack settings-panel" onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ justifyContent: "space-between" }}><h3>{t("settingsBtn")}</h3><button className="secondary" onClick={() => setSettingsOpen(false)}>×</button></div>
            <ConnectionFields conn={conn} onChange={setConn} />
            <button
              onClick={async () => {
                try {
                  const body = connectionPayload(conn);
                  await api.saveConnections(body);
                  const r = await api.testConnections(body);
                  setConn({ ...conn, llm_api_key: "", ncbi_api_key: "" });
                  setError(r && (r as { message?: string }).message ? String((r as { message?: string }).message) : t("testConn"));
                  qc.invalidateQueries({ queryKey: ["connections"] });
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              {t("testConn")}
            </button>
          </div>
          </div>
        )}
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3>{t("tasks")}</h3>
          <button
            className="secondary"
            disabled={!projects.data?.length}
            onClick={async () => {
              if (!window.confirm(t("clearConfirm"))) return;
              try {
                await api.clearWorkspace();
                setProjectId(null);
                setRunId(null);
                setSelected(null);
                setSpec(emptySpec);
                setRequest("");
                setError(t("cleared"));
                qc.invalidateQueries({ queryKey: ["projects"] });
                qc.invalidateQueries({ queryKey: ["runs"] });
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            <Trash2 size={14} /> {t("clearTasks")}
          </button>
        </div>
        <h4 className="sidebar-section-title">{t("topics")}</h4>
        {(projects.data || []).map((p) => (
          <button key={p.id} className={`task ${p.id === projectId ? "active" : ""}`} onClick={() => { setProjectId(p.id); setSpec(p.spec); setRequest(p.original_request || ""); setRunId(null); setSelected(null); }}>
            {p.name}
          </button>
        ))}
        {!!projectId && <h4 className="sidebar-section-title">{t("runs")}</h4>}
        {(runs.data || []).map((r) => (
          <button
            key={r.id}
            className={`task ${r.id === runId ? "active" : ""} ${isLive(r.status) ? "live" : ""}`}
            onClick={() => setRunId(r.id)}
          >
            {statusLabel(r.status, t)} · {r.mode}
          </button>
        ))}
      </aside>
      <main className="main">
        {demo && <div className="banner demo">{t("demoBanner")}</div>}
        {health.data && (
          <div className="banner">
            {t("banner", { ncbi: health.data.ncbi_mode, llm: health.data.llm_mode })}
          </div>
        )}
        {error && <div className="error" role="alert">{error}</div>}
        {(starting || current) && (
          <div
            className={`banner run-status ${active ? "live" : ""}`}
            role="status"
            aria-live="polite"
            aria-busy={active}
          >
            {active && <span className="dot" aria-hidden="true" />}
            <span>
              {starting ? t("starting") : statusLabel(current!.status, t)}
              {!starting && current ? ` · ${t("stage")} ${current.stage}` : ""}
            </span>
            {current && !starting && (
              <span className="muted" style={{ fontWeight: 500 }}>
                {t("queries")} {current.counters.queries_done || 0}
                {" · "}
                {t("uniqueGse")} {current.counters.unique_gse || 0}
              </span>
            )}
          </div>
        )}
        <section className="stack">
          <h2>{t("topic")}</h2>
          <textarea
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            aria-label={t("topic")}
            placeholder={t("topicPh")}
          />
          <div className="row">
            <button disabled={!request.trim()} onClick={() => createProject.mutate()}>{t("createTopic")}</button>
            <button className="secondary" disabled={!projectId || parseSpec.isPending} onClick={() => parseSpec.mutate()}>{t("parseSpec")}</button>
          </div>
          {!!totalTokens(parseUsage) && <p className="muted">{t("parseUsage")} {totalTokens(parseUsage)}{parseUsage?.estimated && ` (${t("estimatedUsage")})`}</p>}
          <SpecEditor spec={spec} onChange={setSpec} />
          <div className="row">
            <button
              disabled={!projectId || active || (deepLimit !== "" && (!Number.isInteger(Number(deepLimit)) || Number(deepLimit) < 0 || Number(deepLimit) > (presets.data?.[tier]?.max_unique_gse ?? 0)))}
              onClick={() => startRun.mutate({ mode: "full", tier, ...(deepLimit !== "" ? { deep_limit: Number(deepLimit) } : {}) })}
            >
              {active ? <Loader2 className="spin" size={14} /> : <Play size={14} />}
              {starting ? t("starting") : isLive(current?.status) ? statusLabel(current!.status, t) : t("startRun")}
            </button>
            <label>{t("intensity")}
              <select value={tier} onChange={(e) => { setTier(e.target.value as typeof tier); setDeepLimit(""); }}>
                {(["low", "medium", "high", "ultra"] as const).map((value) => <option key={value} value={value}>{t(value)}</option>)}
              </select>
            </label>
          </div>
          {presets.data?.[tier] && <p className="muted">
            GSE ≤ {presets.data[tier].max_unique_gse} · SOFT ≤ {presets.data[tier].max_deep_verify}
            {` · ${t("tokenBudget")} `}{presets.data[tier].max_tokens} · {presets.data[tier].max_runtime_s / 60} min
          </p>}
          <label>{t("deepLimit")}<input type="number" min="0" max={presets.data?.[tier]?.max_unique_gse} step="1" value={deepLimit} placeholder={`${t("tierDefault")} (${presets.data?.[tier]?.max_deep_verify ?? ""})`} onChange={(e) => setDeepLimit(e.target.value)} /></label>
          {deepLimit !== "" && Number(deepLimit) > (presets.data?.[tier]?.max_deep_verify ?? 0) && <p className="muted">{t("deepLimitHint")}</p>}
          <h3>{t("manualSearch")}</h3>
          <input
            value={manualQuery}
            onChange={(e) => setManualQuery(e.target.value)}
            aria-label={t("manualSearch")}
            placeholder="GSE1000[Accession]"
          />
          <button
            className="secondary"
            disabled={!projectId || !manualQuery.trim() || active}
            onClick={() => startRun.mutate({ mode: "manual_query", manual_query: manualQuery, budget: { max_unique_gse: 40 } })}
          >
            {starting ? <Loader2 className="spin" size={14} /> : null}
            {starting ? t("starting") : t("ncbiSearch")}
          </button>
        </section>
        {current && (
          <section>
            <h2>{t("run")}</h2>
            <p>
              {t("stage")} {current.stage}　{t("status")} {statusLabel(current.status, t)}　{t("queries")} {current.counters.queries_done || 0}　{t("uniqueGse")} {current.counters.unique_gse || 0}
              {current.token_usage?.prompt_tokens != null && `　token ${totalTokens(current.token_usage)}${current.token_usage.estimated ? ` (${t("estimatedUsage")})` : ""}`}
            </p>
            {current.stop_reason && <p className="muted">{t("stopReason")}{current.stop_reason}</p>}
            {current.budget && (
              <p className="muted">
                GSE ≤ {current.budget.max_unique_gse ?? "?"}
                {" · SOFT ≤ "}
                {current.budget.max_deep_verify ?? "?"}
                {` · ${t("tokenBudget")} `}
                {current.budget.max_tokens ?? "?"}
              </p>
            )}
            {current.status === "waiting_for_credentials" && (
              <p>
                <CircleAlert size={14} /> {t("credsLost")}
                <button
                  className="secondary"
                  style={{ marginLeft: 8 }}
                  onClick={() => {
                    forgetWorkbench();
                    setEntered(false);
                    setSettingsOpen(true);
                  }}
                >
                  {t("reenterKey")}
                </button>
              </p>
            )}
            <div className="row">
              <button className="secondary" disabled={current.status !== "running"} onClick={() => api.pause(current.id)}><Pause size={14} /> {t("pause")}</button>
              <button className="secondary" disabled={current.status !== "paused"} onClick={() => api.resume(current.id)}><Play size={14} /> {t("resume")}</button>
              <button className="bad" disabled={!isLive(current.status)} onClick={async () => {
                setError("");
                try {
                  await api.cancel(current.id);
                  await qc.invalidateQueries({ queryKey: ["run", current.id] });
                } catch (e) {
                  setError(e instanceof Error ? e.message : String(e));
                }
              }}>{t("cancel")}</button>
              <button
                onClick={async () => {
                  const exp = await api.exportRun(current.id);
                  window.location.href = exp.download;
                }}
              >
                <Download size={14} /> {t("exportExcel")}
              </button>
            </div>
            <h3>{t("queryLog")}</h3>
            <div className="table-wrap">
              <table>
                <thead><tr><th>{t("round")}</th><th>{t("term")}</th><th>{t("hits")}</th><th>{t("added")}</th><th>{t("status")}</th></tr></thead>
                <tbody>
                  {(queries.data || []).map((q, i) => (
                    <tr key={i}><td>{q.round_no}</td><td>{q.term}</td><td>{q.hit_count ?? ""}</td><td>{q.new_unique_gse}</td><td>{q.status}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="tabs" role="tablist">
              {(["recommended", "needs_review", "excluded"] as const).map((id) => (
                <button key={id} role="tab" aria-selected={tab === id} className="secondary" onClick={() => setTab(id)}>
                  {id === "recommended" ? t("recommended") : id === "needs_review" ? t("needsReview") : t("excluded")} {id === tab ? `(${datasets.data?.total || 0})` : ""}
                </button>
              ))}
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>GSE</th><th>{t("title")}</th><th>{t("taxon")}</th><th>{t("tech")}</th><th>{t("status")}</th><th>{t("reason")}</th>
                  </tr>
                </thead>
                <tbody>
                  {(datasets.data?.items || []).map((row) => (
                    <tr key={String(row.gse)} className={String(row.gse) === selected ? "selected-row" : ""} onClick={() => setSelected(String(row.gse))} style={{ cursor: "pointer" }}>
                      <td>{String(row.gse)}</td>
                      <td>{String(row.title || "")}</td>
                      <td>{String(row.taxon || "")}</td>
                      <td>
                        {assayLabels(t, row.assay_kinds, row.assay_kind)}
                        {row.gdstype ? <div className="muted">{String(row.gdstype)}</div> : null}
                      </td>
                      <td><span className={`pill ${String(row.category)}`}>{statusIcon(String(row.category))} {String(row.category) === "recommended" ? t("recommended") : String(row.category) === "needs_review" ? t("needsReview") : t("excluded")}</span></td>
                      <td>{String(row.reason || "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(datasets.data?.items || []).length === 0 && <p className="muted">{t("noCandidates")}</p>}
            </div>
            {detail.data && <Detail data={detail.data} runId={current.id} onOverride={() => qc.invalidateQueries({ queryKey: ["datasets", runId] })} />}
          </section>
        )}
      </main>
    </div>
  );
}

function SpecEditor({ spec, onChange }: { spec: ResearchSpec; onChange: (s: ResearchSpec) => void }) {
  const { t } = useI18n();
  const join = (xs: string[]) => xs.join(", ");
  const split = (s: string) => s.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
  return (
    <div className="criteria">
      <label>{t("disease")}<input value={join(spec.disease)} onChange={(e) => onChange({ ...spec, disease: split(e.target.value) })} /></label>
      <label>{t("tissue")}<input value={join(spec.tissues)} onChange={(e) => onChange({ ...spec, tissues: split(e.target.value) })} /></label>
      <label><input type="checkbox" checked={!!spec.tissue_required} onChange={(e) => onChange({ ...spec, tissue_required: e.target.checked })} />{t("tissueRequired")}</label>
      <label>{t("sampleSource")}<select value={spec.sample_source ?? "any"} onChange={(e) => onChange({ ...spec, sample_source: e.target.value })}>
        <option value="any">{t("unspecified")}</option><option value="primary">{t("sourcePrimary")}</option><option value="cell_line">{t("sourceCell")}</option><option value="organoid">{t("sourceOrganoid")}</option><option value="xenograft">{t("sourceXeno")}</option>
      </select></label>
      <label>{t("organism")}
        <select value={spec.organisms[0] || ""} onChange={(e) => onChange({ ...spec, organisms: e.target.value ? [e.target.value] : [] })}>
          <option value="">{t("unspecified")}</option>
          <option value="Homo sapiens">Homo sapiens</option>
          <option value="Mus musculus">Mus musculus</option>
        </select>
      </label>
      <label>{t("assay")}
        <select value={spec.assay_types[0] || ""} onChange={(e) => onChange({ ...spec, assay_types: e.target.value ? [e.target.value] : [] })}>
          <option value="">{t("unspecified")}</option>
          <option value="scrna_seq">{t("kind_scrna_seq")}</option>
          <option value="snrna_seq">{t("kind_snrna_seq")}</option>
          <option value="bulk_rna_seq">{t("kind_bulk_rna_seq")}</option>
          <option value="rna_seq_generic">{t("kind_rna_seq_generic")}</option>
          <option value="spatial_transcriptomics">{t("kind_spatial_transcriptomics")}</option>
          <option value="proteomics">{t("kind_proteomics")}</option>
          <option value="epigenomics">{t("kind_epigenomics")}</option>
          <option value="microbiome">{t("kind_microbiome")}</option>
        </select>
      </label>
      <label>{t("assayMethods")}<input value={join(spec.assay_methods || [])} onChange={(e) => onChange({ ...spec, assay_methods: split(e.target.value) })} /></label>
      <label>{t("minDonors")}<input type="number" value={spec.minimum_donors_per_group ?? ""} onChange={(e) => onChange({ ...spec, minimum_donors_per_group: e.target.value ? Number(e.target.value) : null })} /></label>
      <label>{t("matrix")}
        <select value={spec.processed_matrix_requirement} onChange={(e) => onChange({ ...spec, processed_matrix_requirement: e.target.value })}>
          <option value="none">{t("matrixNone")}</option>
          <option value="preferred">{t("matrixPref")}</option>
          <option value="required">{t("matrixReq")}</option>
        </select>
      </label>
      {spec.unresolved_questions.length > 0 && (
        <div className="card">{t("unresolved")}{spec.unresolved_questions.join("；")}</div>
      )}
    </div>
  );
}

function Detail({ data, runId, onOverride }: { data: Record<string, unknown>; runId: string; onOverride: () => void }) {
  const { t } = useI18n();
  const ds = (data.dataset ?? {}) as Record<string, unknown>;
  const rd = data.run_dataset as Record<string, unknown>;
  const selection = (rd?.selection ?? {}) as { selected?: boolean; rank?: number; reasons?: string[] };
  const samples = (data.samples as Record<string, unknown>[]) || [];
  const assessments = (data.assessments as Record<string, unknown>[]) || [];
  const finals = assessments.filter((a) => a.stage === "final");
  const shown = finals.length ? finals : assessments;
  const [reason, setReason] = useState(() => t("defaultOverride"));
  return (
    <div className="detail">
      <h3>{String(data.gse)} {t("detail")}</h3>
      <p><a href={String(data.url)} target="_blank" rel="noreferrer">{t("geoPage")}</a></p>
      <p>{String(ds.title ?? "")}</p>
      <p>{assayLabels(t, ds.assay_kinds, ds.assay_kind)}{ds.gdstype ? ` · ${String(ds.gdstype)}` : ""}</p>
      {selection.selected !== undefined && <p>{selection.selected ? `${t("selectionRank")}: ${selection.rank}` : t("notSelected")}</p>}
      {!!selection.reasons?.length && <p>{t("selectionReason")}: {selection.reasons.map((reason) => t(reason as MsgKey)).join(", ")}</p>}
      <p className="muted">{String(ds.summary ?? "")}</p>
      <p>{t("gsmCount")} {String(rd?.gsm_count ?? "")}　{t("independentDonors")} {rd?.independent_donors == null ? t("unknown") : String(rd.independent_donors)}</p>
      <h4>{t("judgements")}</h4>
      <ul>
        {shown.map((a, i) => (
          <li key={i}>
            {String(a.criterion_id)} · {String(a.stage)} · {String(a.verdict)} — {String(a.reason)}
            {Array.isArray(a.evidence_ids) && a.evidence_ids.length > 0 ? (
              <span className="muted"> {t("evidence")} {(a.evidence_ids as unknown[]).map(String).join(", ")}</span>
            ) : null}
            {a.quote ? <div className="muted">{t("quote")}{String(a.quote)}</div> : null}
          </li>
        ))}
      </ul>
      <h4>{t("samples")}（{samples.length}）</h4>
      <div className="table-wrap">
        <table>
          <thead><tr><th>GSM</th><th>{t("title")}</th><th>{t("organism")}</th><th>{t("donor")}</th></tr></thead>
          <tbody>
            {samples.slice(0, 50).map((s) => (
              <tr key={String(s.gsm)}><td>{String(s.gsm)}</td><td>{String(s.title)}</td><td>{String(s.organism)}</td><td>{String(s.donor_key || "")}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row">
        <input value={reason} onChange={(e) => setReason(e.target.value)} aria-label={t("overrideReason")} />
        <button className="secondary" onClick={async () => { await api.override(runId, String(data.gse), "recommended", reason); onOverride(); }}>{t("markRecommended")}</button>
        <button className="secondary" onClick={async () => { await api.override(runId, String(data.gse), "excluded", reason); onOverride(); }}>{t("markExcluded")}</button>
      </div>
    </div>
  );
}

function statusLabel(s: string, t: (key: MsgKey) => string) {
  const known: MsgKey[] = ["starting", "queued", "running", "pausing", "paused", "waiting_for_credentials", "completed", "partial", "failed", "cancelled"];
  if (known.includes(s as MsgKey)) return t(s as MsgKey);
  return s;
}
function statusIcon(cat: string) {
  if (cat === "recommended") return "●";
  if (cat === "excluded") return "✕";
  return "?";
}
