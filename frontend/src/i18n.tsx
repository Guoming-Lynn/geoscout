import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

export type Lang = "zh-CN" | "en" | "de";

const STORAGE = "geoscout.lang";

const messages = {
  "zh-CN": {
    sampleSource: "样本来源", sourcePrimary: "直接采集的原代样本", sourceCell: "细胞系 / iPSC", sourceOrganoid: "类器官", sourceXeno: "异种移植", tissueRequired: "组织必须匹配", deepLimit: "深核数量上限", deepLimitHint: "增加深核数量不会提高 token 上限，可能只完成部分核验。", tierDefault: "使用档位默认值", selectionReason: "深核入选依据", selectionRank: "深核次序", notSelected: "未入选深核", disease_in_title: "标题包含目标疾病", disease_in_summary: "摘要包含目标疾病", no_direct_disease_term: "未找到直接疾病词", target_tissue: "包含目标组织", target_tissue_sample_evidence: "标题提示目标组织样本材料", target_tissue_in_title: "标题包含目标组织", target_tissue_in_summary: "摘要背景提及目标组织", conflicting_tissue_in_title: "标题组织与要求冲突", patient_or_donor_context: "患者或供体语境", control_context: "对照语境", patient_or_donor_in_title: "标题包含患者或供体", control_in_title: "标题包含对照", model_or_intervention_context: "模型或干预语境", source_mismatch_model: "标题提示模型来源与原代要求冲突", primary_source_in_title: "标题提示原代采集", requested_model_source: "标题匹配所要求的模型来源", hard_supported: "硬条件有摘要支持", hard_material_supported: "组织或来源硬条件有支持", hard_tissue_fail: "组织硬条件失败", off_assay_microbiome: "非宿主微生物组技术", off_assay_proteomics: "蛋白组技术", off_assay_spatial: "空间组学技术", off_assay_epigenomics: "表观组技术", off_assay_other: "非 RNA 测序技术", off_assay_method: "具体实验方法不匹配", gdstype_other: "GEO 技术类型为 Other", third_party_reanalysis: "第三方再分析", kind_unknown: "未分类", kind_scrna_seq: "scRNA-seq", kind_snrna_seq: "snRNA-seq", kind_bulk_rna_seq: "bulk RNA-seq", kind_rna_seq_generic: "RNA-seq", kind_spatial_transcriptomics: "空间转录组", kind_proteomics: "蛋白组", kind_epigenomics: "表观组", kind_microbiome: "微生物组", kind_other: "其他技术",
    parseUsage: "条件解析累计 token：", estimatedUsage: "含估算", tokenBudget: "token 预算",
    intensity: "核验强度", low: "低", medium: "中等", high: "高", ultra: "极高", startRun: "开始核验", starting: "正在启动…",
    checking: "正在检查本机连接…",
    tagline: "本机 GEO 发现与核验。Key 只保存在这次进程内存里，不会写入数据库、日志或 Excel。",
    workbenchTagline: "本地 GEO 发现与核验。不承诺穷尽全部 GEO。",
    baseUrl: "模型 Base URL",
    requestHost: "请求将发往：",
    modelName: "模型名",
    apiKey: "模型 API Key",
    ncbiEmail: "NCBI 联系邮箱",
    ncbiKey: "NCBI API Key（可选）",
    testStart: "测试连接并开始",
    testing: "正在测试…",
    ncbiOnly: "仅 NCBI 检索进入",
    settings: "打开设置",
    settingsBtn: "设置",
    testConn: "测试连接",
    tasks: "任务",
    clearTasks: "清除任务",
    clearConfirm: "清除本机全部课题和运行记录？GEO 摘要缓存会保留。此操作不能撤销。",
    cleared: "已清除课题和运行记录。",
    help: "连接说明",
    helpBody:
      "GEOScout 使用任意 OpenAI 兼容接口：填服务商给的 Base URL 和 API Key，再填或拉取模型名。常见例子：OpenAI 用 https://api.openai.com/v1 ；DeepSeek 官方用 https://api.deepseek.com（不要加 /v1）；其它兼容网关按其文档填写。Key 只留在这次 API 进程内存里。NCBI 邮箱是 NCBI 要求的联系方式。没有模型也可以只用手工 GEO 检索。",
    fetchModels: "拉取模型",
    fetchingModels: "正在拉取…",
    pickModel: "从列表选择模型",
    language: "语言",
    provider: "服务商",
    chooseProvider: "选择服务商",
    customUrl: "自定义",
    topic: "课题",
    topicPh: "用自己的话写课题",
    createTopic: "创建课题",
    parseSpec: "解析条件",
    manualSearch: "手工英文检索（无需模型 Key）",
    ncbiSearch: "真实/当前 NCBI 模式检索",
    disease: "疾病",
    tissue: "组织",
    organism: "物种",
    assay: "技术",
    assayMethods: "具体方法",
    unspecified: "未指定",
    minDonors: "每组最少供体",
    matrix: "处理后矩阵",
    matrixNone: "无要求",
    matrixPref: "最好有",
    matrixReq: "必须",
    unresolved: "未决：",
    run: "运行",
    stage: "阶段",
    status: "状态",
    queries: "查询",
    uniqueGse: "唯一 GSE",
    stopReason: "停止原因：",
    credsLost: "凭据丢失。",
    reenterKey: "重新填写 Key",
    pause: "暂停",
    resume: "恢复",
    cancel: "取消",
    exportExcel: "导出 Excel",
    queryLog: "查询日志",
    round: "轮次",
    term: "检索式",
    hits: "命中",
    added: "新增",
    recommended: "推荐",
    needsReview: "待核实",
    excluded: "排除",
    title: "标题",
    taxon: "物种",
    tech: "技术",
    reason: "理由",
    noCandidates: "无候选",
    detail: "详情",
    geoPage: "GEO 官方页面",
    unknown: "未知",
    judgements: "逐条件判断（最终）",
    evidence: "证据",
    quote: "引文：",
    samples: "样本",
    donor: "供体",
    overrideReason: "覆盖理由",
    markRecommended: "标为推荐",
    markExcluded: "标为排除",
    demoBanner: "当前为显式演示模式。真实检索失败时不会改用这些数据。",
    banner: "NCBI：{ncbi}　模型：{llm}　本机监听 127.0.0.1",
    queued: "排队",
    running: "运行中",
    pausing: "正在暂停",
    paused: "已暂停",
    waiting_for_credentials: "等待凭据",
    completed: "完成",
    partial: "部分完成",
    failed: "失败",
    cancelled: "已取消",
    defaultOverride: "人工核验后覆盖",
    gsmCount: "GSM",
    independentDonors: "独立供体",
  },
  en: {
    sampleSource: "Sample source", sourcePrimary: "Direct primary samples", sourceCell: "Cell line / iPSC", sourceOrganoid: "Organoid", sourceXeno: "Xenograft", tissueRequired: "Require tissue match", deepLimit: "Deep review limit", deepLimitHint: "Increasing this does not raise the token cap; some reviews may remain unfinished.", tierDefault: "Tier default", selectionReason: "Deep selection factors", selectionRank: "Deep review order", notSelected: "Not selected for deep review", disease_in_title: "Disease in title", disease_in_summary: "Disease in summary", no_direct_disease_term: "No direct disease term", target_tissue: "Target tissue", target_tissue_sample_evidence: "Title suggests target tissue samples", target_tissue_in_title: "Target tissue in title", target_tissue_in_summary: "Target tissue mentioned in summary only", conflicting_tissue_in_title: "Title tissue conflicts with the requirement", patient_or_donor_context: "Patient or donor context", control_context: "Control context", patient_or_donor_in_title: "Patient or donor in title", control_in_title: "Control in title", model_or_intervention_context: "Model or intervention context", source_mismatch_model: "Title suggests a model source against a primary request", primary_source_in_title: "Title suggests primary collection", requested_model_source: "Title matches the requested model source", hard_supported: "Hard criterion supported in summary", hard_material_supported: "Hard tissue or source supported", hard_tissue_fail: "Hard tissue criterion failed", off_assay_microbiome: "Off-target microbiome assay", off_assay_proteomics: "Proteomics assay", off_assay_spatial: "Spatial omics assay", off_assay_epigenomics: "Epigenomics assay", off_assay_other: "Non-RNA sequencing assay", off_assay_method: "Specific assay method mismatch", gdstype_other: "GEO assay type is Other", third_party_reanalysis: "Third-party reanalysis", kind_unknown: "Unclassified", kind_scrna_seq: "scRNA-seq", kind_snrna_seq: "snRNA-seq", kind_bulk_rna_seq: "bulk RNA-seq", kind_rna_seq_generic: "RNA-seq", kind_spatial_transcriptomics: "Spatial transcriptomics", kind_proteomics: "Proteomics", kind_epigenomics: "Epigenomics", kind_microbiome: "Microbiome", kind_other: "Other assay",
    parseUsage: "Criteria parsing tokens:", estimatedUsage: "includes estimates", tokenBudget: "token budget",
    intensity: "Review intensity", low: "Low", medium: "Medium", high: "High", ultra: "Ultra", startRun: "Start review", starting: "Starting…",
    checking: "Checking local connection…",
    tagline: "Local GEO discovery and checks. Keys stay in this process memory only — not the database, logs, or Excel.",
    workbenchTagline: "Local GEO discovery and checks. Completeness of GEO is not promised.",
    baseUrl: "Model base URL",
    requestHost: "Requests go to: ",
    modelName: "Model name",
    apiKey: "Model API key",
    ncbiEmail: "NCBI contact email",
    ncbiKey: "NCBI API key (optional)",
    testStart: "Test connection and start",
    testing: "Testing…",
    ncbiOnly: "Enter with NCBI search only",
    settings: "Open settings",
    settingsBtn: "Settings",
    testConn: "Test connection",
    tasks: "Tasks",
    clearTasks: "Clear tasks",
    clearConfirm: "Clear all local topics and run records? GEO summary cache is kept. This cannot be undone.",
    cleared: "Topics and run records cleared.",
    help: "Connection help",
    helpBody:
      "GEOScout talks to any OpenAI-compatible API: paste the vendor base URL and API key, then type or fetch a model name. Examples: OpenAI uses https://api.openai.com/v1 ; official DeepSeek uses https://api.deepseek.com (do not add /v1); other gateways follow their docs. Keys stay in this API process only. NCBI email is the contact NCBI requires. You can skip the model and use a manual GEO query.",
    fetchModels: "Fetch models",
    fetchingModels: "Fetching…",
    pickModel: "Choose a model",
    language: "Language",
    provider: "Provider",
    chooseProvider: "Choose a provider",
    customUrl: "Custom",
    topic: "Topic",
    topicPh: "Describe your topic in your own words",
    createTopic: "Create topic",
    parseSpec: "Parse criteria",
    manualSearch: "Manual English search (no model key)",
    ncbiSearch: "Search in current NCBI mode",
    disease: "Disease",
    tissue: "Tissue",
    organism: "Organism",
    assay: "Assay",
    assayMethods: "Specific method",
    unspecified: "Unspecified",
    minDonors: "Min. donors per group",
    matrix: "Processed matrix",
    matrixNone: "Not required",
    matrixPref: "Preferred",
    matrixReq: "Required",
    unresolved: "Unresolved: ",
    run: "Run",
    stage: "Stage",
    status: "Status",
    queries: "Queries",
    uniqueGse: "Unique GSE",
    stopReason: "Stop reason: ",
    credsLost: "Credentials missing.",
    reenterKey: "Re-enter key",
    pause: "Pause",
    resume: "Resume",
    cancel: "Cancel",
    exportExcel: "Export Excel",
    queryLog: "Query log",
    round: "Round",
    term: "Term",
    hits: "Hits",
    added: "New",
    recommended: "Recommended",
    needsReview: "Needs review",
    excluded: "Excluded",
    title: "Title",
    taxon: "Taxon",
    tech: "Assay",
    reason: "Reason",
    noCandidates: "No candidates",
    detail: "Details",
    geoPage: "GEO record",
    unknown: "Unknown",
    judgements: "Per-criterion judgements (final)",
    evidence: "Evidence",
    quote: "Quote: ",
    samples: "Samples",
    donor: "Donor",
    overrideReason: "Override reason",
    markRecommended: "Mark recommended",
    markExcluded: "Mark excluded",
    demoBanner: "Explicit demo mode. Failed live retrieval will not fall back to demo data.",
    banner: "NCBI: {ncbi}   Model: {llm}   Listening on 127.0.0.1",
    queued: "Queued",
    running: "Running",
    pausing: "Pausing",
    paused: "Paused",
    waiting_for_credentials: "Waiting for credentials",
    completed: "Completed",
    partial: "Partial",
    failed: "Failed",
    cancelled: "Cancelled",
    defaultOverride: "Manual override after review",
    gsmCount: "GSM",
    independentDonors: "Independent donors",
  },
  de: {
    sampleSource: "Probenherkunft", sourcePrimary: "Direkte Primärproben", sourceCell: "Zelllinie / iPSC", sourceOrganoid: "Organoid", sourceXeno: "Xenotransplantat", tissueRequired: "Gewebe muss passen", deepLimit: "Limit der Tiefenprüfung", deepLimitHint: "Ein höherer Wert erhöht das Tokenlimit nicht; Prüfungen können unvollständig bleiben.", tierDefault: "Stufenstandard", selectionReason: "Auswahlfaktoren", selectionRank: "Prüfreihenfolge", notSelected: "Nicht zur Tiefenprüfung ausgewählt", disease_in_title: "Krankheit im Titel", disease_in_summary: "Krankheit in der Zusammenfassung", no_direct_disease_term: "Kein direkter Krankheitsbegriff", target_tissue: "Zielgewebe", target_tissue_sample_evidence: "Titel legt Zielgewebeproben nahe", target_tissue_in_title: "Zielgewebe im Titel", target_tissue_in_summary: "Zielgewebe nur in der Zusammenfassung", conflicting_tissue_in_title: "Titelgewebe widerspricht der Anforderung", patient_or_donor_context: "Patienten- oder Spenderkontext", control_context: "Kontrollkontext", patient_or_donor_in_title: "Patient oder Spender im Titel", control_in_title: "Kontrolle im Titel", model_or_intervention_context: "Modell- oder Interventionskontext", source_mismatch_model: "Titel legt Modellquelle gegen Primäranforderung nahe", primary_source_in_title: "Titel legt Primärentnahme nahe", requested_model_source: "Titel entspricht der angeforderten Modellquelle", hard_supported: "Hartes Kriterium in der Zusammenfassung gestützt", hard_material_supported: "Hartes Gewebe- oder Herkunftskriterium gestützt", hard_tissue_fail: "Hartes Gewebekriterium fehlgeschlagen", off_assay_microbiome: "Mikrobiom-Assay außerhalb der Anforderung", off_assay_proteomics: "Proteomik-Assay", off_assay_spatial: "Räumliche Omics", off_assay_epigenomics: "Epigenomik-Assay", off_assay_other: "Kein RNA-Sequenzierungsassay", off_assay_method: "Spezifische Methode passt nicht", gdstype_other: "GEO-Assaytyp ist Other", third_party_reanalysis: "Drittanbieter-Reanalyse", kind_unknown: "Unklassifiziert", kind_scrna_seq: "scRNA-seq", kind_snrna_seq: "snRNA-seq", kind_bulk_rna_seq: "bulk RNA-seq", kind_rna_seq_generic: "RNA-seq", kind_spatial_transcriptomics: "Räumliche Transkriptomik", kind_proteomics: "Proteomik", kind_epigenomics: "Epigenomik", kind_microbiome: "Mikrobiom", kind_other: "Anderer Assay",
    parseUsage: "Tokens für Kriterienanalyse:", estimatedUsage: "inkl. Schätzungen", tokenBudget: "Tokenbudget",
    intensity: "Prüfintensität", low: "Niedrig", medium: "Mittel", high: "Hoch", ultra: "Sehr hoch", startRun: "Prüfung starten", starting: "Wird gestartet…",
    checking: "Lokale Verbindung wird geprüft…",
    tagline: "Lokale GEO-Suche und Prüfung. Schlüssel bleiben nur im Prozessspeicher — nicht in Datenbank, Logs oder Excel.",
    workbenchTagline: "Lokale GEO-Suche und Prüfung. Vollständigkeit von GEO wird nicht zugesagt.",
    baseUrl: "Modell-Basis-URL",
    requestHost: "Anfragen gehen an: ",
    modelName: "Modellname",
    apiKey: "Modell-API-Schlüssel",
    ncbiEmail: "NCBI-Kontakt-E-Mail",
    ncbiKey: "NCBI-API-Schlüssel (optional)",
    testStart: "Verbindung testen und starten",
    testing: "Wird getestet…",
    ncbiOnly: "Nur mit NCBI-Suche eintreten",
    settings: "Einstellungen öffnen",
    settingsBtn: "Einstellungen",
    testConn: "Verbindung testen",
    tasks: "Aufgaben",
    clearTasks: "Aufgaben löschen",
    clearConfirm: "Alle lokalen Themen und Läufe löschen? GEO-Zusammenfassungs-Cache bleibt. Das kann nicht rückgängig gemacht werden.",
    cleared: "Themen und Läufe gelöscht.",
    help: "Verbindungshilfe",
    helpBody:
      "GEOScout spricht jede OpenAI-kompatible API an: Basis-URL und API-Schlüssel des Anbieters eintragen, dann Modellnamen eingeben oder laden. Beispiele: OpenAI https://api.openai.com/v1 ; offizielles DeepSeek https://api.deepseek.com (kein /v1); andere Gateways laut ihrer Doku. Schlüssel bleiben nur in diesem API-Prozess. NCBI-E-Mail ist der von NCBI verlangte Kontakt. Ohne Modell geht eine manuelle GEO-Suche.",
    fetchModels: "Modelle laden",
    fetchingModels: "Wird geladen…",
    pickModel: "Modell wählen",
    language: "Sprache",
    provider: "Anbieter",
    chooseProvider: "Anbieter wählen",
    customUrl: "Benutzerdefiniert",
    topic: "Thema",
    topicPh: "Thema in eigenen Worten beschreiben",
    createTopic: "Thema anlegen",
    parseSpec: "Kriterien parsen",
    manualSearch: "Manuelle englische Suche (kein Modellschlüssel)",
    ncbiSearch: "In aktuellem NCBI-Modus suchen",
    disease: "Krankheit",
    tissue: "Gewebe",
    organism: "Organismus",
    assay: "Assay",
    assayMethods: "Spezifische Methode",
    unspecified: "Nicht angegeben",
    minDonors: "Min. Spender pro Gruppe",
    matrix: "Prozessierte Matrix",
    matrixNone: "Nicht nötig",
    matrixPref: "Bevorzugt",
    matrixReq: "Erforderlich",
    unresolved: "Offen: ",
    run: "Lauf",
    stage: "Phase",
    status: "Status",
    queries: "Abfragen",
    uniqueGse: "Eindeutige GSE",
    stopReason: "Stoppgrund: ",
    credsLost: "Anmeldedaten fehlen.",
    reenterKey: "Schlüssel erneut eingeben",
    pause: "Pause",
    resume: "Fortsetzen",
    cancel: "Abbrechen",
    exportExcel: "Excel exportieren",
    queryLog: "Abfrageprotokoll",
    round: "Runde",
    term: "Suchbegriff",
    hits: "Treffer",
    added: "Neu",
    recommended: "Empfohlen",
    needsReview: "Prüfung nötig",
    excluded: "Ausgeschlossen",
    title: "Titel",
    taxon: "Taxon",
    tech: "Assay",
    reason: "Begründung",
    noCandidates: "Keine Kandidaten",
    detail: "Details",
    geoPage: "GEO-Eintrag",
    unknown: "Unbekannt",
    judgements: "Urteile je Kriterium (final)",
    evidence: "Belege",
    quote: "Zitat: ",
    samples: "Proben",
    donor: "Spender",
    overrideReason: "Override-Begründung",
    markRecommended: "Als empfohlen markieren",
    markExcluded: "Als ausgeschlossen markieren",
    demoBanner: "Expliziter Demo-Modus. Fehlgeschlagene Live-Abfragen fallen nicht auf Demo-Daten zurück.",
    banner: "NCBI: {ncbi}   Modell: {llm}   Lauscht auf 127.0.0.1",
    queued: "In Warteschlange",
    running: "Läuft",
    pausing: "Wird pausiert",
    paused: "Pausiert",
    waiting_for_credentials: "Wartet auf Anmeldedaten",
    completed: "Abgeschlossen",
    partial: "Teilweise",
    failed: "Fehlgeschlagen",
    cancelled: "Abgebrochen",
    defaultOverride: "Manuelle Überschreibung nach Prüfung",
    gsmCount: "GSM",
    independentDonors: "Unabhängige Spender",
  },
} as const;

