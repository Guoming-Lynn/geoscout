from __future__ import annotations

from typing import Any

from app.pipeline.assessment import ABSTRACT_CANNOT_FAIL
from app.pipeline.donors import donor_criterion_judgement, infer_group_label
from app.schemas.spec import Criterion, CriterionJudgement, ResearchSpec, Verdict

RNASEQ_GTYP = "expression profiling by high throughput sequencing"
SCRNA_HINTS = [
    "single-cell",
    "single cell",
    "scrna",
    "scRNA",
    "single-cell rna",
    "单细胞",
]
SNRNA_HINTS = ["snrna", "single-nucleus", "single nucleus", "单核"]
BULK_HINTS = ["bulk rna", "bulk rna-seq", "bulk transcriptome"]
TENX_HINTS = ["10x", "10x genomics"]
AGE_KEYS = {"age", "age (years)", "age_years", "age (yrs)", "donor age", "patient age", "age (y)"}
SEX_KEYS = {"sex", "gender", "biological sex", "sex (female/male)", "donor sex"}


def rule_judgements(
    spec: ResearchSpec,
    summary: dict[str, Any],
    samples: list[dict[str, Any]] | None = None,
    *,
    truncated: bool = False,
) -> list[CriterionJudgement]:
    text = _blob(summary, samples)
    out: list[CriterionJudgement] = []
    for criterion in spec.inclusion_criteria:
        out.append(_judge_one(criterion, spec, summary, samples or [], text, truncated=truncated))
    return out


def _judge_one(
    criterion: Criterion,
    spec: ResearchSpec,
    summary: dict[str, Any],
    samples: list[dict[str, Any]],
    text: str,
    *,
    truncated: bool,
) -> CriterionJudgement:
    field = criterion.field
    if field == "organism":
        return _organism(criterion, summary, samples)
    if field == "assay":
        return _assay(criterion, summary, samples, text)
    if field == "disease":
        return _keyword(criterion, text, spec.disease, hard_fail=False)
    if field == "tissue":
        return _keyword(criterion, text, spec.tissues, hard_fail=False)
    if field == "groups":
        return _groups(criterion, spec, text, samples)
    if field == "donors":
        return donor_criterion_judgement(
            criterion,
            samples,
            spec.required_groups,
            truncated=truncated,
            organisms=spec.organisms,
            control_type=spec.control_type,
            spec=spec,
        )
    if field in {"age", "sex"} or field.startswith("meta_"):
        return _clinical(criterion, samples)
    if field == "processed_matrix":
        return _matrix(criterion, summary)
    return CriterionJudgement(criterion_id=criterion.criterion_id, verdict="unknown", reason="无程序规则。", judge_source="rule")


def _organism(criterion: Criterion, summary: dict[str, Any], samples: list[dict[str, Any]]) -> CriterionJudgement:
    wanted = {str(x).lower() for x in (criterion.value or [])}

    def matches(value: str) -> bool:
        t = value.lower()
        return any(w in t or t in w for w in wanted if w)

    if samples:
        labeled = [s for s in samples if s.get("organism")]
        matching = [s for s in labeled if matches(str(s.get("organism") or ""))]
        other = [s for s in labeled if not matches(str(s.get("organism") or ""))]
        gsms = [str(s.get("gsm") or "") for s in matching if s.get("gsm")]
        if matching and not other:
            return CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="pass",
                reason="样本物种均匹配。",
                judge_source="rule",
                support_text=str(matching[0].get("organism") or ""),
                qualifying_gsms=gsms,
            )
        if matching and other:
            return CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="unknown",
                reason="混合物种研究。仅下列 GSM 匹配目标物种，不能把研究整体或交叉拼接子集判为合格："
                + ",".join(gsms[:40]),
                judge_source="rule",
                qualifying_gsms=gsms,
                clue_only=True,
            )
        if labeled and not matching:
            taxa = sorted({str(s.get("organism")) for s in labeled})
            return CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="fail",
                reason=f"样本物种为 {'; '.join(taxa)}，与要求不符。",
                judge_source="rule",
                support_text="; ".join(taxa),
            )
    taxon = str(summary.get("taxon") or "")
    if not taxon:
        return CriterionJudgement(criterion_id=criterion.criterion_id, verdict="unknown", reason="摘要未提供物种。", judge_source="rule")
    parts = [p.strip() for p in taxon.replace(";", ",").split(",") if p.strip()]
    if len(parts) > 1 and any(matches(p) for p in parts) and any(not matches(p) for p in parts):
        return CriterionJudgement(
            criterion_id=criterion.criterion_id,
            verdict="unknown",
            reason="摘要列出多种物种，缺少样本级子集，不能整体通过。",
            judge_source="rule",
            clue_only=True,
            support_text=taxon,
        )
    if matches(taxon):
        return CriterionJudgement(
            criterion_id=criterion.criterion_id,
            verdict="pass",
            reason="摘要物种匹配。",
            judge_source="rule",
            support_text=taxon,
        )
    return CriterionJudgement(
        criterion_id=criterion.criterion_id,
        verdict="fail",
        reason=f"物种为 {taxon}，与要求不符。",
        judge_source="rule",
        support_text=taxon,
    )


