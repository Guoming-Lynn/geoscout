from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.schemas.spec import CriterionJudgement, ResearchSpec
from app.pipeline.lexicon import lexicon_terms

LESION_TOKENS = {
    "lesion",
    "plaque",
    "disease",
    "diseased",
    "atherosclerotic",
    "case",
    "tumor",
    "tumour",
    "hgps",
    "pathology",
    "patient",
    "病变",
    "病例",
}
GROUP_KEYS = {
    "group",
    "condition",
    "disease",
    "disease status",
    "disease_status",
    "disease state",
    "subject status",
    "disease_state",
    "subject_status",
    "clinical status",
    "type",
    "status",
    "treatment",
    "phenotype",
    "diagnosis",
    "sample group",
    "sample_group",
    "genotype",
}
LESION_GROUP_NAMES = {"lesion", "tumor", "tumour", "case", "disease"}
CONTROL_GROUP_NAMES = {"control", "healthy", "normal", "adjacent", "wt", "untreated"}
TREATMENT_GROUP_NAMES = {"treated", "untreated"}

# Short labels are interpreted only in the context of the requested disease.
DISEASE_LABELS = {
    "alzheimer disease": ["AD", "sAD", "LOAD", "EOAD", "SAD", "MAD", "Alzheimer's", "Alzheimers"],
    "type 2 diabetes": ["T2D", "T2DM", "type 2 diabetic", "T2 diabetic", "diabetic"],
    "rheumatoid arthritis": ["RA", "Rheumatiod arthritis", "rhematoid arthritis"],
    "COVID-19": ["COVID", "COVID19", "SARS-CoV-2"],
    "ulcerative colitis": ["UC", "active UC", "inactive UC", "UC active", "UC inactive", "ulcerative colitis"],
    "Crohn's disease": ["CD", "Crohn", "Crohns", "Crohn's"],
    "inflammatory bowel disease": ["IBD"],
    "breast cancer": ["BC", "BRCA", "TNBC", "IDC", "ILC", "HR+", "HER2+", "ER+", "DCIS", "tumor", "tumour"],
}
# Requesting the parent also accepts its child diseases as cases.
DISEASE_CHILDREN = {
    "inflammatory bowel disease": ["ulcerative colitis", "Crohn's disease"],
}
# Exact folded values on a group-like field. Not matched as substrings.
DISEASE_CONTROL_LABELS = {
    "type 2 diabetes": [
        "nd",
        "non diabetic",
        "nondiabetic",
        "non t2d",
        "ngt",
        "normoglycemic",
        "normal glucose tolerance",
    ],
    "ulcerative colitis": ["non ibd", "non-ibd", "nonibd", "non ibd control", "non-ibd control", "hc", "healthy"],
    "Crohn's disease": ["non ibd", "non-ibd", "nonibd", "non ibd control", "non-ibd control", "hc", "healthy"],
    "inflammatory bowel disease": ["non ibd", "non-ibd", "nonibd", "non ibd control", "non-ibd control", "hc", "healthy"],
    "breast cancer": [
        "normal",
        "normal breast",
        "normal tissue",
        "adjacent normal",
        "tumor adjacent normal",
        "reduction mammoplasty",
        "mammoplasty",
        "healthy breast",
    ],
}
_GROUP_KEY_PARTS = ("status", "diagnos", "group", "condition", "disease", "phenotype", "cohort", "state")
_CONTROL_EXACT = {
    "hc",
    "hcs",
    "ctrl",
    "ctrls",
    "con",
    "control",
    "controls",
    "healthy control",
    "healthy controls",
    "hv",
    "healthy volunteer",
    "healthy volunteers",
    "normal control",
    "normal controls",
    "non diabetic",
    "uninfected",
}
_TREATMENT_KEYS = {
    "treatment",
    "stimulation",
    "stimulus",
    "agent",
    "compound",
    "drug",
    "exposure",
    "culture condition",
}
_BASELINE_TREATMENT = {
    "untreated",
    "none",
    "no treatment",
    "baseline",
    "unstimulated",
    "unstim",
    "utx",
    "mock untreated",
    "n a",
    "na",
    "control medium",
    "no strain",
    "unstrained",
    "static",
    "sham",
    "mock",
    "control",
}
_CLINICAL_DRUG = re.compile(
    r"methotrexate|infliximab|adalimumab|vedolizumab|ustekinumab|azathioprine|"
    r"mesalamine|prednisolone|prednisone|steroid|insulin|metformin",
    re.I,
)
_BASELINE_PREFIX = re.compile(r"^(?:no|without|un|non)(?:\s|$)")
_EXVIVO_RE = re.compile(
    r"\blps\b|il[\s\-]?\d+|tnf|ifn|pma|ionomycin|anti[\s\-]?cd3|cd3/cd28|cpg|poly\s*\(?i:c|"
    r"stimulat|inhibitor|agonist|antagonist|sirna|shrna|knock ?down|dmso|vehicle|"
    r"poly\s*\(?\s*i\s*:\s*c\)?|"
    r"\d+\s*(?:ng|ug|µg|μg)/ml|\d+\s*(?:nm|um|µm|μm|mm)\b|\bst\d{3,}\b",
    re.I,
)

