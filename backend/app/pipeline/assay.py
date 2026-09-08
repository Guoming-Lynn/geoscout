from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

AssayKind = Literal[
    "scrna_seq",
    "snrna_seq",
    "bulk_rna_seq",
    "rna_seq_generic",
    "spatial_transcriptomics",
    "proteomics",
    "epigenomics",
    "microbiome",
    "other",
]
RNA_KINDS = {"scrna_seq", "snrna_seq", "bulk_rna_seq", "rna_seq_generic"}
FINE_RNA = {"scrna_seq", "snrna_seq", "bulk_rna_seq"}
TYPED_NONRNA = {"spatial_transcriptomics", "proteomics", "epigenomics", "microbiome"}
KIND_ORDER = (
    "spatial_transcriptomics",
    "scrna_seq",
    "snrna_seq",
    "bulk_rna_seq",
    "rna_seq_generic",
    "proteomics",
    "epigenomics",
    "microbiome",
    "other",
)

SCRNA_HINTS = (
    "single-cell",
    "single cell",
    "scrna",
    "sc rna",
    "单细胞",
)
SNRNA_HINTS = (
    "single-nucleus",
    "single nucleus",
    "snrna",
    "sn rna",
    "单核",
)
BULK_HINTS = (
    "bulk rna-seq",
    "bulk rna seq",
    "bulk rnaseq",
    "bulk transcriptome",
    "bulk rna",
)
SPATIAL_HINTS = (
    "visium",
    "xenium",
    "spatial transcriptom",
    "slide-seq",
    "merfish",
    "seqfish",
    "空间转录",
)
PROTEOMICS_HINTS = (
    "mass spectrometry",
    "proteomic",
    "proteomics",
    "lc-ms",
    "蛋白组",
    "protein expression profiling",
)
MICROBIOME_HINTS = (
    "microbiota",
    "microbiome",
    "16s",
    "metagenom",
    "微生物组",
)
EPIGEN_HINTS = (
    "atac-seq",
    "atac seq",
    "chip-seq",
    "chip seq",
    "methylation profiling",
    "methylation",
    "甲基化",
    "bisulfite",
    "hi-c",
    "表观",
)
RNA_STRATEGY = re.compile(r"rna[\s\-]?seq")
EPIGEN_STRATEGY = {
    "atacseq",
    "chipseq",
    "dnaseseq",
    "bisulfiteseq",
    "methylseq",
    "chiapet",
    "faireseq",
    "hic",
}
GENOME_STRATEGY = {"dnaseq", "wgs", "wxs"}
EPIGEN_METHODS = ("ATAC-seq", "ChIP-seq", "methylation", "Hi-C", "ChIA-PET")
STRATEGY_TO_METHOD = {
    "atacseq": "ATAC-seq",
    "chipseq": "ChIP-seq",
    "bisulfiteseq": "methylation",
    "methylseq": "methylation",
    "chiapet": "ChIA-PET",
    "hic": "Hi-C",
}
METHOD_SYNONYMS = {
    "ATAC-seq": ["ATAC-seq", "snATAC-seq", "scATAC-seq"],
    "ChIP-seq": ["ChIP-seq"],
    "methylation": ["methylation", "甲基化", "bisulfite", "WGBS", "RRBS"],
    "Hi-C": ["Hi-C"],
    "ChIA-PET": ["ChIA-PET"],
}


@dataclass(frozen=True)
class AssayCall:
    kind: AssayKind | None
    confidence: Literal["explicit", "generic", "none"]
    evidence: str
    source: str
    kinds: tuple[AssayKind, ...] = ()
    methods: tuple[str, ...] = ()


def infer_sample_assay(sample: dict[str, Any], study: dict[str, Any] | None = None) -> AssayCall:
    strategy = str(sample.get("library_strategy") or "").strip()
    normalized_strategy = _normalized_library_strategy(sample)
    if normalized_strategy in EPIGEN_STRATEGY:
        return AssayCall(
            kind="epigenomics",
            confidence="explicit",
            evidence=strategy,
            source="sample",
            kinds=("epigenomics",),
            methods=_sample_methods(sample),
        )
    if normalized_strategy in GENOME_STRATEGY:
        return AssayCall(
            kind="other",
            confidence="explicit",
            evidence=strategy,
            source="sample",
            kinds=("other",),
            methods=_sample_methods(sample),
        )
    sample_blob = _sample_blob(sample)
    sample_call = _from_blob(sample_blob, source="sample")
    sample_call = _with_methods(sample_call, _sample_methods(sample))
    if sample_call.confidence == "explicit" and len(sample_call.kinds) <= 1:
        return sample_call
    if not study:
        return sample_call
    study_call = infer_study_assay(study)
    inherited = _inherit_study_kind(sample_call, study_call)
    chosen = inherited or sample_call
    return _with_methods(chosen, _sample_methods(sample))


