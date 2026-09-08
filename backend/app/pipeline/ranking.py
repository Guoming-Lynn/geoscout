from __future__ import annotations

import re
from typing import Any

from app.pipeline.assay import RNA_KINDS, assay_method_relation, assay_relation, infer_study_assay
from app.pipeline.lexicon import lexicon_terms
from app.pipeline.repo import load
from app.schemas.spec import ResearchSpec

_OFF_TARGET = {
    "brain": ["blood", "pbmc", "heart", "liver", "islet", "intestine", "colon"],
    "pancreatic islets": ["blood", "pbmc", "heart", "brain", "liver"],
    "pbmc": ["brain", "heart", "liver", "islet", "intestine", "colon"],
    "blood": ["brain", "heart", "liver", "islet", "intestine", "colon"],
    "intestine": ["blood", "pbmc", "heart", "brain", "liver", "islet"],
    "colon": ["blood", "pbmc", "heart", "brain", "liver", "islet"],
}
_MATERIAL = ["biopsy", "biopsies", "postmortem", "tissue", "islet", "islets", "pbmc", "cortex",
             "hippocampus", "dentate", "blood draw", "patient"]
_MODEL_TITLE = ["cell line", "cell lines", "knockdown", "knockout", "overexpression", "inhibitor",
                "mice", "mouse", "organoid", "organoids", "xenograft", "xenografts",
                "induced pluripotent", "perturb seq", "co culture"]
_RNA_HINTS = ["rna seq", "scrna", "snrna", "transcriptom", "single cell", "single nucleus", "smart seq"]
_ASSAY_REASON = {
    "spatial_transcriptomics": "spatial",
    "proteomics": "proteomics",
    "epigenomics": "epigenomics",
    "microbiome": "microbiome",
    "other": "other",
}


