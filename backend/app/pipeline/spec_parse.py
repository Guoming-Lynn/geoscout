from __future__ import annotations

import re

from app.pipeline.assay import EPIGEN_METHODS, detect_epigen_methods
from app.pipeline.lexicon import ASSAY_SYNONYMS, DISEASE_SYNONYMS, ORGANISM_TERMS, TISSUE_SYNONYMS, lexicon_terms
from app.schemas.spec import Criterion, ResearchSpec

UNRESOLVED_DISEASE_PREFIX = "未解析的疾病需求："
CANONICAL_DISEASE_PATTERNS: list[tuple[str, str]] = [
    ("atherosclerosis", r"动脉粥样硬化|atherosclerosis|atheroma"),
    ("Crohn's disease", r"\bcrohn['’]?s?(?:\s+disease)?\b|克罗恩病"),
    ("ulcerative colitis", r"ulcerative colitis|溃疡性结肠炎"),
    ("inflammatory bowel disease", r"inflammatory bowel disease|\bibd\b|炎症性肠病"),
    ("alzheimer disease", r"alzheimer(?:'s|’s)? disease|alzheimer dementia|阿尔茨海默病?"),
    ("breast cancer", r"breast cancer|breast carcinoma|breast neoplasm|breast tumor|乳腺癌"),
    ("type 2 diabetes", r"type 2 diabetes(?: mellitus)?|\bt2d\b|2型糖尿病"),
    ("rheumatoid arthritis", r"rheumatoid arthritis|类风湿关节炎"),
    ("COVID-19", r"covid[- ]?19|sars[- ]cov[- ]2|coronavirus disease 2019"),
    ("multiple sclerosis", r"multiple sclerosis|多发性硬化"),
    ("influenza", r"\binfluenza\b|流行性感冒|流感"),
]
_SKIP_DISEASE_HEAD = frozenset({
    "seq", "rna", "dna", "atac", "chip", "bulk", "single", "cell", "nucleus",
    "spatial", "visium", "xenium", "human", "mouse", "mus", "homo", "sapiens",
    "primary", "patient", "patients", "control", "controls", "healthy",
    "adjacent", "this", "the", "a", "an", "of", "and", "or", "vs", "versus",
    "library", "sample", "samples", "transcriptome", "expression", "profiling",
    "high", "throughput", "sequencing", "rna-seq", "atac-seq", "chip-seq",
    "scrna-seq", "snrna-seq",
})
_GENERIC_ZH_DISEASE = frozenset({
    "疾病", "病症", "病例", "病变", "病灶", "炎症", "癌症", "肿瘤",
    "症状", "临床症状", "表征",
})
_GROUPING_DISEASE = re.compile(
    r"\b(?:disease|diseased|case|lesion)s?\s+(?:vs\.?|versus|and|or)\s+controls?\b"
    r"|病例\s*对照",
    re.I,
)
_LEFTOVER_EN = re.compile(
    r"\b((?:[A-Za-z][\w'-]*\s+){0,4}[A-Za-z][\w'-]*)\s+"
    r"(diseases?|cancers?|carcinomas?|colitis|syndromes?|disorders?|sclerosis)\b",
    re.I,
)
_LEFTOVER_ZH = re.compile(r"([\u4e00-\u9fff]{2,12}(?:综合征|症候群|病|癌|炎|硬化|症|瘤))")
# Anatomy/cell words that collide with disease-like suffixes; never treat as disease.
_ANATOMY_NOT_DISEASE = frozenset({
    "stroma", "stromal", "stoma", "ostomy", "colostomy", "ileostomy",
    "chroma", "chromatin", "soma", "somatic", "diploma", "aroma", "coma",
    "oma", "glycemia", "lipidemia", "基质", "间质", "基质细胞",
})
# Named diseases without disease/cancer/病 suffixes. Morphology alone is not enough.
_UNSUFFIXED_DISEASE_TERMS = (
    "glioma", "glioblastoma", "lymphoma", "melanoma", "sarcoma",
    "leukemia", "leukaemia", "hepatitis", "pneumonia", "asthma",
    "malaria", "carcinoma", "adenoma", "blastoma",
)
_UNSUFFIXED_DISEASE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in sorted(_UNSUFFIXED_DISEASE_TERMS, key=len, reverse=True)) + r")\b",
    re.I,
)

