from __future__ import annotations

import json
import re

from app.pipeline.lexicon import TISSUE_SYNONYMS, lexicon_terms


_NAMED_LINES = (
    r"hek[- ]?293(?:t)?|hela|mcf[- ]?7|mda[- ]?mb(?:-\d+)?|a549|k562|jurkat|"
    r"u87(?:mg)?|pc[- ]?3|lncap|thp[- ]?1|hepg2|cho[- ]?k1|cos[- ]?7|vero"
)
_CELL_LINE = re.compile(
    rf"(?:cell[- ]lines?|cell_line|ipsc|i\.?p\.?s\.?c|pluripotent|immortaliz|"
    rf"细胞系|诱导多能|{_NAMED_LINES})",
    re.I,
)
_XENOGRAFT = re.compile(r"xenograft|\bpdx\b|\bcdx\b|异种移植", re.I)
_ORGANOID = re.compile(
    r"organoid|类器官|colonoids?|enteroids?|tumou?roids?|spheroids?|assembloids?|"
    r"organ[- ]on[- ]a?[- ]?chips?|(?:colon|gut|intestine|lung|liver|kidney)[- ]chips?",
    re.I,
)
_CULTURE = re.compile(
    r"\bcultured\b|culture medium|cell[- ]cultures?|"
    r"in[ -]?vitro\s+cultures?|(?:grown|maintained|expanded)\s+in[ -]?vitro|"
    r"培养|\bpassage\s*\d+",
    re.I,
)
_ASSAY_PROTOCOL_KIND = re.compile(
    r"extract|label|hyb|hybridization|scan|library|data.?processing",
    re.I,
)
_REAGENT = re.compile(
    r"fetal bovine serum|\bfbs\b|trypsin|dmem|rpmi|opti[- ]mem|penicillin|streptomycin|"
    r"supplemented with",
    re.I,
)
_PRIMARY = re.compile(
    r"biopsy|biopsies|postmortem|autopsy|surgical resection|blood draw|freshly isolated|"
    r"primary tissue|whole blood|peripheral blood|\bpbmcs?\b|\bblood\b|\bplasma\b|"
    r"(?<!fetal bovine )(?<!bovine )\bserum\b|pancreatic islets?|\bislets?\b|"
    r"dentate gyrus|hippocampus|cortex|isocortex|\bpons\b|brain nuclei|"
    r"synovial (?:tissue|fluid)|原代组织|活检|尸检|手术切除|直接采集|全血|外周血|血浆|血清|胰岛|脑组织|滑膜",
    re.I,
)
_NEGATION = re.compile(
    r"\b(?:no|not|never|without|none)\b.{0,40}$|不(?:使用|含|是).{0,12}$",
    re.I,
)


def _field_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_field_text(item) for item in value)
    if isinstance(value, dict):
        parts = [value.get("value"), value.get("raw"), value.get("key")]
        return " ".join(str(p) for p in parts if p)
    return json.dumps(value, ensure_ascii=False)


def _extract_protocol(sample: dict) -> str:
    fields = sample.get("protocol_fields")
    if isinstance(fields, dict):
        return _field_text(fields.get("extract_protocol"))
    return ""


def _material_text(sample: dict) -> str:
    bits = [_field_text(sample.get("title")), _field_text(sample.get("source_name"))]
    for row in sample.get("characteristics") or []:
        bits.append(_field_text(row))
    return " ".join(b for b in bits if b)


def _unnegated(pattern: re.Pattern[str], text: str) -> bool:
    folded = text or ""
    for match in pattern.finditer(folded):
        prefix = folded[max(0, match.start() - 48) : match.start()]
        if _NEGATION.search(prefix):
            continue
        if _REAGENT.search(folded[max(0, match.start() - 24) : match.end() + 24]) and pattern is _PRIMARY:
            continue
        return True
    return False


def _model_kinds(text: str) -> set[str]:
    found: set[str] = set()
    if text and _unnegated(_XENOGRAFT, text):
        found.add("xenograft")
    if text and _unnegated(_ORGANOID, text):
        found.add("organoid")
    if text and _unnegated(_CELL_LINE, text):
        found.add("cell_line")
    return found


def _is_assay_protocol_kind(key: str) -> bool:
    return bool(_ASSAY_PROTOCOL_KIND.search(str(key or "")))


def _protocol_for_culture(sample: dict) -> str:
    """Growth/treatment text only. Extract, labeling, and library prep are assay steps."""
    fields = sample.get("protocol_fields")
    if isinstance(fields, dict) and any(_field_text(v) for v in fields.values()):
        return " ".join(
            _field_text(value) for key, value in fields.items() if not _is_assay_protocol_kind(str(key))
        )
    return _field_text(sample.get("protocol"))


def _all_protocol_text(sample: dict) -> str:
    fields = sample.get("protocol_fields")
    if isinstance(fields, dict) and fields:
        typed = " ".join(_field_text(value) for value in fields.values())
        if typed.strip():
            return typed
    return _field_text(sample.get("protocol"))