def _normal(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def _mentions(text: str, terms: list[str]) -> bool:
    blob = " " + _normal(text) + " "
    return any(_normal(term) and " " + _normal(term) + " " in blob for term in terms)


def relevance(spec: ResearchSpec, summary: dict[str, Any], rules: list[dict]) -> dict:
    title = str(summary.get("title") or "")
    summary_text = str(summary.get("summary") or "")
    text = title + " " + summary_text
    terms = [t.term for t in lexicon_terms("disease", spec.disease)] + spec.disease
    score = 0
    reasons = []
    if _mentions(title, terms):
        score += 60
        reasons.append("disease_in_title")
    elif _mentions(text, terms):
        score += 30
        reasons.append("disease_in_summary")
    elif spec.disease:
        score -= 30
        reasons.append("no_direct_disease_term")
    tissue_terms = [t.term for t in lexicon_terms("tissue", spec.tissues)] + spec.tissues
    if spec.tissues:
        if _mentions(title, tissue_terms) and _mentions(title, _MATERIAL):
            score += 40
            reasons.append("target_tissue_sample_evidence")
        elif _mentions(title, tissue_terms):
            score += 25
            reasons.append("target_tissue_in_title")
        elif _mentions(summary_text, tissue_terms):
            score += 8
            reasons.append("target_tissue_in_summary")
        off = []
        for seed in spec.tissues:
            off.extend(_OFF_TARGET.get(seed.casefold(), _OFF_TARGET.get(seed, [])))
        if spec.tissue_required and _mentions(title, off) and not _mentions(title, tissue_terms):
            score -= 40
            reasons.append("conflicting_tissue_in_title")
    patient_terms = ["patient", "patients", "donors", "postmortem", "biopsies", "biopsy", "clinical cohort"]
    if _mentions(text, patient_terms):
        score += 15
        reasons.append("patient_or_donor_context")
    if spec.required_groups and _control_cue(text):
        score += 20
        reasons.append("control_context")
    if _mentions(title, patient_terms):
        score += 20
        reasons.append("patient_or_donor_in_title")
    if spec.required_groups and _control_cue(title):
        score += 20
        reasons.append("control_in_title")
    score += _assay_mismatch_penalty(spec, title, text, summary, reasons)
    source = spec.sample_source or "any"
    models = _mentions(title, _MODEL_TITLE)
    if source == "primary" and models:
        score -= 40
        reasons.append("source_mismatch_model")
    elif source == "primary" and _mentions(title, _MATERIAL):
        score += 20
        reasons.append("primary_source_in_title")
    elif source in {"cell_line", "organoid", "xenograft"} and _mentions(title, [source.replace("_", " "), "cell line", "organoid", "xenograft", "pdx"]):
        score += 15
        reasons.append("requested_model_source")
    elif source in {"any", "primary"} and models:
        score -= 25
        reasons.append("model_or_intervention_context")
    hard_ids = {c.criterion_id for c in spec.inclusion_criteria if c.priority == "hard"}
    by_id = {j.get("criterion_id"): j for j in rules}
    for cid in hard_ids:
        item = by_id.get(cid)
        if item and item.get("verdict") == "pass" and not item.get("clue_only"):
            score += 8
            reasons.append("hard_supported")
            if cid in {"tissue", "sample_source"}:
                score += 12
                reasons.append("hard_material_supported")
        elif spec.tissue_required and cid == "tissue" and item and item.get("verdict") == "fail":
            score -= 40
            reasons.append("hard_tissue_fail")
    return {"score": score, "reasons": reasons}


def _control_cue(text: str) -> bool:
    if _mentions(text, ["healthy", "normal controls", "non diabetic", "matched controls", "uninfected", "controls"]):
        return True
    blob = " " + _normal(text) + " "
    return " control " in blob and " quality control " not in blob


def _assay_mismatch_penalty(
    spec: ResearchSpec,
    title: str,
    text: str,
    summary: dict[str, Any],
    reasons: list[str],
) -> int:
    if not spec.assay_types:
        return 0
    delta = 0
    call = infer_study_assay(summary)
    if assay_relation(list(spec.assay_types), call) == "contradict":
        off = next((kind for kind in call.kinds if kind in _ASSAY_REASON), call.kind or "other")
        label = _ASSAY_REASON.get(off, off)
        reasons.append(f"off_assay_{label}")
        delta -= 50
    if spec.assay_methods and assay_method_relation(list(spec.assay_methods), call.methods) == "contradict":
        reasons.append("off_assay_method")
        delta -= 50
    if not any(assay in RNA_KINDS for assay in spec.assay_types):
        return delta
    rna_in_title = _mentions(title, _RNA_HINTS)
    rna_in_text = _mentions(text, _RNA_HINTS)
    gdstype = str(summary.get("gdstype") or "")
    folded = gdstype.casefold()
    if "reanalysis" in folded and not rna_in_title:
        delta -= 25
        reasons.append("third_party_reanalysis")
    if folded.strip() == "other" and not rna_in_text:
        delta -= 20
        reasons.append("gdstype_other")
    return delta


def _title_terms(summary: dict[str, Any]) -> set[str]:
    stop = {"the", "of", "and", "in", "a", "an", "on", "with", "by", "for", "to", "rna", "seq"}
    return {t for t in _normal(str(summary.get("title") or "")).split() if t not in stop and len(t) > 2}


def select_deep_targets(rows, summaries: dict[str, dict], limit: int) -> list[str]:
    """Prefer distinct, relevant studies; diversity cannot displace much stronger hits."""
    if limit <= 0:
        return []
    candidates = sorted(
        (r for r in rows if r.verification_status != "rule_excluded"),
        key=lambda r: (-load(r.first_assess_json, {}).get("selection", {}).get("score", 0), r.gse),
    )
    if not candidates:
        return []
    best = load(candidates[0].first_assess_json, {}).get("selection", {}).get("score", 0)
    margin = 25
    near = [
        r
        for r in candidates
        if load(r.first_assess_json, {}).get("selection", {}).get("score", 0) >= best - margin
    ]
    chosen = []
    chosen_terms = []
    for row in near:
        terms = _title_terms(summaries.get(row.gse, {}))
        similar = any(len(terms & other) / max(1, len(terms | other)) >= 0.5 for other in chosen_terms)
        if similar:
            continue
        chosen.append(row)
        chosen_terms.append(terms)
        if len(chosen) >= limit:
            break
    if len(chosen) < limit:
        rest = [r for r in near if r not in chosen]
        rest.sort(key=lambda r: (-load(r.first_assess_json, {}).get("selection", {}).get("score", 0), r.gse))
        for row in rest:
            chosen.append(row)
            if len(chosen) >= limit:
                break
    if len(chosen) < limit:
        rest = [r for r in candidates if r not in chosen]
        rest.sort(key=lambda r: (-load(r.first_assess_json, {}).get("selection", {}).get("score", 0), r.gse))
        for row in rest:
            chosen.append(row)
            if len(chosen) >= limit:
                break
    return [r.gse for r in chosen[:limit]]