export type MsgKey = keyof (typeof messages)["zh-CN"];

type Ctx = {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: MsgKey, vars?: Record<string, string>) => string;
};

const I18nContext = createContext<Ctx | null>(null);

function readLang(): Lang {
  try {
    const v = localStorage.getItem(STORAGE);
    if (v === "en" || v === "de" || v === "zh-CN") return v;
  } catch {
    /* ignore */
  }
  return "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readLang);
  const value = useMemo<Ctx>(() => {
    const t = (key: MsgKey, vars?: Record<string, string>) => {
      let text: string = messages[lang][key] || messages["zh-CN"][key] || key;
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          text = text.replaceAll(`{${k}}`, v);
        }
      }
      return text;
    };
    const setLang = (next: Lang) => {
      setLangState(next);
      try {
        localStorage.setItem(STORAGE, next);
      } catch {
        /* ignore */
      }
      document.documentElement.lang = next === "zh-CN" ? "zh-CN" : next;
    };
    return { lang, setLang, t };
  }, [lang]);
  if (typeof document !== "undefined") {
    document.documentElement.lang = lang === "zh-CN" ? "zh-CN" : lang;
  }
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n");
  return ctx;
}

export function LanguageSelect() {
  const { lang, setLang, t } = useI18n();
  return (
    <label className="lang-select">
      <span className="muted">{t("language")}</span>
      <select
        aria-label={t("language")}
        value={lang}
        onChange={(e) => setLang(e.target.value as Lang)}
      >
        <option value="zh-CN">简体中文</option>
        <option value="en">English</option>
        <option value="de">Deutsch</option>
      </select>
    </label>
  );
}
