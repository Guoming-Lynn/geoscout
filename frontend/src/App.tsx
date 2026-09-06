import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Download, Pause, Play, Settings } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ResearchSpec, RunView } from "./api/client";
import { safeHost } from "./testable";

const emptySpec: ResearchSpec = {
  original_request: "",
  disease: [],
  tissues: [],
  organisms: [],
  assay_types: [],
  required_groups: [],
  minimum_donors_per_group: null,
  preferred_metadata: [],
  processed_matrix_requirement: "preferred",
  inclusion_criteria: [],
  unresolved_questions: [],
};

export default function App() {
  const qc = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const [request, setRequest] = useState("找人类动脉粥样硬化单细胞数据，要病变和对照，至少每组 3 位供体，最好包含年龄和性别。");
  const [manualQuery, setManualQuery] = useState('atherosclerosis AND "Homo sapiens"[ORGN] AND "gse"[ETYP]');
  const [projectId, setProjectId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [spec, setSpec] = useState<ResearchSpec>(emptySpec);
  const [tab, setTab] = useState<"recommended" | "needs_review" | "excluded">("needs_review");
  const [selected, setSelected] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [error, setError] = useState("");
  const [conn, setConn] = useState({ llm_base_url: "https://api.openai.com/v1", llm_model: "gpt-4o-mini", llm_api_key: "", ncbi_email: "", ncbi_api_key: "" });

  const runs = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => api.listRuns(projectId!),
    enabled: !!projectId,
  });
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && ["queued", "running", "pausing", "waiting_for_credentials"].includes(status) ? 1200 : false;
    },
  });
  const datasets = useQuery({
    queryKey: ["datasets", runId, tab],
    queryFn: () => api.datasets(runId!, tab),
    enabled: !!runId,
    refetchInterval: 2000,
  });
  const queries = useQuery({
    queryKey: ["queries", runId],
    queryFn: () => api.queries(runId!),
    enabled: !!runId,
  });

  useEffect(() => {
    if (runs.data && runs.data.length && !runs.data.some((r) => r.id === runId)) {
      setRunId(runs.data[0].id);
    }
  }, [runs.data, runId]);
  const detail = useQuery({
    queryKey: ["detail", runId, selected],
    queryFn: () => api.dataset(runId!, selected!),
    enabled: !!runId && !!selected,
  });

  const createProject = useMutation({
    mutationFn: () => api.createProject(request),
    onSuccess: (p) => {
      setProjectId(p.id);
      setSpec(p.spec);
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (e: Error) => setError(e.message),
  });
  const parseSpec = useMutation({
    mutationFn: () => api.parseSpec(projectId!),
    onSuccess: (r) => setSpec(r.spec),
    onError: (e: Error) => setError(e.message),
  });
  const startRun = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.createRun(projectId!, body),
    onSuccess: (r) => {
      setRunId(r.id);
      setError("");
    },
    onError: (e: Error) => setError(e.message),
  });

  const current: RunView | undefined = run.data;
  const demo = health.data?.demo;

  return (
    <div className="app">
      <aside className="sidebar">
        <h1>GEOScout</h1>
        <p className="muted">本地 GEO 发现与核验。不承诺穷尽全部 GEO。</p>
        <div className="row" style={{ margin: "12px 0" }}>
          <button className="secondary" onClick={() => setSettingsOpen((v) => !v)} aria-label="打开设置">
            <Settings size={16} /> 设置
          </button>
        </div>
        {settingsOpen && (
          <div className="card stack">
            <label>模型 Base URL
              <input value={conn.llm_base_url} onChange={(e) => setConn({ ...conn, llm_base_url: e.target.value })} />
            </label>
            <p className="muted">请求将发往：{safeHost(conn.llm_base_url)}</p>
            <label>模型名<input value={conn.llm_model} onChange={(e) => setConn({ ...conn, llm_model: e.target.value })} /></label>
            <label>模型 API Key
              <input type="password" autoComplete="off" value={conn.llm_api_key} onChange={(e) => setConn({ ...conn, llm_api_key: e.target.value })} />
            </label>
            <label>NCBI 联系邮箱<input value={conn.ncbi_email} onChange={(e) => setConn({ ...conn, ncbi_email: e.target.value })} /></label>
            <label>NCBI API Key（可选）
              <input type="password" value={conn.ncbi_api_key} onChange={(e) => setConn({ ...conn, ncbi_api_key: e.target.value })} />
            </label>
            <button
              onClick={async () => {
                try {
                  await api.saveConnections(conn);
                  const r = await api.testConnections(conn);
                  setError(r && (r as { message?: string }).message ? String((r as { message?: string }).message) : "已测试");
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              测试连接
            </button>
          </div>
        )}
        <h3>任务</h3>
        {(projects.data || []).map((p) => (
          <button key={p.id} className={`task ${p.id === projectId ? "active" : ""}`} onClick={() => { setProjectId(p.id); setSpec(p.spec); }}>
            {p.name}
          </button>
        ))}
        {(runs.data || []).map((r) => (
          <button key={r.id} className={`task ${r.id === runId ? "active" : ""}`} onClick={() => setRunId(r.id)}>
            {r.status} · {r.mode}
          </button>
        ))}
      </aside>
      <main className="main">
        {demo && <div className="banner demo">当前为显式演示模式。真实检索失败时不会改用这些数据。</div>}
        {health.data && (
          <div className="banner">
            NCBI：{health.data.ncbi_mode}　模型：{health.data.llm_mode}　本机监听 127.0.0.1
          </div>
        )}
        {error && <div className="error" role="alert">{error}</div>}
        <section className="stack">
          <h2>课题</h2>
          <textarea value={request} onChange={(e) => setRequest(e.target.value)} aria-label="课题描述" />
          <div className="row">
            <button onClick={() => createProject.mutate()}>创建课题</button>
            <button className="secondary" disabled={!projectId} onClick={() => parseSpec.mutate()}>解析条件</button>
          </div>
          <SpecEditor spec={spec} onChange={setSpec} />
          <div className="row">
            <button
              disabled={!projectId}
              onClick={() => startRun.mutate({ mode: "full", one_click: false })}
            >
              确认条件后运行
            </button>
            <button
              className="secondary"
              disabled={!projectId}
              onClick={() => startRun.mutate({ mode: "full", one_click: true, budget: { max_unique_gse: 80, max_deep_verify: 20, max_queries: 12 } })}
            >
              一键运行（默认预算）
            </button>
          </div>
          <h3>手工英文检索（无需模型 Key）</h3>
          <input value={manualQuery} onChange={(e) => setManualQuery(e.target.value)} aria-label="手工 GEO 检索式" />
          <button
            className="secondary"
            disabled={!projectId}
            onClick={() => startRun.mutate({ mode: "manual_query", manual_query: manualQuery, budget: { max_unique_gse: 40 } })}
          >
            真实/当前 NCBI 模式检索
          </button>
        </section>
        {current && (
          <section>
            <h2>运行</h2>
            <p>
              阶段 {current.stage}　状态 {statusLabel(current.status)}　查询 {current.counters.queries_done || 0}　唯一 GSE {current.counters.unique_gse || 0}
              {current.token_usage?.prompt_tokens != null && `　token ${String(current.token_usage.prompt_tokens)}`}
            </p>
            {current.stop_reason && <p className="muted">停止原因：{current.stop_reason}</p>}
            {current.status === "waiting_for_credentials" && <p><CircleAlert size={14} /> 凭据丢失，请在设置中重新填写 Key 后恢复。</p>}
            <div className="row">
              <button className="secondary" onClick={() => api.pause(current.id)}><Pause size={14} /> 暂停</button>
              <button className="secondary" onClick={() => api.resume(current.id)}><Play size={14} /> 恢复</button>
              <button className="bad" onClick={() => api.cancel(current.id)}>取消</button>
              <button
                onClick={async () => {
                  const exp = await api.exportRun(current.id);
                  window.location.href = exp.download;
                }}
              >
                <Download size={14} /> 导出 Excel
              </button>
            </div>
            <h3>查询日志</h3>
            <div className="table-wrap">
              <table>
                <thead><tr><th>轮次</th><th>检索式</th><th>命中</th><th>新增</th><th>状态</th></tr></thead>
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
                  {id === "recommended" ? "推荐" : id === "needs_review" ? "待核实" : "排除"}
                </button>
              ))}
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>GSE</th><th>标题</th><th>物种</th><th>技术</th><th>状态</th><th>理由</th>
                  </tr>
                </thead>
                <tbody>
                  {(datasets.data?.items || []).map((row) => (
                    <tr key={String(row.gse)} onClick={() => setSelected(String(row.gse))} style={{ cursor: "pointer" }}>
                      <td>{String(row.gse)}</td>
                      <td>{String(row.title || "")}</td>
                      <td>{String(row.taxon || "")}</td>
                      <td>{String(row.gdstype || "")}</td>
                      <td><span className={`pill ${String(row.category)}`}>{statusIcon(String(row.category))} {String(row.category)}</span></td>
                      <td>{String(row.reason || "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(datasets.data?.items || []).length === 0 && <p className="muted">无候选</p>}
            </div>
            {detail.data && <Detail data={detail.data} runId={current.id} onOverride={() => qc.invalidateQueries({ queryKey: ["datasets", runId] })} />}
          </section>
        )}
      </main>
    </div>
  );
}

function SpecEditor({ spec, onChange }: { spec: ResearchSpec; onChange: (s: ResearchSpec) => void }) {
  const join = (xs: string[]) => xs.join(", ");
  const split = (s: string) => s.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
  return (
    <div className="criteria">
      <label>疾病<input value={join(spec.disease)} onChange={(e) => onChange({ ...spec, disease: split(e.target.value) })} /></label>
      <label>组织<input value={join(spec.tissues)} onChange={(e) => onChange({ ...spec, tissues: split(e.target.value) })} /></label>
      <label>物种
        <select value={spec.organisms[0] || ""} onChange={(e) => onChange({ ...spec, organisms: e.target.value ? [e.target.value] : [] })}>
          <option value="">未指定</option>
          <option value="Homo sapiens">Homo sapiens</option>
          <option value="Mus musculus">Mus musculus</option>
        </select>
      </label>
      <label>技术
        <select value={spec.assay_types[0] || ""} onChange={(e) => onChange({ ...spec, assay_types: e.target.value ? [e.target.value] : [] })}>
          <option value="">未指定</option>
          <option value="scrna_seq">scRNA-seq</option>
          <option value="snrna_seq">snRNA-seq</option>
          <option value="bulk_rna_seq">bulk RNA-seq</option>
        </select>
      </label>
      <label>每组最少供体<input type="number" value={spec.minimum_donors_per_group ?? ""} onChange={(e) => onChange({ ...spec, minimum_donors_per_group: e.target.value ? Number(e.target.value) : null })} /></label>
      <label>处理后矩阵
        <select value={spec.processed_matrix_requirement} onChange={(e) => onChange({ ...spec, processed_matrix_requirement: e.target.value })}>
          <option value="none">无要求</option>
          <option value="preferred">最好有</option>
          <option value="required">必须</option>
        </select>
      </label>
      {spec.unresolved_questions.length > 0 && (
        <div className="card">未决：{spec.unresolved_questions.join("；")}</div>
      )}
    </div>
  );
}

function Detail({ data, runId, onOverride }: { data: Record<string, unknown>; runId: string; onOverride: () => void }) {
  const ds = data.dataset as Record<string, string>;
  const rd = data.run_dataset as Record<string, unknown>;
  const samples = (data.samples as Record<string, unknown>[]) || [];
  const assessments = (data.assessments as Record<string, unknown>[]) || [];
  const finals = assessments.filter((a) => a.stage === "final");
  const shown = finals.length ? finals : assessments;
  const [reason, setReason] = useState("人工核验后覆盖");
  return (
    <div className="detail">
      <h3>{String(data.gse)} 详情</h3>
      <p><a href={String(data.url)} target="_blank" rel="noreferrer">GEO 官方页面</a></p>
      <p>{ds?.title}</p>
      <p className="muted">{ds?.summary}</p>
      <p>GSM {String(rd?.gsm_count ?? "")}　独立供体 {rd?.independent_donors == null ? "未知" : String(rd.independent_donors)}</p>
      <h4>逐条件判断（最终）</h4>
      <ul>
        {shown.map((a, i) => (
          <li key={i}>
            {String(a.criterion_id)} · {String(a.stage)} · {String(a.verdict)} — {String(a.reason)}
            {Array.isArray(a.evidence_ids) && a.evidence_ids.length > 0 ? (
              <span className="muted"> 证据 {(a.evidence_ids as unknown[]).map(String).join(", ")}</span>
            ) : null}
            {a.quote ? <div className="muted">引文：{String(a.quote)}</div> : null}
          </li>
        ))}
      </ul>
      <h4>样本（{samples.length}）</h4>
      <div className="table-wrap">
        <table>
          <thead><tr><th>GSM</th><th>标题</th><th>物种</th><th>供体</th></tr></thead>
          <tbody>
            {samples.slice(0, 50).map((s) => (
              <tr key={String(s.gsm)}><td>{String(s.gsm)}</td><td>{String(s.title)}</td><td>{String(s.organism)}</td><td>{String(s.donor_key || "")}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row">
        <input value={reason} onChange={(e) => setReason(e.target.value)} aria-label="覆盖理由" />
        <button className="secondary" onClick={async () => { await api.override(runId, String(data.gse), "recommended", reason); onOverride(); }}>标为推荐</button>
        <button className="secondary" onClick={async () => { await api.override(runId, String(data.gse), "excluded", reason); onOverride(); }}>标为排除</button>
      </div>
    </div>
  );
}

function statusLabel(s: string) {
  const map: Record<string, string> = {
    queued: "排队", running: "运行中", pausing: "正在暂停", paused: "已暂停",
    waiting_for_credentials: "等待凭据", completed: "完成", partial: "部分完成", failed: "失败", cancelled: "已取消",
  };
  return map[s] || s;
}
function statusIcon(cat: string) {
  if (cat === "recommended") return "●";
  if (cat === "excluded") return "✕";
  return "?";
}
