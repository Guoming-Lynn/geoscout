from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.connectors.llm import LLMError, validate_assessment
from app.evidence.store import quote_in_text
from app.pipeline.assay import assay_relation, infer_sample_assay
from app.pipeline.donors import infer_group_label, _organism_ok
from app.schemas.spec import CriterionJudgement, ModelAssessment, ResearchSpec

DETERMINISTIC_FIELDS = {"organism", "donors", "assay", "age", "sex"}
# Fail on these requires citing GSM/sample evidence; abstract absence is unknown.
SAMPLE_FAIL_FIELDS = {"groups", "donors", "donors_per_group", "age", "sex", "assay"}
# Screen-time NCBI gdstype/taxon fail may still exclude without SOFT samples.
ABSTRACT_CANNOT_FAIL = {"groups", "donors", "donors_per_group", "age", "sex"}


SAMPLE_CHAR_BUDGET = 20_000
_MOUSE_TOKENS = ("murine", "mouse", "mus musculus", "小鼠")
_HUMAN_TOKENS = ("homo sapiens", "human", "人类")


def _criterion_field(criterion_id: str) -> str:
    if criterion_id.startswith("meta_"):
        return criterion_id[5:]
    return criterion_id


def _sample_evidence_ids(evidence: list[dict[str, Any]]) -> dict[str, str]:
    by_gsm: dict[str, str] = {}
    for row in evidence:
        if not _is_sample_evidence(row):
            continue
        eid = str(row.get("evidence_id") or "")
        if not eid:
            continue
        path = str(row.get("field_path") or "")
        text = str(row.get("text") or "")
        for token in path.replace("/", ".").split("."):
            if token.upper().startswith("GSM") and len(token) > 3:
                by_gsm[token.upper()] = eid
        for token in text.split():
            raw = token.strip(",;:()[]")
            if raw.upper().startswith("GSM") and len(raw) > 3:
                by_gsm.setdefault(raw.upper(), eid)
    return by_gsm


def _compact_sample(row: dict[str, Any], *, evidence_id: str = "") -> dict[str, Any]:
    compact = {
        "gsm": row.get("gsm") or "",
        "title": row.get("title") or "",
        "organism": row.get("organism") or "",
        "source_name": row.get("source_name") or "",
        "donor_key": row.get("donor_key"),
        "group_label": row.get("group_label"),
        "library_strategy": row.get("library_strategy") or "",
        "library_source": row.get("library_source") or "",
        "characteristics": row.get("characteristics") or [],
    }
    if evidence_id:
        compact["evidence_id"] = evidence_id
    return compact


