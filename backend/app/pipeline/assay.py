from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

AssayKind = Literal["scrna_seq", "snrna_seq", "bulk_rna_seq", "rna_seq_generic", "other"]

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
RNA_STRATEGY = re.compile(r"rna[\s\-]?seq")


@dataclass(frozen=True)
class AssayCall:
    kind: AssayKind | None
    confidence: Literal["explicit", "generic", "none"]
    evidence: str
    source: str


def infer_sample_assay(sample: dict[str, Any], study: dict[str, Any] | None = None) -> AssayCall:
    sample_blob = _sample_blob(sample)
    sample_call = _from_blob(sample_blob, source="sample")
    if sample_call.confidence == "explicit":
        return sample_call
    study_blob = _study_blob(study) if study else ""
    mixed = _mixed_tech(study_blob)
    if sample_call.kind == "rna_seq_generic" or sample_call.confidence == "none":
        if study_blob and not mixed:
            study_call = _from_blob(study_blob, source="study")
            if study_call.confidence == "explicit":
                return AssayCall(
                    kind=study_call.kind,
                    confidence="explicit",
                    evidence=study_call.evidence,
                    source="study",
                )
    return sample_call


def assay_relation(wanted: list[str], call: AssayCall) -> Literal["ok", "contradict", "insufficient"]:
    if not wanted:
        return "ok"
    if call.kind and call.kind in wanted and call.confidence == "explicit":
        return "ok"
    fine = {"scrna_seq", "snrna_seq", "bulk_rna_seq"}
    if call.kind in fine and any(w in fine for w in wanted) and call.kind not in wanted:
        return "contradict"
    return "insufficient"


def _sample_blob(sample: dict[str, Any]) -> str:
    parts = [
        str(sample.get("title") or ""),
        str(sample.get("source_name") or ""),
        str(sample.get("library_strategy") or ""),
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


def _from_blob(blob: str, *, source: str) -> AssayCall:
    lower = blob.lower()
    has_sc = any(h in lower for h in SCRNA_HINTS)
    has_sn = any(h in lower for h in SNRNA_HINTS)
    has_bulk = any(h in lower for h in BULK_HINTS)
    hits = [name for name, flag in (("scrna_seq", has_sc), ("snrna_seq", has_sn), ("bulk_rna_seq", has_bulk)) if flag]
    if len(hits) > 1:
        return AssayCall(kind=None, confidence="none", evidence="样本级技术描述冲突", source=source)
    if hits:
        kind = hits[0]
        needle = {"scrna_seq": "single-cell", "snrna_seq": "single-nucleus", "bulk_rna_seq": "bulk"}[kind]
        return AssayCall(kind=kind, confidence="explicit", evidence=needle, source=source)
    if RNA_STRATEGY.search(lower):
        return AssayCall(kind="rna_seq_generic", confidence="generic", evidence="RNA-Seq", source=source)
    return AssayCall(kind=None, confidence="none", evidence="", source=source)


def _mixed_tech(blob: str) -> bool:
    lower = blob.lower()
    flags = [
        any(h in lower for h in SCRNA_HINTS),
        any(h in lower for h in SNRNA_HINTS),
        any(h in lower for h in BULK_HINTS),
    ]
    return sum(1 for x in flags if x) > 1