_NEGATED_DISEASE = re.compile(
    r"\b(?:no|without|free of)\s+(?:disease|diseased|lesion|pathology)\b"
    r"|\bnon[\s\-]?diseased\b"
    r"|\bnon[\s\-]?disease\b"
    r"|\b(?:disease|lesion|pathology)[\s\-]?free\b"
)
_AMBIGUOUS = re.compile(r"^(?:unknown|n/?a|na|other|unspecified|not specified|none)$")
_CN = re.compile(r"[\u4e00-\u9fff]")


@dataclass
class SampleTraits:
    disease_state: str | None = None
    health: str | None = None
    treatment: str | None = None
    genotype: str | None = None
    adjacent: bool = False
    control_token: bool = False
    conflict: str | None = None
    notes: list[str] = field(default_factory=list)
    raw_fields: list[str] = field(default_factory=list)


def infer_group_label(
    sample: dict[str, Any],
    required_groups: list[str] | None = None,
    control_type: str | None = None,
    spec: ResearchSpec | None = None,
) -> str | None:
    if spec is not None:
        required_groups = required_groups or spec.required_groups
        control_type = control_type or spec.control_type
    traits = parse_sample_traits(sample, spec=spec)
    return map_traits_to_group(traits, required_groups or ["lesion", "control"], control_type)


_GENERIC_CASE_RE = re.compile(
    r"^(?:diseased?|affected)(?:\s*(?:group|sample|tissue)?\s*\d*[a-z]?)$"
)


def parse_sample_traits(sample: dict[str, Any], *, spec: ResearchSpec | None = None) -> SampleTraits:
    acc = SampleTraits()
    texts: list[tuple[str, str]] = []
    if sample.get("group_label") and spec is None:
        texts.append(("group", str(sample["group_label"])))
    for row in sample.get("characteristics") or []:
        key = str(row.get("key") or "")
        value = str(row.get("value") or "")
        raw = str(row.get("raw") or f"{key}: {value}")
        if value:
            texts.append((key.lower(), value))
            acc.raw_fields.append(raw)
        elif key:
            texts.append((key.lower(), key))
    for extra in (sample.get("title"), sample.get("source_name")):
        if extra:
            texts.append(("description", str(extra)))
    if not texts:
        return acc
    terms = [t.term for t in lexicon_terms("disease", spec.disease)] + spec.disease if spec is not None else []
    requested = _requested_disease_names(spec)
    aliases = [alias for name in requested for alias in DISEASE_LABELS.get(name, [])]
    disease_controls = {
        _fold(label)
        for name in requested
        for label in DISEASE_CONTROL_LABELS.get(name, [])
    }
    for key, text in texts:
        folded = _fold(text)
        if not folded or _AMBIGUOUS.match(folded):
            continue
        piece = _traits_from_text(folded)
        grouped = _is_group_key(key)
        if spec is not None and spec.disease:
            if key in {"genotype", "treatment"}:
                piece.pop("health", None)
                piece.pop("control_token", None)
            if grouped and _other_disease_label(folded, requested):
                piece.pop("disease_state", None)
                piece.pop("health", None)
            elif grouped and folded in disease_controls:
                piece.update(control_token=True, disease_state="absent")
            else:
                targets = terms + [a for a in aliases if grouped or len(_fold(a)) >= 5]
                matches = [term for term in targets if _has_word(folded, term)]
                negated = any(re.search(r"\b(?:no|without|non)\s+" + re.escape(_fold(term)) + r"\b", folded) for term in matches)
                if matches:
                    piece["disease_state"] = "absent" if negated else "lesion"
                elif piece.get("disease_state") == "lesion":
                    # "disease" also appears inside other diseases' names ("Parkinson's disease dementia"),
                    # so it only counts as a bare label; role words like lesion/case count anywhere.
                    role = any(_has_word(folded, token) for token in ("lesion", "lesional", "case", "病例", "病变"))
                    if not role and not _GENERIC_CASE_RE.match(folded):
                        piece.pop("disease_state", None)
            if grouped and folded in _CONTROL_EXACT:
                piece.update(control_token=True, disease_state="absent")
        if _is_treatment_key(key):
            kind = _treatment_kind(text)
            if kind:
                piece["treatment"] = kind
            elif folded not in {"treated", "untreated"}:
                acc.notes.append(f"患者治疗字段：{text}")
        _merge_trait_piece(acc, piece, text)
    return acc


