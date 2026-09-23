"""Regressions from the 2026-09-23 DeepSeek Flash three-topic run."""

from app.connectors.geo_ftp import classify_suppl_names
from app.evidence.soft_parser import count_biosamples, count_independent_donors
from app.pipeline.assay import assay_relation, infer_sample_assay, infer_study_assay, mixed_omics_note
from app.pipeline.assessment import check_model_assessment, fit_samples, judge_user_payload
from app.pipeline.ranking import relevance
from app.pipeline.screening import rule_judgements
from app.pipeline.source import source_kind, tissue_matches
from app.pipeline.spec_parse import heuristic_parse

EV = [{"evidence_id": "ev_ok", "text": "Homo sapiens RNA-seq type 2 diabetes T2D healthy control"}]


def test_flash_topics_keep_named_tissues():
    ad = heuristic_parse("human primary Alzheimer disease brain RNA-seq with disease and control")
    assert ad.tissues == ["brain"]
    assert ad.tissue_required is True
    t2d = heuristic_parse("human primary type 2 diabetes islet RNA-seq with disease and control")
    assert t2d.tissues == ["pancreatic islets"]
    assert t2d.tissue_required is True
    assert t2d.sample_source == "primary"
    ra = heuristic_parse("human primary rheumatoid arthritis PBMC RNA-seq with disease and control")
    assert ra.tissues == ["pbmc"]
    assert ra.tissue_required is True
    assert heuristic_parse("human atherosclerosis scRNA-seq lesion vs control").tissues == []
    assert heuristic_parse("human bulk RNA-seq of influenza").tissues == []


def test_islet_request_ranks_heart_below_islet():
    spec = heuristic_parse("human primary type 2 diabetes islet RNA-seq with disease and control")
    heart = relevance(spec, {"title": "Type 2 diabetes heart RNA-seq"}, [])
    islet = relevance(spec, {"title": "Type 2 diabetes pancreatic islet RNA-seq"}, [])
    assert islet["score"] > heart["score"]
    assert "conflicting_tissue_in_title" in heart["reasons"]


def test_mirna_seq_is_not_generic_rna():
    assert heuristic_parse("human brain miRNA-seq").assay_types == ["small_rna"]
    assert heuristic_parse("human brain RNA-seq").assay_types == ["rna_seq_generic"]
    call = infer_sample_assay({"library_strategy": "miRNA-Seq", "title": "temporal lobe"})
    assert call.kind == "small_rna"
    assert assay_relation(["rna_seq_generic"], call) == "contradict"
    study = infer_study_assay({"title": "Temporal lobe miRNA-seq in Alzheimer disease"})
    assert study.kind == "small_rna"
    spec = heuristic_parse("human Alzheimer disease brain RNA-seq")
    assay = next(j for j in rule_judgements(spec, {"title": study.evidence, "gdstype": ""}) if j.criterion_id == "assay")
    judged = next(
        j
        for j in rule_judgements(spec, {"title": "Temporal lobe miRNA-seq in Alzheimer disease", "gdstype": ""})
        if j.criterion_id == "assay"
    )
    assert judged.verdict == "fail"
    assert assay.verdict == "fail"


def test_unlabeled_group_gsm_is_dropped_without_invalidating():
    spec = heuristic_parse("human type 2 diabetes RNA-seq disease and control")
    samples = [
        {
            "gsm": "GSM1",
            "organism": "Homo sapiens",
            "library_strategy": "RNA-Seq",
            "title": "T2D donor",
            "characteristics": [{"key": "disease state", "value": "T2D", "raw": "disease state: T2D"}],
        },
        {
            "gsm": "GSM2",
            "organism": "Homo sapiens",
            "library_strategy": "RNA-Seq",
            "title": "control donor",
            "characteristics": [{"key": "disease state", "value": "healthy control", "raw": "disease state: healthy control"}],
        },
        {
            "gsm": "GSM3",
            "organism": "Homo sapiens",
            "library_strategy": "RNA-Seq",
            "title": "unlabeled donor",
            "characteristics": [{"key": "tissue", "value": "islet", "raw": "tissue: islet"}],
        },
    ]
    raw = {
        "judgements": [
            {"criterion_id": cid, "verdict": "pass", "evidence_ids": ["ev_ok"], "quote": quote, "reason": "ok", "qualifying_gsms": gsms}
            for cid, quote, gsms in (
                ("organism", "Homo sapiens", ["GSM1", "GSM2", "GSM3"]),
                ("assay", "RNA-seq", ["GSM1", "GSM2", "GSM3"]),
                ("disease", "type 2 diabetes", []),
                ("groups", "T2D", ["GSM1", "GSM2", "GSM3"]),
            )
        ]
    }
    checked = check_model_assessment(spec, raw, EV, samples=samples)
    assert not checked.invalid
    groups = next(j for j in checked.judgements if j.criterion_id == "groups")
    assert "GSM3" not in (groups.qualifying_gsms or [])
    assert set(groups.qualifying_gsms or []) == {"GSM1", "GSM2"}


