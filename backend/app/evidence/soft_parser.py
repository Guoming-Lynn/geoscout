from __future__ import annotations

import gzip
import io
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, TextIO

logger = logging.getLogger("geoscout.soft")

ENTITY_RE = re.compile(r"^\^(SERIES|SAMPLE|PLATFORM|DATASET)\s*=\s*(.*)$")
ATTR_RE = re.compile(r"^!(Series|Sample|Platform|Dataset)_(\S+)\s*=\s?(.*)$")
TABLE_BEGIN_RE = re.compile(r"^!(Series|Sample|Platform|Dataset)_table_begin", re.I)
TABLE_END_RE = re.compile(r"^!(Series|Sample|Platform|Dataset)_table_end", re.I)


@dataclass
class SoftEntity:
    kind: str
    accession: str
    fields: dict[str, list[str]] = field(default_factory=dict)

    def get(self, key: str) -> list[str]:
        return self.fields.get(key, [])

    def first(self, key: str) -> str:
        values = self.get(key)
        return values[0] if values else ""


@dataclass
class SoftDocument:
    series: SoftEntity | None = None
    platforms: list[SoftEntity] = field(default_factory=list)
    samples: list[SoftEntity] = field(default_factory=list)
    truncated: bool = False
    truncate_reason: str = ""
    bytes_read: int = 0
    lines_read: int = 0
    tables_skipped: int = 0


class SoftParseError(Exception):
    pass


def parse_soft_text(
    text: str,
    *,
    max_samples: int | None = None,
    max_bytes: int | None = None,
) -> SoftDocument:
    return parse_soft_stream(io.StringIO(text), max_samples=max_samples, max_bytes=max_bytes)


def parse_soft_bytes(
    data: bytes,
    *,
    max_samples: int | None = None,
    max_bytes: int | None = None,
) -> SoftDocument:
    if data[:2] == b"\x1f\x8b":
        raw = gzip.decompress(data)
    else:
        raw = data
    text = raw.decode("utf-8", errors="replace")
    return parse_soft_text(text, max_samples=max_samples, max_bytes=max_bytes)


def parse_soft_stream(
    stream: TextIO,
    *,
    max_samples: int | None = None,
    max_bytes: int | None = None,
) -> SoftDocument:
    doc = SoftDocument()
    current: SoftEntity | None = None
    in_table = False
    bytes_read = 0
    for line in stream:
        bytes_read += len(line.encode("utf-8", errors="replace"))
        doc.lines_read += 1
        doc.bytes_read = bytes_read
        if max_bytes is not None and bytes_read > max_bytes:
            doc.truncated = True
            doc.truncate_reason = "max_bytes"
            break
        stripped = line.rstrip("\r\n")
        if in_table:
            if TABLE_END_RE.match(stripped):
                in_table = False
            continue
        if TABLE_BEGIN_RE.match(stripped):
            in_table = True
            doc.tables_skipped += 1
            continue
        entity_match = ENTITY_RE.match(stripped)
        if entity_match:
            kind, accession = entity_match.group(1).upper(), entity_match.group(2).strip()
            current = SoftEntity(kind=kind, accession=accession)
            if kind == "SERIES":
                doc.series = current
            elif kind == "PLATFORM":
                doc.platforms.append(current)
            elif kind == "SAMPLE":
                if max_samples is not None and len(doc.samples) >= max_samples:
                    doc.truncated = True
                    doc.truncate_reason = "max_samples"
                    current = None
                    continue
                doc.samples.append(current)
            continue
        attr_match = ATTR_RE.match(stripped)
        if attr_match and current is not None:
            key = attr_match.group(2)
            value = attr_match.group(3)
            current.fields.setdefault(key, []).append(value)
    return doc


def characteristics_map(sample: SoftEntity) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw in sample.get("characteristics_ch1") + sample.get("characteristics_ch2"):
        if ":" in raw:
            key, value = raw.split(":", 1)
            rows.append({"key": key.strip().lower(), "value": value.strip(), "raw": raw})
        else:
            rows.append({"key": "", "value": raw.strip(), "raw": raw})
    return rows


def donor_key_from_sample(sample: SoftEntity) -> str | None:
    chars = characteristics_map(sample)
    donor_keys = {
        "donor",
        "donor_id",
        "donor id",
        "patient",
        "patient_id",
        "patient id",
        "individual",
        "individual_id",
        "subject",
        "subject_id",
        "animal_id",
        "mouse_id",
    }
    for row in chars:
        if row["key"] in donor_keys and row["value"]:
            return f"{row['key']}={row['value']}"
    return None


def sample_as_dict(sample: SoftEntity) -> dict[str, Any]:
    return {
        "gsm": sample.accession,
        "title": sample.first("title"),
        "organism": sample.first("organism_ch1") or sample.first("organism_ch2"),
        "source_name": sample.first("source_name_ch1"),
        "library_strategy": sample.first("library_strategy"),
        "library_source": sample.first("library_source"),
        "instrument_model": sample.first("instrument_model"),
        "molecule": sample.first("molecule_ch1"),
        "description": " ".join(sample.get("description")),
        "protocol": _protocol_text(sample),
        "protocol_fields": _protocol_fields(sample),
        "characteristics": characteristics_map(sample),
        "relations": sample.get("relation"),
        "supplementary_file": sample.get("supplementary_file"),
        "donor_key": donor_key_from_sample(sample),
        "geo_accession": sample.first("geo_accession") or sample.accession,
    }


def _protocol_kind(key: str) -> str:
    return re.sub(r"_ch\d+$", "", key.casefold())


def _protocol_fields(sample: SoftEntity) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for key, values in sample.fields.items():
        if "protocol" not in key.casefold():
            continue
        bits = [part.strip() for part in values if part and part.strip()]
        if not bits:
            continue
        grouped.setdefault(_protocol_kind(key), []).extend(bits)
    return {kind: " ".join(parts) for kind, parts in grouped.items()}


def _protocol_text(sample: SoftEntity) -> str:
    return " ".join(text for text in _protocol_fields(sample).values() if text)


def series_as_dict(doc: SoftDocument) -> dict[str, Any]:
    series = doc.series
    if series is None:
        return {"truncated": doc.truncated, "truncate_reason": doc.truncate_reason, "samples": []}
    return {
        "gse": series.accession or series.first("geo_accession"),
        "title": series.first("title"),
        "summary": " ".join(series.get("summary")),
        "overall_design": " ".join(series.get("overall_design")),
        "type": series.get("type"),
        "sample_taxid": series.get("sample_taxid"),
        "platform_id": series.get("platform_id"),
        "relations": series.get("relation"),
        "supplementary_file": series.get("supplementary_file"),
        "pubmed_id": series.get("pubmed_id"),
        "truncated": doc.truncated,
        "truncate_reason": doc.truncate_reason,
        "tables_skipped": doc.tables_skipped,
        "samples": [sample_as_dict(s) for s in doc.samples],
        "platforms": [p.accession for p in doc.platforms],
    }


def count_independent_donors(samples: Iterable[dict[str, Any]]) -> int | None:
    keys = []
    for sample in samples:
        key = sample.get("donor_key")
        if not key:
            return None
        keys.append(key)
    return len(set(keys)) if keys else None