def map_traits_to_group(
    traits: SampleTraits,
    required_groups: list[str],
    control_type: str | None = None,
) -> str | None:
    if traits.conflict:
        return None
    groups = [g.lower() for g in (required_groups or ["lesion", "control"])]
    if set(groups) <= TREATMENT_GROUP_NAMES and groups:
        if traits.disease_state != "lesion":
            return None
        label = "treated" if traits.treatment == "ex_vivo" else traits.treatment
        if label in groups:
            return label
        return None
    wants_treatment = any(g in TREATMENT_GROUP_NAMES for g in groups)
    if traits.treatment == "ex_vivo" and not wants_treatment:
        return None
    lesion_name = next((g for g in groups if g in LESION_GROUP_NAMES), None)
    control_name = next((g for g in groups if g in CONTROL_GROUP_NAMES or g == "control"), None)
    if traits.disease_state == "lesion":
        return lesion_name or ("lesion" if "lesion" in groups or not groups else None)
    if _is_control(traits, control_type):
        if "healthy" in groups and control_type == "healthy":
            return "healthy"
        return control_name or "control"
    return None


def _is_control(traits: SampleTraits, control_type: str | None) -> bool:
    ct = (control_type or "unspecified").lower()
    if traits.health == "abnormal":
        return False
    if ct == "healthy":
        if traits.adjacent:
            return False
        return traits.health == "healthy" or traits.disease_state == "absent" or (
            traits.control_token
            and traits.treatment is None
            and traits.genotype is None
            and traits.disease_state != "lesion"
        )
    if ct == "adjacent":
        return bool(traits.adjacent)
    if ct == "untreated":
        return traits.treatment == "untreated" and traits.disease_state != "lesion"
    if ct in {"wt", "wildtype", "wild-type"}:
        return traits.genotype == "wt"
    return (
        (traits.health == "healthy" and not traits.adjacent)
        or traits.adjacent
        or traits.disease_state == "absent"
        or (
            traits.control_token
            and traits.treatment is None
            and traits.genotype is None
            and traits.disease_state != "lesion"
        )
    )