ASSAY_PATTERNS = [
    (r"visium|xenium|slide-seq|merfish|seqfish|spatial transcriptom|空间转录|空间组学", "spatial_transcriptomics"),
    (r"proteomic|proteomics|mass spectrometry|lc-ms|蛋白组", "proteomics"),
    (r"atac-?seq|chip-?seq|snatac|表观组|epigenom|甲基化|\bmethylation\b|bisulfite|hi-c", "epigenomics"),
    (r"microbiome|microbiota|metagenom|\b16s\b|微生物组", "microbiome"),
    (r"snrna|single[- ]nucleus|单核", "snrna_seq"),
    (r"scrna|single[- ]cell|cite-?seq|单细胞", "scrna_seq"),
    (r"\bbulk\b|转录组测序", "bulk_rna_seq"),
]
_NONRNA_ASSAYS = {"spatial_transcriptomics", "proteomics", "epigenomics", "microbiome"}
_PRIMARY_MATERIAL = (
    r"tissue|samples?|biops(?:y|ies)|pbmc|whole blood|peripheral blood|"
    r"plaque|islets?|brain|cortex|hippocampus|"
    r"组织|样本|斑块|胰岛|脑|外周血|全血"
)
_ASKS_PRIMARY = re.compile(
    rf"直接.{{0,16}}(?:患者|病人).{{0,8}}样本|"
    rf"原代.{{0,16}}(?:{_PRIMARY_MATERIAL})|"
    rf"\bprimary\b.{{0,48}}(?:{_PRIMARY_MATERIAL})|"
    rf"directly (?:from|collected from) patients",
    re.I,
)
_SOURCE_NEGATION = re.compile(r"不|无需|排除|\b(?:not|no|exclude|without)\b", re.I)


def _blocked_disease_terms() -> frozenset[str]:
    blocked = {
        "control", "controls", "case", "cases", "lesion", "healthy", "adjacent",
        "bulk", "primary", "lung", "liver", "heart", "kidney", "skin", "spleen",
        "blood", "tissue", "tissues", "sample", "samples", "organ", "organs",
        "对照", "病例", "病变", "病灶", "分组", "肺", "肺组织", "肝脏", "心脏",
        "肾脏", "皮肤", "脾脏", "单细胞", "测序", "转录组", "空间转录组", "蛋白组",
        "人", "人类", "小鼠",
    }
    blocked.update(_ANATOMY_NOT_DISEASE)
    for table in (TISSUE_SYNONYMS, ASSAY_SYNONYMS, ORGANISM_TERMS):
        for key, values in table.items():
            blocked.add(key.casefold())
            blocked.update(item.casefold() for item in values)
    return frozenset(blocked)


_BLOCKED_DISEASE_TERMS = _blocked_disease_terms()


def _span_blocked(span: str) -> bool:
    folded = span.casefold()
    if folded in _BLOCKED_DISEASE_TERMS:
        return True
    tokens = [part for part in re.split(r"\s+", folded) if part]
    return len(tokens) == 1 and tokens[0] in _BLOCKED_DISEASE_TERMS


def request_asks_primary(text: str) -> bool:
    """True when the user asked for primary/ex vivo material, not patient-derived alone."""
    folded = text or ""
    if _SOURCE_NEGATION.search(folded):
        return False
    return bool(_ASKS_PRIMARY.search(folded))


def request_supports_tissues(text: str, tissues: list[str]) -> bool:
    """True when named tissues are actually in the user request, not inferred from disease."""
    blob = (text or "").casefold()
    if not tissues or not blob:
        return False
    for seed in tissues:
        terms = [seed] + [item.term for item in lexicon_terms("tissue", [seed])]
        if any(term and term.casefold() in blob for term in terms):
            return True
    return False


def request_supports_disease(text: str, diseases: list[str]) -> bool:
    """True when named diseases actually appear in the user request."""
    blob = (text or "").casefold()
    if not diseases or not blob:
        return False
    for seed in diseases:
        terms = [seed, *[item.term for item in lexicon_terms("disease", [seed])]]
        if any(term and term.casefold() in blob for term in terms):
            return True
    return False