def infer_study_assay(study: dict[str, Any] | None) -> AssayCall:
    if not study:
        return AssayCall(kind=None, confidence="none", evidence="", source="study", kinds=())
    row = dict(study)
    gdstype = study.get("gdstype")
    if isinstance(gdstype, (list, tuple)):
        row["gdstype"] = " ".join(str(item) for item in gdstype)
    return _from_blob(_study_blob(row), source="study")


def study_assay_kind(study: dict[str, Any] | None, samples: list[dict[str, Any]] | None = None) -> str:
    kinds = study_assay_kinds(study, samples)
    return kinds[0] if kinds else "unknown"


def study_assay_kinds(study: dict[str, Any] | None, samples: list[dict[str, Any]] | None = None) -> list[str]:
    seen: list[AssayKind] = []
    for kind in infer_study_assay(study).kinds:
        if kind not in seen:
            seen.append(kind)
    for sample in samples or []:
        call = infer_sample_assay(sample, None)
        for kind in call.kinds or ((call.kind,) if call.kind else ()):
            if kind and kind not in seen:
                seen.append(kind)
    ordered = _collapse_kinds(seen)
    return list(ordered) or ["unknown"]


def assay_relation(wanted: list[str], call: AssayCall) -> Literal["ok", "contradict", "insufficient"]:
    if not wanted:
        return "ok"
    kinds = _collapse_kinds(call.kinds or ((call.kind,) if call.kind else ()))
    if not kinds:
        return "insufficient"
    rels = [_kind_relation(wanted, kind, call.confidence) for kind in kinds]
    if "ok" in rels and "contradict" in rels:
        return "insufficient"
    if "ok" in rels:
        return "ok"
    if rels and all(item == "contradict" for item in rels):
        return "contradict"
    return "insufficient"


def _kind_relation(wanted: list[str], kind: AssayKind | None, confidence: str) -> Literal["ok", "contradict", "insufficient"]:
    if not kind:
        return "insufficient"
    if kind == "other" and confidence == "explicit":
        return "contradict"
    if kind in TYPED_NONRNA and confidence == "explicit":
        return "ok" if kind in wanted else "contradict"
    if any(item in TYPED_NONRNA for item in wanted) and kind in RNA_KINDS:
        return "contradict"
    if "rna_seq_generic" in wanted and kind in RNA_KINDS:
        return "ok"
    if kind in wanted and confidence == "explicit":
        return "ok"
    if kind in FINE_RNA and any(item in FINE_RNA for item in wanted) and kind not in wanted:
        return "contradict"
    return "insufficient"


def detect_epigen_methods(blob: str, strategy: str = "") -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()

    def add(method: str) -> None:
        if method and method not in seen:
            seen.add(method)
            found.append(method)

    mapped = STRATEGY_TO_METHOD.get(re.sub(r"[\s_-]+", "", (strategy or "").casefold()))
    if mapped:
        add(mapped)
    lower = (blob or "").lower()
    compact = re.sub(r"[\s_-]+", "", lower)
    if "atacseq" in compact or "snatac" in compact or "scatac" in compact or re.search(r"\batac\b", lower):
        add("ATAC-seq")
    if "chiapet" in compact or "chia-pet" in lower or "chia pet" in lower:
        add("ChIA-PET")
    if "chipseq" in compact or "histone chip" in lower:
        add("ChIP-seq")
    if (
        "bisulfite" in lower
        or "methylseq" in compact
        or "wgbs" in compact
        or "rrbs" in compact
        or "methylation profiling" in lower
        or "甲基化" in (blob or "")
        or re.search(r"\bmethylation\b", lower)
    ):
        add("methylation")
    if re.search(r"\bhi-c\b", lower) or re.search(r"(?<![a-z])hic(?![a-z])", compact):
        add("Hi-C")
    return tuple(found)


