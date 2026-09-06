from __future__ import annotations

from app.schemas.spec import TermEntry

DISEASE_SYNONYMS: dict[str, list[str]] = {
    "atherosclerosis": ["atherosclerosis", "atherosclerotic", "atheroma"],
    "coronary artery disease": ["coronary artery disease", "CAD", "ischemic heart disease"],
    "carotid": ["carotid", "carotid artery", "carotid plaque"],
}

TISSUE_SYNONYMS: dict[str, list[str]] = {
    "artery": ["artery", "arterial", "aorta", "aortic"],
    "plaque": ["plaque", "atheroma", "lesion"],
    "brain": ["brain", "cerebral", "cortex"],
    "blood": ["blood", "pbmc", "peripheral blood"],
}

ASSAY_SYNONYMS: dict[str, list[str]] = {
    "scrna_seq": [
        "single-cell RNA sequencing",
        "single cell RNA-seq",
        "scRNA-seq",
        "single-cell transcriptome",
        "single cell transcriptomics",
    ],
    "snrna_seq": [
        "single-nucleus RNA sequencing",
        "snRNA-seq",
        "single nucleus RNA-seq",
    ],
    "bulk_rna_seq": [
        "RNA-seq",
        "RNA sequencing",
        "transcriptome sequencing",
        "Expression profiling by high throughput sequencing",
    ],
}

ORGANISM_TERMS: dict[str, list[str]] = {
    "Homo sapiens": ["Homo sapiens", "human"],
    "Mus musculus": ["Mus musculus", "mouse"],
}

ASSAY_GTYP = {
    "scrna_seq": "Expression profiling by high throughput sequencing",
    "snrna_seq": "Expression profiling by high throughput sequencing",
    "bulk_rna_seq": "Expression profiling by high throughput sequencing",
}

# 10x is a supplementary platform signal, never used as the sole assay proof.
ASSAY_SUPPLEMENTAL = {
    "scrna_seq": ["10x Genomics", "10X"],
}


def lexicon_terms(group: str, seeds: list[str]) -> list[TermEntry]:
    table = {
        "disease": DISEASE_SYNONYMS,
        "tissue": TISSUE_SYNONYMS,
        "assay": ASSAY_SYNONYMS,
        "organism": ORGANISM_TERMS,
    }[group]
    out: list[TermEntry] = []
    seen: set[str] = set()
    for seed in seeds:
        key = seed.strip()
        synonyms = table.get(key, [])
        if key.lower() in {k.lower() for k in table}:
            match = next(k for k in table if k.lower() == key.lower())
            synonyms = table[match]
        else:
            synonyms = [key] + _fuzzy(table, key)
        for term in synonyms:
            low = term.lower()
            if low in seen:
                continue
            seen.add(low)
            origin = "lexicon" if term.lower() != key.lower() else "user"
            out.append(TermEntry(term=term, group=group, origin=origin))
    return out


def _fuzzy(table: dict[str, list[str]], seed: str) -> list[str]:
    s = seed.lower()
    hits: list[str] = []
    for key, values in table.items():
        bag = [key, *values]
        if any(s in v.lower() or v.lower() in s for v in bag):
            hits.extend(values)
    return hits
