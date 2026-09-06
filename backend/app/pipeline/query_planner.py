from __future__ import annotations

import re

from app.pipeline.lexicon import ASSAY_GTYP, ASSAY_SUPPLEMENTAL, lexicon_terms
from app.schemas.spec import PlannedQuery, ResearchSpec, TermEntry


def or_group(terms: list[str]) -> str:
    clean = []
    seen = set()
    for term in terms:
        t = term.strip()
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        if re.search(r"\s", t) or any(ch in t for ch in "()[]"):
            clean.append(f'"{t}"')
        else:
            clean.append(t)
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    return "(" + " OR ".join(clean) + ")"


def and_join(parts: list[str]) -> str:
    return " AND ".join(p for p in parts if p)


def collect_terms(spec: ResearchSpec, extra: list[TermEntry] | None = None) -> list[TermEntry]:
    terms: list[TermEntry] = []
    terms.extend(lexicon_terms("disease", spec.disease))
    terms.extend(lexicon_terms("tissue", spec.tissues))
    assay_keys = spec.assay_types or []
    terms.extend(lexicon_terms("assay", assay_keys))
    terms.extend(lexicon_terms("organism", spec.organisms))
    if extra:
        seen = {(t.group, t.term.lower()) for t in terms}
        for item in extra:
            key = (item.group, item.term.lower())
            if key not in seen:
                terms.append(item)
                seen.add(key)
    return terms


def plan_queries(
    spec: ResearchSpec,
    extra: list[TermEntry] | None = None,
    *,
    manual_query: str | None = None,
) -> list[PlannedQuery]:
    if manual_query:
        term = manual_query.strip()
        if '"gse"[ETYP]' not in term and "[ETYP]" not in term:
            term = and_join([term, '"gse"[ETYP]'])
        return [PlannedQuery(term=term, round_no=1, source="user", concept_groups=["manual"])]

    grouped: dict[str, list[str]] = {"disease": [], "tissue": [], "assay": [], "organism": []}
    for item in collect_terms(spec, extra):
        grouped.setdefault(item.group, []).append(item.term)

    organism_filters = [_organism_filter(name) for name in spec.organisms]
    assay_gtyp = None
    if spec.assay_types:
        assay_gtyp = f'"{ASSAY_GTYP[spec.assay_types[0]]}"[GTYP]'

    planned: list[PlannedQuery] = []
    seen: set[str] = set()

    def add(term: str, round_no: int, source: str, groups: list[str]) -> None:
        key = re.sub(r"\s+", " ", term.strip())
        if not key or key.lower() in seen:
            return
        seen.add(key.lower())
        planned.append(PlannedQuery(term=key, round_no=round_no, source=source, concept_groups=groups))

    disease = or_group(grouped["disease"][:8])
    assay = or_group(grouped["assay"][:6])
    tissue = or_group(grouped["tissue"][:6])
    gse = '"gse"[ETYP]'

    round1 = and_join([disease, tissue, assay, *organism_filters, assay_gtyp, gse])
    add(round1, 1, "planner", [g for g in ["disease", "tissue", "assay", "organism"] if (g == "organism") or grouped.get(g) or (g == "tissue" and tissue)])

    if tissue:
        add(and_join([disease, tissue, *organism_filters, gse]), 2, "planner", ["disease", "tissue", "organism"])

    if grouped["disease"]:
        add(and_join([or_group(grouped["disease"]), *organism_filters, gse]), 2, "planner", ["disease", "organism"])

    if spec.assay_types:
        for extra_term in ASSAY_SUPPLEMENTAL.get(spec.assay_types[0], []):
            add(
                and_join([disease, f'"{extra_term}"', *organism_filters, gse]),
                2,
                "planner",
                ["disease", "assay_supplement"],
            )

    return planned


def discovered_queries(spec: ResearchSpec, new_terms: list[str], round_no: int = 3) -> list[PlannedQuery]:
    organism_filters = [_organism_filter(name) for name in spec.organisms]
    gse = '"gse"[ETYP]'
    out: list[PlannedQuery] = []
    for term in new_terms:
        if not _term_relevant(term, spec):
            continue
        q = and_join([f'"{term}"', *organism_filters, gse])
        out.append(PlannedQuery(term=q, round_no=round_no, source="discovered", concept_groups=["discovered"]))
    return out


def _organism_filter(name: str) -> str:
    return f'"{name}"[ORGN]'


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", text) if t.lower() not in {"and", "the", "for"}]


def _term_relevant(term: str, spec: ResearchSpec) -> bool:
    blob = " ".join(
        spec.disease + spec.tissues + spec.organisms + spec.assay_types + spec.original_request.split()
    ).lower()
    t = term.lower()
    if len(t) < 4:
        return False
    return any(part in blob or blob.find(part) >= 0 for part in t.split() if len(part) > 3) or t in blob