def _as_str_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(x) for x in value if x is not None and str(x) != ""]
    return [str(value)]


def _flatten_text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return " ".join(_flatten_text(v) for v in raw.values())
    if isinstance(raw, (list, tuple)):
        return " ".join(_flatten_text(v) for v in raw)
    return str(raw)


def _gdstype_text(summary: dict[str, Any]) -> str:
    raw = summary.get("gdstype")
    if raw in (None, "", []):
        raw = summary.get("type")
    return _flatten_text(raw).lower()


def _assay(criterion: Criterion, summary: dict[str, Any], samples: list[dict[str, Any]], text: str) -> CriterionJudgement:
    wanted = _as_str_list(criterion.value)
    gdstype = _gdstype_text(summary)
    blob = text.lower()
    has_scrna = any(h.lower() in blob for h in SCRNA_HINTS)
    has_snrna = any(h.lower() in blob for h in SNRNA_HINTS)
    has_bulk = any(h.lower() in blob for h in BULK_HINTS)
    has_tenx = any(h.lower() in blob for h in TENX_HINTS)
    is_rnaseq = RNASEQ_GTYP in gdstype
    mixed_tech = has_scrna and has_bulk
    wants_rnaseq = any(w in {"scrna_seq", "snrna_seq", "bulk_rna_seq"} for w in wanted)
    if wants_rnaseq and "profiling by array" in gdstype:
        return CriterionJudgement(
            criterion_id=criterion.criterion_id,
            verdict="fail",
            reason="GEO 技术类型为微阵列，与 RNA-seq 要求直接冲突。",
            judge_source="rule",
            support_text=_flatten_text(summary.get("gdstype") or summary.get("type") or ""),
        )

    if "scrna_seq" in wanted:
        if mixed_tech or (has_scrna and has_snrna):
            return CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="unknown",
                reason="研究可能混合多种转录组技术，必须列出同一适用子集的 GSM 才能通过。",
                judge_source="rule",
                clue_only=True,
            )
        if has_scrna and is_rnaseq:
            return CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="pass",
                reason="存在单细胞 RNA-seq 直接表述，且 GTYP 为高通量表达谱。",
                judge_source="rule",
                support_text="single-cell" if "single-cell" in blob else "scrna",
            )
        if has_tenx and not has_scrna:
            return CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="unknown",
                reason="仅出现 10x Genomics，不能单独证明是 scRNA-seq。",
                judge_source="rule",
                clue_only=True,
            )
        if is_rnaseq:
            return CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="unknown",
                reason="是高通量表达谱，但缺少单细胞直接描述。",
                judge_source="rule",
            )
        return CriterionJudgement(criterion_id=criterion.criterion_id, verdict="unknown", reason="技术类型证据不足。", judge_source="rule")

    if "snrna_seq" in wanted:
        if has_snrna and is_rnaseq:
            return CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="pass",
                reason="存在单核 RNA-seq 直接表述。",
                judge_source="rule",
                support_text="snRNA" if "snrna" in blob else "single-nucleus",
            )
        return CriterionJudgement(criterion_id=criterion.criterion_id, verdict="unknown", reason="缺少 snRNA-seq 直接描述。", judge_source="rule")

    if "bulk_rna_seq" in wanted:
        if mixed_tech or has_scrna:
            return CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="unknown",
                reason="摘要出现单细胞表述，不能因此排除可能存在的 bulk 子集，也不能把研究整体判为 bulk。",
                judge_source="rule",
                clue_only=True,
            )
        if has_bulk and is_rnaseq:
            return CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="pass",
                reason="存在 bulk RNA-seq 直接表述。",
                judge_source="rule",
                support_text="bulk",
            )
        if is_rnaseq and not has_scrna:
            return CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="unknown",
                reason="高通量表达谱且无单细胞词，仍不足以证明 bulk；缺少明确 bulk 描述。",
                judge_source="rule",
            )
        return CriterionJudgement(criterion_id=criterion.criterion_id, verdict="unknown", reason="不能确认 bulk RNA-seq。", judge_source="rule")
    return CriterionJudgement(criterion_id=criterion.criterion_id, verdict="unknown", reason="未指定可判定技术。", judge_source="rule")