def assay_method_relation(wanted: list[str], methods: tuple[str, ...] | list[str]) -> Literal["ok", "contradict", "insufficient"]:
    want = [item for item in wanted if item]
    if not want:
        return "ok"
    have = [item for item in methods if item]
    if any(item in want for item in have):
        extra = [item for item in have if item not in want]
        if extra:
            return "insufficient"
        return "ok"
    if have and all(item in EPIGEN_METHODS and item not in want for item in have):
        return "contradict"
    return "insufficient"


def sample_method_relation(wanted: list[str], sample: dict[str, Any]) -> Literal["ok", "contradict", "insufficient"]:
    """Judge methods from this GSM's strategy and local fields, not shared protocol text."""
    if not wanted:
        return "ok"
    declared = _declared_strategy_method(sample)
    if declared:
        return assay_method_relation(wanted, (declared,))
    if _rna_or_genome_strategy(sample):
        return "contradict"
    return assay_method_relation(wanted, _sample_methods(sample))


def _normalized_library_strategy(sample: dict[str, Any]) -> str:
    return re.sub(r"[\s_-]+", "", str(sample.get("library_strategy") or "").casefold())


def _declared_strategy_method(sample: dict[str, Any]) -> str | None:
    return STRATEGY_TO_METHOD.get(_normalized_library_strategy(sample))


def _rna_or_genome_strategy(sample: dict[str, Any]) -> bool:
    normalized = _normalized_library_strategy(sample)
    if not normalized or normalized in EPIGEN_STRATEGY:
        return False
    if normalized in GENOME_STRATEGY:
        return True
    return normalized.endswith("rnaseq")


def _sample_local_blob(sample: dict[str, Any]) -> str:
    parts = [
        str(sample.get("title") or ""),
        str(sample.get("source_name") or ""),
        str(sample.get("library_strategy") or ""),
        str(sample.get("library_source") or ""),
    ]
    for row in sample.get("characteristics") or []:
        if isinstance(row, dict):
            parts.append(str(row.get("raw") or row.get("value") or ""))
        else:
            parts.append(str(row))
    return " ".join(parts)


def _sample_methods(sample: dict[str, Any]) -> tuple[str, ...]:
    declared = _declared_strategy_method(sample)
    if declared:
        return (declared,)
    if _rna_or_genome_strategy(sample):
        return ()
    return detect_epigen_methods(_sample_local_blob(sample))


def _with_methods(call: AssayCall, methods: tuple[str, ...]) -> AssayCall:
    if call.methods == methods:
        return call
    return AssayCall(
        kind=call.kind,
        confidence=call.confidence,
        evidence=call.evidence,
        source=call.source,
        kinds=call.kinds,
        methods=methods,
    )


def _inherit_study_kind(sample_call: AssayCall, study_call: AssayCall) -> AssayCall | None:
    if study_call.confidence != "explicit":
        return None
    if sample_call.kind not in {None, "rna_seq_generic"} and sample_call.confidence != "none":
        return None
    if "spatial_transcriptomics" in study_call.kinds and len(study_call.kinds) > 1:
        return None
    if sample_call.kind in RNA_KINDS and any(kind in TYPED_NONRNA for kind in study_call.kinds):
        return None
    study_rna = [kind for kind in study_call.kinds if kind in FINE_RNA]
    if len(study_rna) == 1:
        kind = study_rna[0]
        return AssayCall(kind=kind, confidence="explicit", evidence=study_call.evidence, source="study", kinds=(kind,), methods=sample_call.methods)
    if len(study_call.kinds) == 1:
        kind = study_call.kinds[0]
        return AssayCall(kind=kind, confidence="explicit", evidence=study_call.evidence, source="study", kinds=(kind,), methods=sample_call.methods)
    return None


def _sample_blob(sample: dict[str, Any]) -> str:
    parts = [
        str(sample.get("title") or ""),
        str(sample.get("source_name") or ""),
        str(sample.get("library_strategy") or ""),
        str(sample.get("library_source") or ""),
        str(sample.get("protocol") or ""),
    ]
    for row in sample.get("characteristics") or []:
        parts.append(str(row.get("raw") or row.get("value") or ""))
    return " ".join(parts)


def _study_blob(study: dict[str, Any]) -> str:
    return " ".join(
        str(study.get(k) or "")
        for k in ("title", "summary", "gdstype", "overall_design", "protocol")
    )


