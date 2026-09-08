from __future__ import annotations

import json
import re

from app.pipeline.lexicon import lexicon_terms


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
_ORGANOID = re.compile(r"organoid|类器官", re.I)
_CULTURE = re.compile(
    r"\bcultured\b|culture medium|cell[- ]cultures?|"
    r"in[ -]?vitro\s+cultures?|(?:grown|maintained|expanded)\s+in[ -]?vitro|"
    r"培养",
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
    r"primary tissue|whole blood|peripheral blood|\bpbmc\b|\bplasma\b|"
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
    if len(kinds) > 1:
        return None
    if kinds:
        return next(iter(kinds))
    cultured = _unnegated(_CULTURE, material) or _unnegated(_CULTURE, _protocol_for_culture(sample))
    if cultured:
        return None
    if _unnegated(_PRIMARY, material):
        return "primary"
    return None


def tissue_matches(sample: dict, tissues: list[str]) -> bool:
    values = [str(sample.get("source_name") or "")]
    for row in sample.get("characteristics") or []:
        if isinstance(row, dict) and str(row.get("key") or "").casefold() in {"tissue", "organ", "tissue type", "tissue_type"}:
            values.append(str(row.get("value") or row.get("raw") or ""))
    text = " ".join(values).casefold()
    terms = tissues + [t.term for t in lexicon_terms("tissue", tissues)]
    return any(re.search(r"(?<!\w)" + re.escape(t.casefold()) + r"(?!\w)", text) for t in terms if t)


_OFF_TISSUE = {
    "brain": ["blood", "pbmc", "heart", "liver", "intestine", "colon", "gut"],
    "intestine": ["blood", "pbmc", "brain", "liver", "heart", "islet"],
    "colon": ["blood", "pbmc", "brain", "liver", "heart", "islet"],
    "gut": ["blood", "pbmc", "brain", "liver", "heart", "islet"],
    "pancreatic islets": ["blood", "pbmc", "brain", "heart", "liver"],
    "plaque": ["blood", "pbmc"],
    "pbmc": ["brain", "heart", "liver", "intestine", "colon"],
    "blood": ["brain", "heart", "liver", "intestine", "colon"],
}


def sample_tissue_conflicts(sample: dict, tissues: list[str]) -> bool:
    """True when sample material fields name a different organ than the requested tissue."""
    if not tissues or tissue_matches(sample, tissues):
        return False
    values = [str(sample.get("source_name") or "")]
    for row in sample.get("characteristics") or []:
        if isinstance(row, dict) and str(row.get("key") or "").casefold() in {"tissue", "organ", "tissue type", "tissue_type"}:
            values.append(str(row.get("value") or row.get("raw") or ""))
    blob = " ".join(values).casefold()
    if not blob.strip():
        return False
    offs: list[str] = []
    for seed in tissues:
        offs.extend(_OFF_TISSUE.get(seed.casefold(), []))
        offs.extend(_OFF_TISSUE.get(seed, []))
    return any(re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", blob) for term in offs if term)