def source_kind(sample: dict) -> str | None:
    """Conservative provenance from sample material fields, not reagent protocols."""
    material = _material_text(sample)
    protocol = _all_protocol_text(sample)
    kinds = _model_kinds(material)
    kinds |= _model_kinds(protocol)
    primary = _unnegated(_PRIMARY, material)
    if kinds and primary:
        return None
    if "organoid" in kinds and kinds <= {"organoid", "cell_line"}:
        return "organoid"
    if len(kinds) > 1:
        return None
    if kinds:
        return next(iter(kinds))
    cultured = _unnegated(_CULTURE, material) or _unnegated(_CULTURE, _protocol_for_culture(sample))
    if cultured:
        return None
    if _unnegated(_PRIMARY, material) or _unnegated(_PRIMARY, _extract_protocol(sample)):
        return "primary"
    if _tissue_material_primary(sample):
        return "primary"
    return None


def _tissue_material_primary(sample: dict) -> bool:
    """A named organ in the material fields is primary when nothing says it was cultured or modeled."""
    blob = _tissue_values(sample, include_extract=False)
    if not blob.strip():
        return False
    material = _material_text(sample)
    protocol = _protocol_for_culture(sample)
    if _model_kinds(material) or _model_kinds(protocol) or _model_kinds(blob):
        return False
    if _unnegated(_CULTURE, material) or _unnegated(_CULTURE, protocol) or _unnegated(_CULTURE, blob):
        return False
    if _blob_has_tissue(blob, list(TISSUE_SYNONYMS)):
        return True
    return bool(re.search(r"tumou?rs?|resection|surgical specimen|mucosa", blob, re.I))


def _tissue_values(sample: dict, *, include_extract: bool) -> str:
    values = [str(sample.get("source_name") or "")]
    for row in sample.get("characteristics") or []:
        key = str(row.get("key") or "").casefold() if isinstance(row, dict) else ""
        if key in {"tissue", "organ", "tissue type", "tissue_type"} or any(
            part in key for part in ("cell type", "cell_type", "celltype", "cell population", "sample type")
        ) or _is_site_key(key):
            values.append(str(row.get("value") or row.get("raw") or ""))
    if include_extract:
        values.append(_extract_protocol(sample))
    return " ".join(values).casefold()


def _blob_has_tissue(blob: str, tissues: list[str]) -> bool:
    terms = tissues + [t.term for t in lexicon_terms("tissue", tissues)]
    return any(re.search(r"(?<!\w)" + re.escape(t.casefold()) + r"(?!\w)", blob) for t in terms if t)


def _material_has_tissue(sample: dict, tissues: list[str]) -> bool:
    return _blob_has_tissue(_tissue_values(sample, include_extract=False), tissues)


_PBMC_SUBSET_RE = re.compile(
    r"\bsorted\b|\bt[\s\-]?cells?\b|\bb[\s\-]?cells?\b|\bnk[\s\-]?cells?\b|"
    r"\btfh\b|\btscm\b|\btregs?\b|\bth\d+\b|\btemra\b|follicular helper|regulatory t|memory t|naive t|"
    r"\bmonocytes?\b|\bmacrophages?\b|\bdendritic\b|\bneutrophils?\b|\bplasmablasts?\b|\bcd(?!45\b)\d+\s*\+?",
    re.I,
)
# "T cell-depleted PBMC" names what was removed, not what was kept.
_DEPLETED_RE = re.compile(
    r"(?:\b[\w+]+\s+)?[\w+]+[\s\-]+depleted\b(?!\s+of\b)|\bdepleted\s+of\s+[\w+]+(?:\s+cells?)?",
    re.I,
)


def _cell_type_values(sample: dict) -> list[str]:
    out: list[str] = []
    for row in sample.get("characteristics") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").casefold()
        if any(part in key for part in ("cell type", "cell_type", "celltype", "cell population", "cell subset")):
            out.append(str(row.get("value") or ""))
    return out


def _pbmc_subset(sample: dict, tissues: list[str]) -> bool:
    """A sorted lymphocyte/myeloid fraction is not a PBMC sample."""
    if not any(t.casefold() in {"pbmc", "pbmcs"} for t in tissues):
        return False
    return any(_PBMC_SUBSET_RE.search(_DEPLETED_RE.sub(" ", value)) for value in _cell_type_values(sample))


def tissue_matches(sample: dict, tissues: list[str]) -> bool:
    """Material fields win. Extract protocol can add a tissue only when those fields name no organ."""
    if _pbmc_subset(sample, tissues):
        return False
    if _material_has_tissue(sample, tissues):
        return True
    if _material_conflicts(sample, tissues):
        return False
    if _material_names_other_organ(sample, tissues):
        return False
    return _blob_has_tissue(_tissue_values(sample, include_extract=True), tissues)