def _keyword(criterion: Criterion, text: str, seeds: list[str], *, hard_fail: bool) -> CriterionJudgement:
    blob = text.lower()
    hit = next((seed for seed in seeds if seed and seed.lower() in blob), None)
    if hit:
        return CriterionJudgement(
            criterion_id=criterion.criterion_id,
            verdict="pass",
            reason="文本出现相关词。",
            judge_source="rule",
            support_text=hit,
        )
    if hard_fail:
        return CriterionJudgement(criterion_id=criterion.criterion_id, verdict="fail", reason="文本明确不含该主题。", judge_source="rule")
    return CriterionJudgement(
        criterion_id=criterion.criterion_id,
        verdict="unknown",
        reason="摘要未直接出现该词，需深核或人工核对。",
        judge_source="rule",
    )


def _groups(criterion: Criterion, spec: ResearchSpec, text: str, samples: list[dict[str, Any]]) -> CriterionJudgement:
    needed = [str(x).lower() for x in (criterion.value or [])]
    if samples:
        found = {infer_group_label(s, spec=spec) for s in samples}
        found.discard(None)
        if needed and set(needed).issubset(found):
            gsms = [str(s.get("gsm") or "") for s in samples if infer_group_label(s, spec=spec) in needed]
            return CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="pass",
                reason="样本特征字段给出所需分组。",
                judge_source="rule",
                support_text=",".join(sorted(x for x in found if x)),
                qualifying_gsms=gsms,
            )
        if any(infer_group_label(s, spec=spec) for s in samples):
            return CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="unknown",
                reason="样本分组不完整，标题中的 control/disease 不能证明目标子集存在合格对照。",
                judge_source="rule",
                clue_only=True,
            )
    blob = text.lower()
    mapping = {
        "lesion": ["lesion", "plaque", "disease", "atherosclerotic", "病例", "病变"],
        "control": ["control", "healthy", "normal", "adjacent", "对照", "健康"],
    }
    hinted = [item for item in needed if any(k in blob for k in mapping.get(item, [item]))]
    if hinted:
        return CriterionJudgement(
            criterion_id=criterion.criterion_id,
            verdict="unknown",
            reason="标题或摘要出现分组线索，不能证明目标样本子集中存在符合要求的对照/病变。",
            judge_source="rule",
            clue_only=True,
        )
    return CriterionJudgement(criterion_id=criterion.criterion_id, verdict="unknown", reason="分组证据不足。", judge_source="rule")


def _clinical(criterion: Criterion, samples: list[dict[str, Any]]) -> CriterionJudgement:
    field = criterion.field.replace("meta_", "")
    keys = AGE_KEYS if field == "age" else SEX_KEYS if field == "sex" else {field, criterion.user_text.lower()}
    for sample in samples:
        for row in sample.get("characteristics") or []:
            key = str(row.get("key") or "").lower()
            value = str(row.get("value") or "").strip()
            if key in keys and value:
                return CriterionJudgement(
                    criterion_id=criterion.criterion_id,
                    verdict="pass",
                    reason=f"样本特征字段 {key} 提供 {field}。",
                    judge_source="rule",
                    support_text=str(row.get("raw") or value),
                )
    return CriterionJudgement(
        criterion_id=criterion.criterion_id,
        verdict="unknown",
        reason="GEO 元数据未提供该临床字段名；未提及不等于数据不存在。不会把 macrophage 等词当成 age。",
        judge_source="rule",
    )


def _matrix(criterion: Criterion, summary: dict[str, Any]) -> CriterionJudgement:
    supp = (summary.get("suppfile") or "").lower()
    names = " ".join(summary.get("suppl_names") or []).lower()
    blob = supp + " " + names
    clue = any(x in blob for x in ["h5ad", "h5", "mtx", "csv", "tsv", "txt", "rdata"])
    required = str(criterion.value or "") == "required" or criterion.priority == "hard"
    if clue:
        return CriterionJudgement(
            criterion_id=criterion.criterion_id,
            verdict="unknown",
            reason="文件名或后缀只是 probable 线索，尚未打开验证是否为可分析矩阵。",
            judge_source="rule",
            clue_only=True,
            support_text=supp or names[:80],
        )
    if required:
        return CriterionJudgement(
            criterion_id=criterion.criterion_id,
            verdict="unknown",
            reason="必需的处理后矩阵尚未被验证。",
            judge_source="rule",
        )
    return CriterionJudgement(
        criterion_id=criterion.criterion_id,
        verdict="unknown",
        reason="尚未验证处理后矩阵是否可直接分析。",
        judge_source="rule",
    )