def _traits_from_text(folded: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if _NEGATED_DISEASE.search(folded):
        out["disease_state"] = "absent"
    elif any(_has_word(folded, tok) for tok in LESION_TOKENS):
        out["disease_state"] = "lesion"
    if _has_word(folded, "abnormal") or "异常" in folded:
        out["health"] = "abnormal"
    elif _has_word(folded, "healthy") or "健康" in folded:
        out["health"] = "healthy"
    elif _has_word(folded, "normal") or "正常" in folded:
        out["health"] = "healthy"
    if _has_word(folded, "adjacent") or "邻近" in folded:
        out["adjacent"] = True
    if _has_word(folded, "untreated") or "未处理" in folded:
        out["treatment"] = "untreated"
    elif _has_word(folded, "treated"):
        out["treatment"] = "treated"
    if _has_word(folded, "wt") or _has_word(folded, "wild type") or _has_word(folded, "wildtype"):
        out["genotype"] = "wt"
    if _has_word(folded, "control") or "对照" in folded:
        out["control_token"] = True
    return out


def _merge_trait_piece(acc: SampleTraits, piece: dict[str, Any], raw: str) -> None:
    mapping = {
        "disease_state": "disease_state",
        "health": "health",
        "treatment": "treatment",
        "genotype": "genotype",
    }
    for key, attr in mapping.items():
        value = piece.get(key)
        if not value:
            continue
        current = getattr(acc, attr)
        if current is None:
            setattr(acc, attr, value)
        elif current != value:
            acc.conflict = f"{attr}: {current} vs {value}（{raw}）"
            acc.notes.append(acc.conflict)
    if piece.get("adjacent"):
        acc.adjacent = True
    if piece.get("control_token"):
        acc.control_token = True
    if acc.health == "healthy" and acc.disease_state == "lesion" and not acc.adjacent:
        acc.conflict = acc.conflict or f"健康与病变同时出现（{raw}）"
        acc.notes.append(acc.conflict)


def _is_group_key(key: str) -> bool:
    folded = key.strip().lower()
    return folded in GROUP_KEYS or any(part in folded for part in _GROUP_KEY_PARTS)


def _is_treatment_key(key: str) -> bool:
    folded = key.strip().lower()
    return folded in _TREATMENT_KEYS or "treat" in folded or "stimul" in folded


def _treatment_kind(value: str) -> str | None:
    folded = _fold(value)
    if not folded:
        return None
    if _looks_like_group_value(folded):
        return None
    if folded in _BASELINE_TREATMENT or _BASELINE_PREFIX.match(folded):
        return "untreated"
    if re.search(r"therap|dmard|medication|clinical|prior|history", value, re.I):
        return None
    if _CLINICAL_DRUG.search(value):
        return None
    if _EXVIVO_RE.search(value):
        return "ex_vivo"
    return "ex_vivo"


def _requested_disease_names(spec: ResearchSpec | None) -> list[str]:
    if spec is None:
        return []
    names: list[str] = []
    for disease in spec.disease:
        canon = next((name for name in DISEASE_LABELS if name.casefold() == disease.casefold()), disease)
        names.append(canon)
        names.extend(DISEASE_CHILDREN.get(canon, []))
    return names


def _other_disease_label(folded: str, requested: list[str]) -> bool:
    requested_folded = {name.casefold() for name in requested}
    for name, labels in DISEASE_LABELS.items():
        if name.casefold() in requested_folded:
            continue
        if _has_word(folded, name) or any(
            _has_word(folded, label) and (len(_fold(label)) >= 5 or folded == _fold(label))
            for label in labels
        ):
            return True
    return False


def _looks_like_group_value(folded: str) -> bool:
    if folded in _CONTROL_EXACT or folded in {"healthy", "normal", "case", "lesion"}:
        return True
    for labels in DISEASE_LABELS.values():
        if any(folded == _fold(label) for label in labels):
            return True
    for labels in DISEASE_CONTROL_LABELS.values():
        if folded in {_fold(label) for label in labels}:
            return True
    return False


def _fold(value: str) -> str:
    return re.sub(r"[\s\-_/,]+", " ", value.lower()).strip()


def _has_word(folded: str, token: str) -> bool:
    token = _fold(token)
    if not token:
        return False
    if _CN.search(token):
        return token in folded
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", folded) is not None


def _organism_ok(sample: dict[str, Any], organisms: list[str] | None) -> bool | None:
    if not organisms:
        return True
    wanted = {str(x).lower() for x in organisms if x}
    org = str(sample.get("organism") or "").lower()
    if not org:
        return None
    return any(w in org or org in w for w in wanted)


def donors_per_group(
    samples: list[dict[str, Any]],
    required_groups: list[str],
    *,
    truncated: bool = False,
    organisms: list[str] | None = None,
    control_type: str | None = None,
    spec: ResearchSpec | None = None,
) -> dict[str, Any]:
    """Return counts, completeness flags, and a judgement payload."""
    if spec is not None:
        required_groups = required_groups or spec.required_groups
        control_type = control_type or spec.control_type
        organisms = organisms if organisms is not None else spec.organisms
    groups = [g.lower() for g in (required_groups or ["all"])]
    buckets: dict[str, set[str]] = {g: set() for g in groups}
    missing_donor = False
    missing_group = False
    missing_subset = False
    conflicts = 0
    for sample in samples:
        subset = _organism_ok(sample, organisms)
        if subset is None:
            missing_subset = True
            continue
        if subset is False:
            continue
        donor = sample.get("donor_key")
        if not donor:
            missing_donor = True
            continue
        traits = parse_sample_traits(sample, spec=spec)
        if traits.conflict:
            conflicts += 1
            missing_group = True
            continue
        label = map_traits_to_group(traits, required_groups, control_type)
        if required_groups:
            if not label:
                missing_group = True
                continue
            if label in buckets:
                buckets[label].add(donor)
        else:
            buckets["all"].add(donor)
    counts = {g: len(ids) for g, ids in buckets.items()}
    return {
        "counts": counts,
        "missing_donor": missing_donor,
        "missing_group": missing_group,
        "missing_subset": missing_subset,
        "truncated": truncated,
        "conflicts": conflicts,
        "complete": bool(samples)
        and not missing_donor
        and not missing_group
        and not missing_subset
        and not truncated,
    }


def donor_criterion_judgement(
    criterion,
    samples: list[dict[str, Any]],
    required_groups: list[str],
    *,
    truncated: bool = False,
    organisms: list[str] | None = None,
    control_type: str | None = None,
    spec: ResearchSpec | None = None,
) -> CriterionJudgement:
    need = int(criterion.value or 0)
    if not samples:
        return CriterionJudgement(
            criterion_id=criterion.criterion_id,
            verdict="unknown",
            reason="尚未获取样本级供体字段。",
            judge_source="rule",
        )
    stats = donors_per_group(
        samples,
        required_groups,
        truncated=truncated,
        organisms=organisms,
        control_type=control_type,
        spec=spec,
    )
    counts = stats["counts"]
    detail = "；".join(f"{g}:{n}" for g, n in counts.items())
    if stats["truncated"]:
        return CriterionJudgement(
            criterion_id=criterion.criterion_id,
            verdict="unknown",
            reason=f"样本未完整获取，不能用部分样本证明每组供体不足。已见表 {detail}。",
            judge_source="rule",
        )
    if stats["missing_donor"] or stats["missing_group"] or stats["missing_subset"]:
        missing = []
        if stats["missing_donor"]:
            missing.append("供体 ID")
        if stats["missing_group"]:
            missing.append("实验分组")
        if stats["missing_subset"]:
            missing.append("适用物种子集")
        extra = " 存在分组冲突，已计为未知。" if stats.get("conflicts") else ""
        return CriterionJudgement(
            criterion_id=criterion.criterion_id,
            verdict="unknown",
            reason="缺少" + "、".join(missing) + f"。仅凭总人数足够不能通过每组人数条件。已见表 {detail}。" + extra,
            judge_source="rule",
        )
    short = [g for g, n in counts.items() if n < need]
    if short:
        return CriterionJudgement(
            criterion_id=criterion.criterion_id,
            verdict="fail",
            reason=f"完整分组证据显示不足：{detail}，要求每组至少 {need} 名独立供体。同一供体的重复文库未重复计数。",
            judge_source="rule",
            support_text=detail,
        )
    return CriterionJudgement(
        criterion_id=criterion.criterion_id,
        verdict="pass",
        reason=f"各组独立供体 {detail}，均不少于 {need}。配对设计下同一供体可计入不同组，但不计为两个全局供体。",
        judge_source="rule",
        support_text=detail,
    )