def canonical_disease_name(name: str) -> str | None:
    folded = (name or "").casefold()
    if not folded:
        return None
    for key, synonyms in DISEASE_SYNONYMS.items():
        if folded == key.casefold() or any(folded == item.casefold() for item in synonyms):
            return key
    return None


def disease_parse_incomplete(spec: ResearchSpec) -> bool:
    return any(str(item).startswith(UNRESOLVED_DISEASE_PREFIX) for item in spec.unresolved_questions)


def extract_canonical_diseases(text: str) -> list[str]:
    lower = (text or "").lower()
    out: list[str] = []
    for name, pattern in CANONICAL_DISEASE_PATTERNS:
        if re.search(pattern, lower) and name not in out:
            out.append(name)
    return out


def _has_disease(diseases: list[str], name: str) -> bool:
    want = (canonical_disease_name(name) or name).casefold()
    for item in diseases:
        got = (canonical_disease_name(item) or item).casefold()
        if got == want or item.casefold() == name.casefold():
            return True
    return False


def _trim_en_disease_span(span: str) -> str:
    tokens = [part for part in re.split(r"\s+", span.strip()) if part]
    while tokens and tokens[0].casefold().strip(".,;:'\"") in _SKIP_DISEASE_HEAD:
        tokens.pop(0)
    if len(tokens) < 2:
        return ""
    return " ".join(tokens)