def merge_verdicts(first: Verdict, second: Verdict) -> Verdict:
    if first == second:
        return first
    return "unknown"


def _criterion_field(criterion_id: str) -> str:
    if criterion_id.startswith("meta_"):
        return criterion_id[5:]
    return criterion_id


def classify(
    spec: ResearchSpec,
    judgements: list[CriterionJudgement],
    *,
    verified: bool,
    conflict: bool,
    model_invalid: bool,
    depth_complete: bool = True,
    review_complete: bool = True,
) -> tuple[str, str]:
    by_id = {j.criterion_id: j for j in judgements}
    hard = [c for c in spec.inclusion_criteria if c.priority == "hard"]

    def hard_fail() -> list[str]:
        return [
            c.criterion_id
            for c in hard
            if by_id.get(c.criterion_id) and by_id[c.criterion_id].verdict == "fail" and not by_id[c.criterion_id].clue_only
        ]

    fails = hard_fail()
    ready = verified and depth_complete and review_complete and not conflict and not model_invalid
    if not ready:
        if fails:
            abstract_only = (not depth_complete) and all(_criterion_field(fid) in ABSTRACT_CANNOT_FAIL for fid in fails)
            if abstract_only:
                return "needs_review", "硬条件失败缺少样本级证据，不能仅凭摘要排除: " + ",".join(fails)
            return "excluded", "硬条件失败: " + ",".join(fails)
        if model_invalid:
            return "needs_review", "复核失败：模型输出不符合契约，不是科研信息不足。"
        if not depth_complete:
            return "needs_review", "科研信息不足：深度核验未覆盖或样本记录不完整。"
        return "needs_review", "核验未完成、模型冲突、漏答或输出无效。"
    if hard:
        if fails:
            return "excluded", "硬条件失败: " + ",".join(fails)
        for c in hard:
            j = by_id.get(c.criterion_id)
            if j is None or j.verdict != "pass" or j.clue_only or not _has_support(j):
                return "needs_review", "硬条件缺少有效直接证据，或仍为 unknown/线索。"
        return "recommended", "全部硬条件通过，证据有效，深度核验与复核完成且无未决冲突。"
    theme = [
        j
        for j in judgements
        if j.criterion_id in {"disease", "assay", "organism", "tissue"} and j.verdict == "pass" and _has_support(j) and not j.clue_only
    ]
    if not judgements or all(j.verdict == "unknown" for j in judgements) or not theme:
        return "needs_review", "没有硬条件时仍需主题直接证据；全部 unknown 不能推荐。"
    return "recommended", "无硬条件，已完成核验且与主题有直接证据。"


def _has_support(j: CriterionJudgement) -> bool:
    return bool(j.evidence_ids) or bool(j.support_text) or bool(j.quote)


def soft_score(spec: ResearchSpec, judgements: list[CriterionJudgement]) -> tuple[float | None, float | None, int]:
    soft = [c for c in spec.inclusion_criteria if c.priority == "soft"]
    if not soft:
        return None, None, 0
    by_id = {j.criterion_id: j for j in judgements}
    gained = 0.0
    known = 0
    unknowns = 0
    for c in soft:
        j = by_id.get(c.criterion_id)
        if not j or j.verdict == "unknown":
            unknowns += 1
            continue
        known += 1
        if j.verdict == "pass":
            gained += 1
    return gained / len(soft), known / len(soft), unknowns


def _blob(summary: dict[str, Any], samples: list[dict[str, Any]] | None) -> str:
    parts = [
        str(summary.get("title") or ""),
        str(summary.get("summary") or ""),
        _gdstype_text(summary),
        str(summary.get("taxon") or ""),
    ]
    for sample in samples or []:
        parts.append(str(sample.get("title") or ""))
        parts.append(str(sample.get("source_name") or ""))
        parts.append(str(sample.get("library_strategy") or ""))
        for row in sample.get("characteristics") or []:
            parts.append(str(row.get("raw") or ""))
    return " ".join(parts)