def test_repeated_protocol_is_sent_once():
    proto = "Cells were prepared once. " + ("ACGT" * 40)
    rows = []
    for gsm, label in (("GSM1", "T2D"), ("GSM2", "healthy control")):
        rows.append(
            {
                "gsm": gsm,
                "organism": "Homo sapiens",
                "library_strategy": "RNA-Seq",
                "protocol": proto,
                "characteristics": [{"key": "disease state", "value": label, "raw": f"disease state: {label}"}],
            }
        )
    spec = heuristic_parse("human type 2 diabetes RNA-seq disease and control")
    packed, coverage = fit_samples(rows, spec=spec)
    assert packed[0]["protocol_id"] == "P1"
    assert "protocol" not in packed[0]
    assert coverage["shared_protocols"]["P1"] == proto
    payload = judge_user_payload(spec, "GSE1", summary={}, evidence=[], samples=rows)
    assert payload["shared_protocols"]["P1"] == proto
    assert "shared_protocols" not in payload["sample_coverage"]
    assert proto not in str(payload["samples"])


def test_blood_source_and_pbmc_extract_protocol():
    assert source_kind({"source_name": "Blood", "characteristics": [{"key": "tissue", "value": "Blood", "raw": "tissue: Blood"}]}) == "primary"
    sample = {
        "gsm": "GSM1",
        "source_name": "Blood",
        "characteristics": [{"key": "tissue", "value": "Blood", "raw": "tissue: Blood"}],
        "protocol_fields": {"extract_protocol": "Peripheral blood mononuclear cells (PBMCs) were isolated."},
    }
    assert tissue_matches(sample, ["pbmc"])
    assert not tissue_matches(
        {"source_name": "frontal cortex", "characteristics": [{"key": "tissue", "value": "cortex", "raw": "tissue: cortex"}],
         "protocol_fields": {"extract_protocol": "PBMCs were used as a comparison."}},
        ["pbmc"],
    )


def test_biosample_count_is_not_a_donor_count():
    samples = [
        {"donor_key": None, "relations": ["BioSample: https://www.ncbi.nlm.nih.gov/biosample/SAMN1"]},
        {"donor_key": None, "relations": ["BioSample: https://www.ncbi.nlm.nih.gov/biosample/SAMN1"]},
        {"donor_key": None, "relations": ["BioSample: https://www.ncbi.nlm.nih.gov/biosample/SAMN2"]},
    ]
    assert count_independent_donors(samples) is None
    assert count_biosamples(samples) == 2
    assert count_biosamples([{"relations": []}]) is None


def test_suppl_names_are_classified_without_opening_files():
    assert classify_suppl_names(["GSE1_RAW.tar"])["matrix_availability"] == "raw_archive"
    counts = classify_suppl_names(["GSE1_counts.csv.gz"])
    assert counts["matrix_availability"] == "filename_only"
    assert counts["processed_data"] == "probable"
    assert classify_suppl_names(["<a href='GSE1.h5ad'>GSE1.h5ad</a>"])["processed_data"] == "probable"
    assert classify_suppl_names(["GSE1_family.soft.gz"])["matrix_availability"] == "not_listed"


def test_mixed_omics_series_is_flagged():
    note = mixed_omics_note(
        {"title": "Mass spectrometry proteomics of Alzheimer cortex"},
        [{"library_strategy": "RNA-Seq", "title": "frontal cortex RNA-seq", "library_source": "transcriptomic"}],
    )
    assert "proteomics" in note
    assert mixed_omics_note({"title": "RNA-seq of human PBMC"}, [{"library_strategy": "RNA-Seq"}]) == ""
