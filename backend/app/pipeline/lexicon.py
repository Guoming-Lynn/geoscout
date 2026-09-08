from __future__ import annotations

from app.schemas.spec import TermEntry

DISEASE_SYNONYMS: dict[str, list[str]] = {
    "atherosclerosis": ["atherosclerosis", "atherosclerotic", "atheroma"],
    "coronary artery disease": ["coronary artery disease", "CAD", "ischemic heart disease"],
    "carotid": ["carotid", "carotid artery", "carotid plaque"],
    "alzheimer disease": ["Alzheimer disease", "Alzheimer's disease", "Alzheimer dementia", "阿尔茨海默病"],
    "breast cancer": ["breast cancer", "breast carcinoma", "breast neoplasm", "breast tumor", "乳腺癌"],
    "type 2 diabetes": ["type 2 diabetes", "type 2 diabetes mellitus", "T2D", "2型糖尿病"],
    "rheumatoid arthritis": ["rheumatoid arthritis", "类风湿关节炎"],
    "COVID-19": ["COVID-19", "SARS-CoV-2 infection", "coronavirus disease 2019"],
    "inflammatory bowel disease": [
        "inflammatory bowel disease",
        "IBD",
        "炎症性肠病",
    ],
    "Crohn's disease": [
        "Crohn's disease",
        "Crohn disease",
        "Crohns disease",
        "克罗恩病",
    ],
    "ulcerative colitis": [
        "ulcerative colitis",
        "溃疡性结肠炎",
    ],
    "influenza": ["influenza", "流感", "流行性感冒"],
    "multiple sclerosis": ["multiple sclerosis", "多发性硬化"],
}

TISSUE_SYNONYMS: dict[str, list[str]] = {
    "artery": ["artery", "arterial", "aorta", "aortic"],
    "plaque": ["plaque", "atheroma", "lesion"],
    "brain": ["brain", "cerebral", "cortex", "isocortex", "hippocampus", "dentate gyrus", "pons", "temporal gyrus", "脑组织"],
    "blood": ["blood", "pbmc", "peripheral blood"],
    "pancreatic islets": ["pancreatic islets", "pancreatic islet", "islets"],
    "pbmc": ["pbmc", "peripheral blood mononuclear cells"],
    "intestine": [
        "intestine",
        "intestinal",
        "colon",
        "colonic",
        "ileum",
        "ileal",
        "gut",
        "bowel",
        "intestinal mucosa",
        "colon mucosa",
        "肠组织",
        "肠道组织",
    ],
    "colon": ["colon", "colonic", "intestine", "intestinal", "gut"],
    "breast": ["breast", "mammary", "mammary gland", "乳腺", "乳房"],
}

ASSAY_SYNONYMS: dict[str, list[str]] = {
    "rna_seq_generic": ["RNA-seq", "RNA sequencing"],
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
    "spatial_transcriptomics": [
        "spatial transcriptomics",
        "Visium",
        "Xenium",
        "spatially resolved transcriptomics",
    ],
    "proteomics": ["proteomics", "proteomic", "mass spectrometry"],
    "epigenomics": ["ATAC-seq", "ChIP-seq", "epigenomics", "chromatin accessibility"],
    "microbiome": ["microbiome", "microbiota", "16S", "metagenome"],
}

ORGANISM_TERMS: dict[str, list[str]] = {
    "Homo sapiens": ["Homo sapiens", "human"],
    "Mus musculus": ["Mus musculus", "mouse"],
}

ASSAY_GTYP = {
    "rna_seq_generic": "Expression profiling by high throughput sequencing",
    "scrna_seq": "Expression profiling by high throughput sequencing",
    "snrna_seq": "Expression profiling by high throughput sequencing",
    "bulk_rna_seq": "Expression profiling by high throughput sequencing",
    "spatial_transcriptomics": "Expression profiling by high throughput sequencing",
    "epigenomics": "Genome binding/occupancy profiling by high throughput sequencing",
}

# 10x is a supplementary platform signal, never used as the sole assay proof.
ASSAY_SUPPLEMENTAL = {
    "scrna_seq": ["10x Genomics", "10X"],
    "spatial_transcriptomics": ["Visium", "Xenium"],
    "epigenomics": ["ATAC-seq", "ChIP-seq"],
    "proteomics": ["mass spectrometry", "proteomics"],
    "microbiome": ["16S", "microbiome"],
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