def fit_samples(
    samples: list[dict[str, Any]],
    *,
    budget: int = SAMPLE_CHAR_BUDGET,
    evidence: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Send complete GSM records only. Record coverage; do not silently drop the remainder."""
    ids = _sample_evidence_ids(evidence or [])
    included: list[dict[str, Any]] = []
    used = 2
    for row in samples:
        gsm = str(row.get("gsm") or "").upper()
        compact = _compact_sample(row, evidence_id=ids.get(gsm, ""))
        size = len(json.dumps(compact, ensure_ascii=False))
        if included and used + size > budget:
            break
        included.append(compact)
        used += size
    total = len(samples)
    return included, {
        "total": total,
        "included": len(included),
        "complete": len(included) == total,
    }


def study_evidence_only(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in evidence if not _is_sample_evidence(row)]


def judge_user_payload(
    spec: ResearchSpec,
    gse: str,
    *,
    summary: dict[str, Any],
    evidence: list[dict[str, Any]],
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    """Payload for assess/verify. Sample records live in samples[]; evidence is study-level only."""
    included, coverage = fit_samples(samples, evidence=evidence)
    return {
        "gse": gse,
        "sample_records_available": bool(samples),
        "sample_coverage": coverage,
        "spec": spec.model_dump(),
        "summary": {
            "title": summary.get("title") or "",
            "summary": summary.get("summary") or "",
            "overall_design": summary.get("overall_design") or "",
            "taxon": summary.get("taxon") or "",
            "gdstype": summary.get("gdstype") or "",
            "n_samples": summary.get("n_samples"),
        },
        "samples": included,
        "evidence": study_evidence_only(evidence),
    }


@dataclass
class CheckedAssessment:
    judgements: list[CriterionJudgement]
    invalid: bool = False
    incomplete: bool = False
    error: str = ""
    unknown_ids: list[str] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    missing_ids: list[str] = field(default_factory=list)
    raw_model: ModelAssessment | None = None


def check_model_assessment(
    spec: ResearchSpec,
    raw: dict[str, Any],
    evidence: list[dict[str, Any]],
    samples: list[dict[str, Any]] | None = None,
    study: dict[str, Any] | None = None,
    sample_coverage: dict[str, Any] | None = None,
) -> CheckedAssessment:
    """Validate model output against this run's ResearchSpec, evidence texts, and GSMs."""
    try:
        model = validate_assessment(raw)
    except LLMError as exc:
        filled = _unknown_all(spec, f"模型输出无效: {exc}")
        return CheckedAssessment(judgements=filled, invalid=True, incomplete=True, error=str(exc))

    allowed = {c.criterion_id for c in spec.inclusion_criteria}
    seen: list[str] = []
    unknown_ids: list[str] = []
    duplicate_ids: list[str] = []
    by_id: dict[str, CriterionJudgement] = {}
    try:
        for item in model.judgements:
            cid = item.criterion_id
            if cid not in allowed:
                unknown_ids.append(cid)
                continue
            if cid in by_id:
                duplicate_ids.append(cid)
                continue
            seen.append(cid)
            _bind_quotes_to_evidence(item, evidence)
            _demote_study_level_fail(item, evidence, samples)
            _demote_source_conflict(item, evidence, study)
            criterion = next(c for c in spec.inclusion_criteria if c.criterion_id == cid)
            _bind_qualifying_gsms(item, spec, criterion, samples, study=study)
            by_id[cid] = item
    except LLMError as exc:
        filled = _unknown_all(spec, str(exc))
        return CheckedAssessment(
            judgements=filled,
            invalid=True,
            incomplete=True,
            error=str(exc),
            unknown_ids=unknown_ids,
            duplicate_ids=duplicate_ids,
        )

    if unknown_ids or duplicate_ids:
        err = ""
        if unknown_ids:
            err += "未知 criterion_id: " + ",".join(unknown_ids) + "。"
        if duplicate_ids:
            err += "重复 criterion_id: " + ",".join(duplicate_ids) + "。"
        filled = _unknown_all(spec, err)
        return CheckedAssessment(
            judgements=filled,
            invalid=True,
            incomplete=True,
            error=err,
            unknown_ids=unknown_ids,
            duplicate_ids=duplicate_ids,
        )

    missing = [c.criterion_id for c in spec.inclusion_criteria if c.criterion_id not in by_id]
    judgements: list[CriterionJudgement] = []
    for criterion in spec.inclusion_criteria:
        if criterion.criterion_id in by_id:
            judgements.append(by_id[criterion.criterion_id])
        else:
            judgements.append(
                CriterionJudgement(
                    criterion_id=criterion.criterion_id,
                    verdict="unknown",
                    reason="模型未回答该条件。",
                    judge_source="model",
                )
            )
    incomplete = bool(missing)
    judgements = _restrict_to_common_subset(spec, judgements, samples, study=study)
    _demote_incomplete_sample_coverage(judgements, sample_coverage)
    return CheckedAssessment(
        judgements=judgements,
        invalid=False,
        incomplete=incomplete,
        error="漏答: " + ",".join(missing) if missing else "",
        missing_ids=missing,
        raw_model=model,
    )


def _bind_quotes_to_evidence(item: CriterionJudgement, evidence: list[dict[str, Any]]) -> None:
    allowed = {row["evidence_id"]: row.get("text") or "" for row in evidence}
    if item.verdict in {"pass", "fail"} and not item.evidence_ids:
        raise LLMError(f"{item.criterion_id} 的 pass/fail 缺少 evidence_ids")
    quotes = list(item.quotes) if item.quotes else ([item.quote] if item.quote else [])
    for idx, eid in enumerate(item.evidence_ids):
        if eid not in allowed:
            raise LLMError(f"非法 evidence_id: {eid}")
        if idx < len(quotes) and quotes[idx]:
            if not quote_in_text(quotes[idx], allowed[eid]):
                _demote_unverified_quote(item, eid)
                return
        elif item.quote and idx == 0:
            if not quote_in_text(item.quote, allowed[eid]):
                _demote_unverified_quote(item, eid)
                return
        # A shared quote is never required to appear in every cited source.


def _demote_unverified_quote(item: CriterionJudgement, evidence_id: str) -> None:
    item.verdict = "unknown"
    item.evidence_ids = []
    item.quote = ""
    item.quotes = []
    item.reason = f"引句无法在证据 {evidence_id} 原文中核对，改为 unknown。"


def _is_sample_evidence(row: dict[str, Any]) -> bool:
    path = str(row.get("field_path") or "").lower()
    return "sample" in path or "gsm" in path or "characteristics" in path


def _demote_study_level_fail(
    item: CriterionJudgement,
    evidence: list[dict[str, Any]],
    samples: list[dict[str, Any]] | None,
) -> None:
    """Title/abstract absence is not fail for donors, groups, assay, age, or sex."""
    if item.verdict != "fail":
        return
    field = item.criterion_id
    if field.startswith("meta_"):
        field = field[5:]
    if field not in SAMPLE_FAIL_FIELDS:
        return
    by_id = {str(row.get("evidence_id") or ""): row for row in evidence}
    cited = [by_id[eid] for eid in item.evidence_ids if eid in by_id]
    if any(_is_sample_evidence(row) for row in cited):
        return
    item.verdict = "unknown"
    item.clue_only = True
    item.reason = (
        "摘要或标题未出现某词不能判 fail；供体/分组/技术/年龄性别需要样本级证据。"
        + ("" if samples else "当前没有 GSM 样本记录。")
        + "改为 unknown。"
    )


def _taxon_text(study: dict[str, Any] | None) -> str:
    if not study:
        return ""
    return str(study.get("taxon") or "")


def _cited_blob(item: CriterionJudgement, evidence: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    by_id = {str(row.get("evidence_id") or ""): row for row in evidence}
    cited = [by_id[eid] for eid in item.evidence_ids if eid in by_id]
    parts = [str(row.get("text") or "") for row in cited]
    if item.quote:
        parts.append(item.quote)
    parts.extend(item.quotes or [])
    return cited, " ".join(parts).lower()


def _demote_source_conflict(
    item: CriterionJudgement,
    evidence: list[dict[str, Any]],
    study: dict[str, Any] | None,
) -> None:
    """Abstract vs taxon conflict is 待核实, not an automatic exclude."""
    if item.verdict != "fail":
        return
    field = _criterion_field(item.criterion_id)
    if field not in {"disease", "tissue"}:
        return
    cited, blob = _cited_blob(item, evidence)
    if any(_is_sample_evidence(row) for row in cited):
        return
    taxon = _taxon_text(study).lower()
    if not taxon:
        for row in evidence:
            path = str(row.get("field_path") or "").lower()
            if path.endswith("taxon") or "taxon" in path:
                taxon = str(row.get("text") or "").lower()
                break
    human_taxon = any(tok in taxon for tok in _HUMAN_TOKENS)
    mouse_taxon = any(tok in taxon for tok in _MOUSE_TOKENS)
    mouse_cite = any(tok in blob for tok in _MOUSE_TOKENS)
    human_cite = any(tok in blob for tok in _HUMAN_TOKENS)
    conflict = (human_taxon and mouse_cite) or (mouse_taxon and human_cite)
    if not conflict:
        return
    item.verdict = "unknown"
    item.clue_only = True
    item.reason = "来源冲突：摘要叙述与 taxon 不一致，待核实，不能直接排除。"


def _demote_incomplete_sample_coverage(
    judgements: list[CriterionJudgement],
    sample_coverage: dict[str, Any] | None,
) -> None:
    if not sample_coverage or sample_coverage.get("complete", True):
        return
    for item in judgements:
        field = _criterion_field(item.criterion_id)
        if field not in SAMPLE_FAIL_FIELDS or item.verdict != "pass":
            continue
        item.verdict = "unknown"
        item.clue_only = True
        item.reason = "样本记录未完整纳入模型输入，不能据此推荐。"


def _bind_qualifying_gsms(
    item: CriterionJudgement,
    spec: ResearchSpec,
    criterion,
    samples: list[dict[str, Any]] | None,
    study: dict[str, Any] | None = None,
) -> None:
    gsms = [str(g).strip() for g in item.qualifying_gsms if str(g).strip()]
    if not gsms:
        return
    if not samples:
        raise LLMError(f"{item.criterion_id} 列出了 qualifying_gsms，但当前 GSE 尚未完成样本获取")
    by_gsm = {str(s.get("gsm") or "").upper(): s for s in samples if s.get("gsm")}
    field = criterion.field
    kept: list[str] = []
    contradict: list[str] = []
    insufficient: list[str] = []
    assay_notes: list[str] = []
    for gsm in gsms:
        sample = by_gsm.get(gsm.upper())
        if sample is None:
            raise LLMError(f"qualifying_gsms 含有不属于当前 GSE 的 {gsm}")
        if field == "organism" and spec.organisms:
            org = _organism_ok(sample, spec.organisms)
            if org is not True:
                raise LLMError(f"{gsm} 与要求的物种子集不一致")
        if field in {"groups", "donors"} and spec.required_groups:
            label = infer_group_label(sample, spec=spec)
            if label not in {g.lower() for g in spec.required_groups}:
                raise LLMError(f"{gsm} 的分组 {label or '未知'} 与条件不一致")
        if field == "assay" and spec.assay_types:
            call = infer_sample_assay(sample, study)
            rel = assay_relation(list(spec.assay_types), call)
            if rel == "contradict":
                contradict.append(gsm)
                assay_notes.append(f"{gsm} 明确为 {call.kind}，与要求 {','.join(spec.assay_types)} 矛盾")
                continue
            if rel == "insufficient":
                insufficient.append(gsm)
                assay_notes.append(f"{gsm} 仅有 {call.evidence or '不足'} 证据，不能证明 {','.join(spec.assay_types)}")
                continue
            item.support_text = item.support_text or call.evidence
        kept.append(gsm)
    if field == "assay" and spec.assay_types:
        if contradict and not kept:
            item.verdict = "fail"
            item.reason = "；".join(assay_notes) or "列出的 GSM 与要求的细分技术矛盾。"
            item.qualifying_gsms = []
            return
        if not kept:
            item.verdict = "unknown"
            item.reason = "；".join(assay_notes) or "RNA-Seq 不能单独证明 bulk/sc/sn。"
            item.qualifying_gsms = []
            item.clue_only = True
            return
        item.qualifying_gsms = kept
        if contradict or insufficient:
            item.reason = (item.reason or "") + " 仅保留技术匹配的子集：" + ",".join(kept)
        return
    if field in {"groups", "donors"} and spec.required_groups:
        labels = {infer_group_label(by_gsm[g.upper()], spec=spec) for g in kept}
        needed = {g.lower() for g in spec.required_groups}
        if not needed.issubset({x for x in labels if x}):
            item.verdict = "unknown"
            item.reason = "列出的 GSM 未覆盖全部要求分组。"
            item.qualifying_gsms = kept
            return
    item.qualifying_gsms = kept


def _restrict_to_common_subset(
    spec: ResearchSpec,
    judgements: list[CriterionJudgement],
    samples: list[dict[str, Any]] | None,
    study: dict[str, Any] | None = None,
) -> list[CriterionJudgement]:
    if not samples:
        return judgements
    hard = [c for c in spec.inclusion_criteria if c.priority == "hard"]
    by_id = {j.criterion_id: j for j in judgements}
    claimed: list[set[str]] = []
    for criterion in hard:
        item = by_id.get(criterion.criterion_id)
        if not item or item.verdict != "pass":
            continue
        gsms = {str(g).upper() for g in item.qualifying_gsms if g}
        if gsms:
            claimed.append(gsms)
    if len(claimed) >= 2:
        common = set.intersection(*claimed)
        if not common:
            for criterion in hard:
                item = by_id.get(criterion.criterion_id)
                if item and item.verdict == "pass":
                    item.verdict = "unknown"
                    item.reason = (item.reason or "") + " 各硬条件没有共同可用样本子集。"
                    item.clue_only = True
            return judgements
        by_gsm = {str(s.get("gsm") or "").upper(): s for s in samples if s.get("gsm")}
        usable = {gsm for gsm in common if _sample_fits_all_hard(by_gsm.get(gsm), spec, study)}
        if not usable:
            for criterion in hard:
                item = by_id.get(criterion.criterion_id)
                if item and item.verdict == "pass":
                    item.verdict = "unknown"
                    item.reason = (item.reason or "") + " 共同子集无法同时满足全部硬条件。"
                    item.clue_only = True
            return judgements
        for criterion in hard:
            item = by_id.get(criterion.criterion_id)
            if item and item.verdict == "pass" and item.qualifying_gsms:
                item.qualifying_gsms = [g for g in item.qualifying_gsms if g.upper() in usable]
                if not item.qualifying_gsms:
                    item.verdict = "unknown"
                    item.reason = (item.reason or "") + " 共同子集为空。"
                    item.clue_only = True
        groups_item = next((j for j in judgements if j.criterion_id in {"groups", "donors_per_group"} and j.verdict == "pass"), None)
        if groups_item and spec.required_groups:
            labels = {infer_group_label(by_gsm[g], spec=spec) for g in usable if g in by_gsm}
            if not {x.lower() for x in spec.required_groups}.issubset({x for x in labels if x}):
                groups_item.verdict = "unknown"
                groups_item.reason = (groups_item.reason or "") + " 共同子集未覆盖全部要求分组。"
    return judgements


def _sample_fits_all_hard(sample: dict[str, Any] | None, spec: ResearchSpec, study: dict[str, Any] | None) -> bool:
    if not sample:
        return False
    if spec.organisms and _organism_ok(sample, spec.organisms) is not True:
        return False
    if spec.assay_types:
        call = infer_sample_assay(sample, study)
        if assay_relation(list(spec.assay_types), call) != "ok":
            return False
    return True


def bind_rule_evidence(
    judgements: list[CriterionJudgement],
    evidence: list[dict[str, Any]],
) -> list[CriterionJudgement]:
    """Attach evidence_ids when rule support_text occurs in a stored source."""
    out: list[CriterionJudgement] = []
    for item in judgements:
        if item.evidence_ids or not item.support_text:
            out.append(item)
            continue
        needle = item.support_text.strip()
        hits = [
            row["evidence_id"]
            for row in evidence
            if needle and needle.lower() in (row.get("text") or "").lower()
        ]
        if hits:
            out.append(item.model_copy(update={"evidence_ids": hits[:8]}))
        else:
            out.append(item)
    return out


def merge_final(
    spec: ResearchSpec,
    rules: list[CriterionJudgement],
    first: CheckedAssessment | None,
    verify: CheckedAssessment | None,
    samples: list[dict[str, Any]] | None = None,
    study: dict[str, Any] | None = None,
) -> tuple[list[CriterionJudgement], list[dict[str, Any]], bool, bool]:
    """Merge rule / first model / verify into a final snapshot.

    Returns judgements, conflicts, review_complete, model_invalid.
    """
    first_ok = first is not None and not first.invalid
    verify_ok = verify is not None and not verify.invalid
    first_map = {j.criterion_id: j for j in (first.judgements if first_ok else [])}
    verify_map = {j.criterion_id: j for j in (verify.judgements if verify_ok else [])}
    model_invalid = bool((first and first.invalid) or (verify and verify.invalid))
    review_complete = first_ok and verify_ok and not (first and first.incomplete) and not (verify and verify.incomplete)
    conflicts: list[dict[str, Any]] = []
    merged: list[CriterionJudgement] = []
    rule_map = {j.criterion_id: j for j in rules}
    for criterion in spec.inclusion_criteria:
        rule = rule_map.get(criterion.criterion_id) or CriterionJudgement(
            criterion_id=criterion.criterion_id,
            verdict="unknown",
            reason="无规则判断。",
            judge_source="rule",
        )
        f_item = first_map.get(criterion.criterion_id)
        v_item = verify_map.get(criterion.criterion_id)
        if (
            f_item
            and v_item
            and f_item.verdict != "unknown"
            and v_item.verdict != "unknown"
        ):
            if f_item.verdict != v_item.verdict:
                conflicts.append(
                    {
                        "criterion_id": criterion.criterion_id,
                        "first": f_item.verdict,
                        "verify": v_item.verdict,
                        "first_evidence_ids": f_item.evidence_ids,
                        "verify_evidence_ids": v_item.evidence_ids,
                        "first_reason": f_item.reason,
                        "verify_reason": v_item.reason,
                    }
                )
                merged.append(
                    CriterionJudgement(
                        criterion_id=criterion.criterion_id,
                        verdict="unknown",
                        reason=f"两次模型判断冲突（{f_item.verdict} vs {v_item.verdict}），两侧证据均保留。",
                        evidence_ids=list(dict.fromkeys(f_item.evidence_ids + v_item.evidence_ids)),
                        quote=v_item.quote or f_item.quote,
                        quotes=list(f_item.quotes) + list(v_item.quotes),
                        judge_source="conflict",
                    )
                )
                continue
            chosen = v_item.model_copy(update={"judge_source": "verify"})
            if rule.verdict == "fail" and not rule.clue_only and _rule_standalone(rule):
                merged.append(rule.model_copy(update={"judge_source": "rule"}))
            elif rule.clue_only and chosen.verdict == "pass" and not chosen.qualifying_gsms:
                merged.append(
                    rule.model_copy(
                        update={
                            "verdict": "unknown",
                            "reason": rule.reason + " 模型未列出合格 GSM，不能把混合研究整体判为通过。",
                            "evidence_ids": chosen.evidence_ids,
                            "quote": chosen.quote,
                            "judge_source": "merge",
                        }
                    )
                )
            else:
                merged.append(chosen)
            continue
        if _rule_standalone(rule):
            merged.append(rule)
            continue
        merged.append(
            CriterionJudgement(
                criterion_id=criterion.criterion_id,
                verdict="unknown",
                reason="模型未完成有效核验；不继承弱关键词规则的 pass。"
                + ((" 规则说明：" + rule.reason) if rule.reason else ""),
                judge_source="rule",
                clue_only=True,
                support_text=rule.support_text,
            )
        )
    merged = _restrict_to_common_subset(spec, merged, samples, study=study)
    return merged, conflicts, review_complete, model_invalid


def _rule_standalone(rule: CriterionJudgement) -> bool:
    if rule.clue_only:
        return False
    if rule.verdict == "unknown":
        return False
    if not (rule.evidence_ids or rule.support_text or rule.quote):
        return False
    field_hint = rule.criterion_id.split("_")[0]
    if rule.criterion_id in DETERMINISTIC_FIELDS or field_hint in DETERMINISTIC_FIELDS:
        return True
    if rule.criterion_id in {"organism", "donors_per_group", "assay"}:
        return True
    return rule.verdict == "fail"


def _unknown_all(spec: ResearchSpec, reason: str) -> list[CriterionJudgement]:
    return [
        CriterionJudgement(
            criterion_id=c.criterion_id,
            verdict="unknown",
            reason=reason,
            judge_source="model",
        )
        for c in spec.inclusion_criteria
    ]