def _trim_zh_disease_span(span: str) -> str:
    text = span.strip()
    for prefix in ("人类", "小鼠", "原代"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if text.startswith("人") and len(text) > 1 and text[1] != "工":
        text = text[1:]
    return text.strip()


def extract_unstructured_disease_spans(text: str, already: list[str]) -> list[str]:
    work = _GROUPING_DISEASE.sub(lambda match: " " * len(match.group(0)), text or "")
    for _name, pattern in CANONICAL_DISEASE_PATTERNS:
        work = re.sub(pattern, lambda match: " " * len(match.group(0)), work, flags=re.I)
    for seed in already:
        work = re.sub(re.escape(seed), lambda match: " " * len(match.group(0)), work, flags=re.I)
        for item in lexicon_terms("disease", [seed]):
            if item.term:
                work = re.sub(re.escape(item.term), lambda match: " " * len(match.group(0)), work, flags=re.I)
    spans: list[str] = []
    seen: set[str] = set()

    def add(span: str) -> None:
        cleaned = re.sub(r"\s+", " ", span).strip(" .,;:/-")
        if not cleaned or _span_blocked(cleaned) or cleaned.endswith("症状"):
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        spans.append(cleaned)

    for match in _LEFTOVER_EN.finditer(work):
        trimmed = _trim_en_disease_span(match.group(0))
        if trimmed:
            add(trimmed)
    for match in _UNSUFFIXED_DISEASE_RE.finditer(work):
        add(match.group(0))
    for match in _LEFTOVER_ZH.finditer(work):
        trimmed = _trim_zh_disease_span(match.group(1))
        if trimmed and trimmed not in _GENERIC_ZH_DISEASE:
            add(trimmed)
    return spans


def apply_parse_completeness(spec: ResearchSpec) -> ResearchSpec:
    """Keep explicit disease demands that the structured parse missed."""
    text = spec.original_request or ""
    diseases = list(spec.disease or [])
    questions = list(spec.unresolved_questions or [])
    for name in extract_canonical_diseases(text):
        if not _has_disease(diseases, name):
            diseases.append(name)
    for span in extract_unstructured_disease_spans(text, diseases):
        canon = canonical_disease_name(span)
        if canon:
            if not _has_disease(diseases, canon):
                diseases.append(canon)
            continue
        if not _has_disease(diseases, span):
            diseases.append(span)
        note = f"{UNRESOLVED_DISEASE_PREFIX}{span}"
        if note not in questions:
            questions.append(note)
    spec.disease = list(dict.fromkeys(diseases))
    spec.unresolved_questions = questions
    return spec


def _merge_supported_diseases(existing: list, extra: object, request: str) -> list:
    out = [item for item in (existing or []) if isinstance(item, str) and item.strip()]
    if not isinstance(extra, list):
        return out
    for item in extra:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name or _has_disease(out, name):
            continue
        if request_supports_disease(request, [name]):
            out.append(name)
    return out


def _merge_supported_methods(existing: list, extra: object, request: str) -> list[str]:
    allowed = set(EPIGEN_METHODS)
    out = [item for item in (existing or []) if isinstance(item, str) and item in allowed]
    if not isinstance(extra, list):
        return out
    supported = set(detect_epigen_methods(request))
    for item in extra:
        if not isinstance(item, str) or item not in allowed or item in out:
            continue
        if item in supported:
            out.append(item)
    return out


def heuristic_parse(text: str) -> ResearchSpec:
    """Deterministic parse that never invents unspecified constraints."""
    spec = ResearchSpec(original_request=text)
    lower = text.lower()
    if request_asks_primary(text):
        spec.sample_source = "primary"

    if re.search(r"小鼠|mouse|mus musculus", lower):
        spec.organisms.append("Mus musculus")
    if re.search(r"人|人类|human|homo sapiens", lower):
        spec.organisms.append("Homo sapiens")
    spec.organisms = list(dict.fromkeys(spec.organisms))

    for pattern, assay in ASSAY_PATTERNS:
        if re.search(pattern, lower) and assay not in spec.assay_types:
            if assay == "bulk_rna_seq" and any(
                x in spec.assay_types for x in ("scrna_seq", "snrna_seq", *_NONRNA_ASSAYS)
            ):
                continue
            if assay in {"scrna_seq", "snrna_seq", "bulk_rna_seq"} and any(x in spec.assay_types for x in _NONRNA_ASSAYS):
                continue
            spec.assay_types.append(assay)  # type: ignore[arg-type]

    spec.assay_methods = [item for item in detect_epigen_methods(text) if item in EPIGEN_METHODS]

    if re.search(r"颈动脉|carotid", lower):
        spec.tissues.append("carotid")
    if re.search(r"主动脉|aorta|aortic", lower):
        spec.tissues.append("artery")
    if re.search(r"斑块|plaque", lower):
        spec.tissues.append("plaque")
    if re.search(r"肠组织|肠道组织|intestinal tissue|colon tissue|\bcolon\b|intestin", lower):
        spec.tissues.append("intestine")
    if re.search(r"脑组织|brain tissue|\bbrain\b", lower):
        spec.tissues.append("brain")
    if re.search(r"乳腺|乳房|\bbreast\b", lower):
        spec.tissues.append("breast")
    spec.tissues = list(dict.fromkeys(spec.tissues))
    if spec.tissues and request_supports_tissues(text, spec.tissues):
        spec.tissue_required = True

    apply_parse_completeness(spec)
    if not spec.assay_types and re.search(r"rna[- ]?seq|rna sequencing", lower):
        spec.assay_types.append("rna_seq_generic")

    if (spec.disease or re.search(r"病变|病例|lesion|case|disease", lower)) and re.search(r"对照|control|healthy|adjacent", lower):
        case_name = "lesion" if re.search(r"病变|病灶|\blesion\b", lower) else "case"
        spec.required_groups = [case_name, "control"]

    donor = re.search(r"(?:每组|each group|per group)[^\d]{0,8}(\d+)", lower)
    if donor:
        spec.minimum_donors_per_group = int(donor.group(1))
    else:
        donor2 = re.search(r"(?:至少|at least)[^\d]{0,8}(\d+)[^\d]{0,6}(?:donor|供体|人|例)", lower)
        if donor2:
            spec.minimum_donors_per_group = int(donor2.group(1))
            spec.unresolved_questions.append("最少供体数是按每组还是总计，原文未写明。")

    if re.search(r"年龄|age", lower):
        spec.preferred_metadata.append("age")
    if re.search(r"性别|sex|gender", lower):
        spec.preferred_metadata.append("sex")
    if re.search(r"处理后矩阵|processed matrix|h5ad|count matrix", lower):
        spec.processed_matrix_requirement = "preferred"
        if re.search(r"必须|必须有|required", lower):
            spec.processed_matrix_requirement = "required"

    _fill_criteria(spec)
    return spec


def _fill_criteria(spec: ResearchSpec) -> None:
    items: list[Criterion] = []
    if spec.organisms:
        items.append(
            Criterion(
                criterion_id="organism",
                field="organism",
                description="物种必须匹配",
                user_text=" / ".join(spec.organisms),
                priority="hard",
                value=spec.organisms,
            )
        )
    if spec.assay_types:
        items.append(
            Criterion(
                criterion_id="assay",
                field="assay",
                description="实验技术必须匹配",
                user_text=" / ".join(spec.assay_types),
                priority="hard",
                value=spec.assay_types,
            )
        )
    if spec.assay_methods:
        items.append(
            Criterion(
                criterion_id="assay_method",
                field="assay_method",
                description="具体实验方法必须匹配，不能仅凭表观组学大类通过",
                user_text=" / ".join(spec.assay_methods),
                priority="hard",
                value=spec.assay_methods,
            )
        )
    if spec.disease:
        items.append(
            Criterion(
                criterion_id="disease",
                field="disease",
                description="疾病相关",
                user_text=" / ".join(spec.disease),
                priority="hard",
                value=spec.disease,
            )
        )
    if spec.tissues:
        items.append(
            Criterion(
                criterion_id="tissue",
                field="tissue",
                description="组织相关；样本描述中可能才出现",
                user_text=" / ".join(spec.tissues),
                priority="hard" if spec.tissue_required else "soft",
                value=spec.tissues,
            )
        )
    if spec.sample_source != "any":
        items.append(Criterion(criterion_id="sample_source", field="sample_source", description="样本来源必须匹配", user_text=spec.sample_source, value=spec.sample_source))
    if spec.required_groups:
        items.append(
            Criterion(
                criterion_id="groups",
                field="groups",
                description="需要的实验分组",
                user_text=" / ".join(spec.required_groups),
                priority="hard",
                value=spec.required_groups,
            )
        )
    if spec.minimum_donors_per_group:
        items.append(
            Criterion(
                criterion_id="donors_per_group",
                field="donors",
                description="每组最少独立供体",
                user_text=str(spec.minimum_donors_per_group),
                priority="hard",
                value=spec.minimum_donors_per_group,
            )
        )
    for field in spec.preferred_metadata:
        items.append(
            Criterion(
                criterion_id=f"meta_{field}",
                field=field,
                description=f"最好包含 {field}；GEO 未写不等于数据没有",
                user_text=field,
                priority="soft",
                value=field,
            )
        )
    if spec.processed_matrix_requirement != "none":
        items.append(
            Criterion(
                criterion_id="processed_matrix",
                field="processed_matrix",
                description="处理后矩阵",
                user_text=spec.processed_matrix_requirement,
                priority="hard" if spec.processed_matrix_requirement == "required" else "soft",
                value=spec.processed_matrix_requirement,
            )
        )
    spec.inclusion_criteria = items


def merge_model_parse(base: ResearchSpec, payload: dict) -> ResearchSpec:
    data = base.model_dump()
    if not isinstance(payload, dict):
        payload = {}
    request = str(data.get("original_request") or "")
    data["disease"] = _merge_supported_diseases(data.get("disease") or [], payload.get("disease"), request)
    data["assay_methods"] = _merge_supported_methods(data.get("assay_methods") or [], payload.get("assay_methods"), request)
    for key in (
        "tissues",
        "organisms",
        "assay_types",
        "required_groups",
        "required_metadata",
        "preferred_metadata",
        "unresolved_questions",
    ):
        extra = payload.get(key)
        if key in {"tissues", "organisms", "assay_types", "required_groups"} and data.get(key):
            continue
        if isinstance(extra, list):
            merged = list(data.get(key) or [])
            for item in extra:
                if item not in merged:
                    merged.append(item)
            data[key] = merged
    if payload.get("minimum_donors_per_group") and not data.get("minimum_donors_per_group"):
        data["minimum_donors_per_group"] = payload["minimum_donors_per_group"]
    if (data.get("sample_source") or "any") == "any" and payload.get("sample_source") == "primary":
        if request_asks_primary(request):
            data["sample_source"] = "primary"
    if payload.get("processed_matrix_requirement"):
        data["processed_matrix_requirement"] = payload["processed_matrix_requirement"]
    if payload.get("tissue_required") is True and (data.get("tissues") or payload.get("tissues")):
        data["tissue_required"] = True
    tissues = list(data.get("tissues") or [])
    if tissues and request_supports_tissues(request, tissues):
        data["tissue_required"] = True
    spec = ResearchSpec.model_validate(data)
    apply_parse_completeness(spec)
    _fill_criteria(spec)
    return spec