def _hint_hit(blob: str, hints: tuple[str, ...]) -> str:
    lower = blob.lower()
    return next((hint for hint in hints if hint in lower), "")


def _spatial_hit(lower: str) -> str:
    hit = _hint_hit(lower, SPATIAL_HINTS)
    if hit:
        return hit
    if "spatial" in lower and any(token in lower for token in ("transcriptom", "omics", "resolved")):
        return "spatial"
    return ""


def _order_kinds(kinds: list[AssayKind] | tuple[AssayKind, ...]) -> tuple[AssayKind, ...]:
    rank = {name: idx for idx, name in enumerate(KIND_ORDER)}
    unique: list[AssayKind] = []
    for kind in kinds:
        if kind not in unique:
            unique.append(kind)
    return tuple(sorted(unique, key=lambda item: rank.get(item, 99)))


def _collapse_kinds(kinds: list[AssayKind] | tuple[AssayKind, ...]) -> tuple[AssayKind, ...]:
    collapsed = [kind for kind in kinds]
    if "spatial_transcriptomics" in collapsed or any(kind in FINE_RNA for kind in collapsed):
        collapsed = [kind for kind in collapsed if kind != "rna_seq_generic"]
    return _order_kinds(collapsed)


def _from_blob(blob: str, *, source: str) -> AssayCall:
    hits = _collect_kinds(blob)
    kinds = _collapse_kinds([kind for kind, _evidence, _conf in hits])
    by_kind = {kind: (evidence, conf) for kind, evidence, conf in hits}
    if source == "sample":
        fine = [kind for kind in kinds if kind in FINE_RNA]
        extra = [kind for kind in kinds if kind in TYPED_NONRNA]
        if len(fine) > 1 or (fine and extra):
            return AssayCall(
                kind=None,
                confidence="none",
                evidence="样本级技术描述冲突",
                source=source,
                kinds=kinds,
                methods=detect_epigen_methods(blob),
            )
    if not kinds:
        return AssayCall(kind=None, confidence="none", evidence="", source=source, kinds=(), methods=detect_epigen_methods(blob))
    confs = [by_kind[kind][1] for kind in kinds if kind in by_kind]
    confidence: Literal["explicit", "generic", "none"] = (
        "explicit" if any(item == "explicit" for item in confs) else "generic"
    )
    evidence = "; ".join(by_kind[kind][0] for kind in kinds if kind in by_kind)
    return AssayCall(
        kind=kinds[0],
        confidence=confidence,
        evidence=evidence,
        source=source,
        kinds=kinds,
        methods=detect_epigen_methods(blob),
    )


def _collect_kinds(blob: str) -> list[tuple[AssayKind, str, Literal["explicit", "generic"]]]:
    lower = blob.lower()
    compact = re.sub(r"[\s_-]+", "", lower)
    out: list[tuple[AssayKind, str, Literal["explicit", "generic"]]] = []
    seen: set[AssayKind] = set()

    def add(kind: AssayKind, evidence: str, confidence: Literal["explicit", "generic"] = "explicit") -> None:
        if kind in seen:
            return
        seen.add(kind)
        out.append((kind, evidence, confidence))

    spatial = _spatial_hit(lower)
    if spatial:
        add("spatial_transcriptomics", spatial)
    if "citeseq" in compact:
        add("scrna_seq", "CITE-seq")
    proteomics = _hint_hit(lower, PROTEOMICS_HINTS)
    if proteomics and "citeseq" not in compact:
        add("proteomics", proteomics)
    microbiome = _hint_hit(lower, MICROBIOME_HINTS)
    if microbiome:
        add("microbiome", microbiome)
    epigen = _hint_hit(lower, EPIGEN_HINTS)
    if not epigen and ("genome binding" in lower or "occupancy profiling" in lower or "methylation profiling" in lower):
        epigen = "epigenomics"
    if epigen:
        add("epigenomics", epigen)
    if any(h in lower for h in SNRNA_HINTS):
        add("snrna_seq", "single-nucleus")
    elif any(h in lower for h in SCRNA_HINTS):
        add("scrna_seq", "single-cell")
    if any(h in lower for h in BULK_HINTS):
        add("bulk_rna_seq", "bulk")
    if RNA_STRATEGY.search(lower) and not (seen & FINE_RNA) and "spatial_transcriptomics" not in seen:
        add("rna_seq_generic", "RNA-Seq", "generic")
    return out