def _material_names_other_organ(sample: dict, tissues: list[str]) -> bool:
    """A named organ outside the requested family blocks the extract-protocol fallback."""
    blob = _tissue_values(sample, include_extract=False)
    family: set[str] = set()
    for seed in tissues:
        family |= TISSUE_FAMILY.get(seed.casefold(), {seed.casefold()})
    outside: list[str] = []
    for key, values in TISSUE_SYNONYMS.items():
        if key.casefold() in family:
            continue
        outside.append(key)
        outside.extend(values)
    return _blob_has_tissue(blob, outside)


_OFF_TISSUE = {
    "brain": ["blood", "pbmc", "heart", "liver", "intestine", "colon", "gut", "synovial", "adipose", "olfactory epithelium", "nasal", "olfactory mucosa"],
    "intestine": ["blood", "pbmc", "brain", "liver", "heart", "islet"],
    "colon": ["blood", "pbmc", "brain", "liver", "heart", "islet", "ileum", "ileal", "terminal ileum", "small intestine", "回肠"],
    "gut": ["blood", "pbmc", "brain", "liver", "heart", "islet"],
    "pancreatic islets": ["blood", "pbmc", "brain", "heart", "liver", "adipose", "synovial", "muscle"],
    "plaque": ["blood", "pbmc"],
    "pbmc": ["brain", "cortex", "hippocampus", "heart", "liver", "intestine", "colon", "synovial", "synovium", "adipose", "muscle", "cd4", "cd8", "cd14", "cd16", "cd19", "cd56", "monocytes", "neutrophils", "whole blood", "plasma", "serum", "platelets"],
    "blood": ["brain", "cortex", "hippocampus", "heart", "liver", "intestine", "colon", "synovial", "adipose"],
    "lung": ["blood", "pbmc", "brain", "liver", "heart", "islet"],
    "liver": ["blood", "pbmc", "brain", "lung", "heart", "islet"],
    "kidney": ["blood", "pbmc", "brain", "liver", "heart", "islet"],
    "synovium": ["blood", "pbmc", "brain", "muscle", "adipose"],
    "skeletal muscle": ["blood", "pbmc", "brain", "synovial", "adipose"],
    "breast": ["blood", "pbmc", "lung", "liver", "brain", "bone", "bone marrow", "lymph node", "pleural effusion", "ascites", "skin", "ovary", "colon"],
}

# Synonym families. A requested member must not treat its relatives as a different organ.
TISSUE_FAMILY = {
    "intestine": {"intestine", "colon", "gut"},
    "colon": {"intestine", "colon", "gut"},
    "gut": {"intestine", "colon", "gut"},
    "blood": {"blood", "pbmc"},
    "pbmc": {"blood", "pbmc"},
    "brain": {"brain"},
}


def _is_site_key(key: str) -> bool:
    folded = key.casefold()
    if re.search(r"\b(?:region|location|site|anatom|biopsy)\b", folded):
        return True
    return "region" in folded or "location" in folded or "anatom" in folded or "biopsy" in folded


def _conflict_terms(tissues: list[str]) -> list[str]:
    offs: list[str] = []
    for seed in tissues:
        listed = _OFF_TISSUE.get(seed.casefold(), _OFF_TISSUE.get(seed))
        if listed:
            offs.extend(listed)
            continue
        family = TISSUE_FAMILY.get(seed.casefold(), {seed.casefold()})
        for key, values in TISSUE_SYNONYMS.items():
            if key.casefold() in family:
                continue
            offs.append(key)
            offs.extend(values)
    return offs


def _material_conflicts(sample: dict, tissues: list[str]) -> bool:
    if tissues and _pbmc_subset(sample, tissues):
        return True
    if not tissues or _material_has_tissue(sample, tissues):
        return False
    blob = _tissue_values(sample, include_extract=False)
    if not blob.strip():
        return False
    offs = _conflict_terms(tissues)
    return any(re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", blob) for term in offs if term)


def sample_tissue_conflicts(sample: dict, tissues: list[str]) -> bool:
    """True when sample material fields name a different organ than the requested tissue."""
    return _material_conflicts(sample, tissues)


_SORTED_EXTRA = re.compile(
    r"\bepithelial\b|\bfibroblasts?\b|\bendothelial\b|\bstromal\b|\bimmune cells?\b|\bleukocytes?\b|\bcd45\s*\+",
    re.I,
)


def sorted_fraction(sample: dict) -> str | None:
    """A purified cell population taken out of a tissue, when the user asked for the tissue itself."""
    values = _cell_type_values(sample)
    source = str(sample.get("source_name") or "")
    if source:
        values.append(source)
    for value in values:
        cleaned = _DEPLETED_RE.sub(" ", value)
        match = _PBMC_SUBSET_RE.search(cleaned) or _SORTED_EXTRA.search(cleaned)
        if match:
            return value.strip()
    return None
