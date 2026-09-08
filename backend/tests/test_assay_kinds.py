from app.pipeline.assay import assay_relation, infer_sample_assay, infer_study_assay, study_assay_kinds
from app.pipeline.query_planner import plan_queries
from app.pipeline.ranking import relevance
from app.pipeline.screening import rule_judgements
from app.pipeline.spec_parse import heuristic_parse


def test_heuristic_parse_non_rna_assays():
    assert heuristic_parse("人动脉粥样硬化斑块空间转录组").assay_types == ["spatial_transcriptomics"]
    assert heuristic_parse("Alzheimer proteomics mass spectrometry").assay_types == ["proteomics"]
    assert heuristic_parse("human brain ATAC-seq").assay_types == ["epigenomics"]
    assert heuristic_parse("human brain ATAC-seq").assay_methods == ["ATAC-seq"]
    assert heuristic_parse("atherosclerosis plaque microbiome 16S").assay_types == ["microbiome"]
    assert heuristic_parse("human atherosclerosis scRNA-seq").assay_types == ["scrna_seq"]


def test_infer_study_assay_labels():
    spatial = infer_study_assay({
        "title": "Spatial and single cell transcriptomics of Alzheimer cortex",
        "gdstype": "Expression profiling by high throughput sequencing",
    })
    assert spatial.kind == "spatial_transcriptomics"
    assert spatial.kinds == ("spatial_transcriptomics", "scrna_seq")
    proteomics = infer_study_assay({
        "title": "Mass spectrometry-based proteomic profiling of human postmortem brain",
        "gdstype": "Expression profiling by high throughput sequencing",
    })
    assert proteomics.kind == "proteomics"
    cite = infer_study_assay({"title": "CITE-seq of human PBMCs from atherosclerosis patients"})
    assert cite.kind == "scrna_seq"
    multiome = infer_study_assay({"title": "snRNA-seq and snATAC-seq of human cortex"})
    assert "snrna_seq" in multiome.kinds
    assert "epigenomics" in multiome.kinds
    assert assay_relation(["snrna_seq"], spatial) == "contradict"
    assert assay_relation(["scrna_seq"], spatial) == "insufficient"
    assert assay_relation(["snrna_seq"], proteomics) == "contradict"
    assert assay_relation(["rna_seq_generic"], cite) == "ok"
    assert assay_relation(["snrna_seq"], multiome) == "insufficient"


def test_mixed_assays_are_listed_and_not_excluded():
    study = {
        "title": "scRNA-seq and Visium of atherosclerotic plaque",
        "gdstype": "Expression profiling by high throughput sequencing",
    }
    assert study_assay_kinds(study) == ["spatial_transcriptomics", "scrna_seq"]
    mixed_samples = study_assay_kinds(
        {"title": "Atherosclerosis multiome"},
        [
            {"library_strategy": "RNA-Seq"},
            {"library_strategy": "ATAC-seq"},
        ],
    )
    assert "epigenomics" in mixed_samples
    spec = heuristic_parse("human atherosclerosis plaque scRNA-seq")
    visium_scrna = next(
        j
        for j in rule_judgements(spec, study)
        if j.criterion_id == "assay"
    )
    assert visium_scrna.verdict == "unknown"
    visium_only = next(
        j
        for j in rule_judgements(
            spec,
            {
                "title": "Targeting modulated vascular smooth muscle cells in atherosclerosis [Visium]",
                "gdstype": "Expression profiling by high throughput sequencing",
            },
        )
        if j.criterion_id == "assay"
    )
    assert visium_only.verdict == "fail"


def test_proteomics_and_spatial_fail_rna_screen():
    spec = heuristic_parse("human Alzheimer disease brain snRNA-seq")
    proteomics = next(
        j
        for j in rule_judgements(
            spec,
            {
                "title": "Mass spectrometry-based proteomic profiling of human postmortem brain",
                "gdstype": "Expression profiling by high throughput sequencing",
            },
        )
        if j.criterion_id == "assay"
    )
    assert proteomics.verdict == "fail"
    spec_sc = heuristic_parse("human atherosclerosis plaque scRNA-seq")
    visium = next(
        j
        for j in rule_judgements(
            spec_sc,
            {
                "title": "Targeting modulated vascular smooth muscle cells in atherosclerosis [Visium]",
                "gdstype": "Expression profiling by high throughput sequencing",
            },
        )
        if j.criterion_id == "assay"
    )
    assert visium.verdict == "fail"
    generic = next(
        j
        for j in rule_judgements(
            spec,
            {
                "title": "Postmortem cortex cohort",
                "gdstype": "Expression profiling by high throughput sequencing",
            },
        )
        if j.criterion_id == "assay"
    )
    assert generic.verdict == "unknown"


def test_wanted_proteomics_can_pass_explicit_title():
    spec = heuristic_parse("Alzheimer proteomics")
    hit = next(
        j
        for j in rule_judgements(
            spec,
            {"title": "Mass spectrometry-based proteomic profiling of Alzheimer brain"},
        )
        if j.criterion_id == "assay"
    )
    assert hit.verdict == "pass"


def test_visium_rna_seq_library_is_spatial_not_conflict():
    call = infer_sample_assay({
        "title": "Breast tumor Visium",
        "library_strategy": "RNA-Seq",
        "protocol": "10x Genomics Visium spatial gene expression",
    })
    assert call.kind == "spatial_transcriptomics"
    assert "rna_seq_generic" not in call.kinds
    assert assay_relation(["spatial_transcriptomics"], call) == "ok"
    spec = heuristic_parse("乳腺癌空间转录组")
    assay = next(
        j
        for j in rule_judgements(
            spec,
            {
                "title": "Visium of breast cancer",
                "gdstype": "Expression profiling by high throughput sequencing",
            },
            [{"gsm": "GSM1", "title": "Visium section", "library_strategy": "RNA-Seq",
              "protocol": "10x Visium"}],
        )
        if j.criterion_id == "assay"
    )
    assert assay.verdict == "pass"
    call = infer_sample_assay({"library_strategy": "ATAC-seq"}, {"summary": "RNA-seq and ATAC study"})
    assert call.kind == "epigenomics"
    assert assay_relation(["rna_seq_generic"], call) == "contradict"
    assert assay_relation(["epigenomics"], call) == "ok"


def test_ranking_spatial_with_single_cell_wording():
    spec = heuristic_parse("human Alzheimer disease brain snRNA-seq")
    spatial = relevance(
        spec,
        {
            "title": "Spatial and single cell transcriptomics of Alzheimer cortex",
            "gdstype": "Expression profiling by high throughput sequencing",
        },
        [],
    )
    assert "off_assay_spatial" in spatial["reasons"]


def test_proteomics_query_omits_gtyp_spatial_keeps_gtyp():
    proteomics = plan_queries(heuristic_parse("human Alzheimer proteomics"))
    assert all("[GTYP]" not in q.term for q in proteomics)
    assert any("proteomics" in q.term.lower() or "mass spectrometry" in q.term.lower() for q in proteomics)
    spatial = plan_queries(heuristic_parse("human atherosclerosis 空间转录组"))
    assert any("[GTYP]" in q.term for q in spatial)
    assert any("Visium" in q.term for q in spatial)


def test_mass_spec_series_with_single_cell_rna_is_not_snrna():
    spec = heuristic_parse("阿尔茨海默病脑组织 snRNA-seq")
    study = {
        "title": "Mass spectrometry-based proteomic profiling of human postmortem brain tissues in tauopathies",
        "summary": "Homogenates were analyzed by mass spectrometry. Subsequent single-nucleus profiling is discussed.",
        "gdstype": "Expression profiling by high throughput sequencing",
        "taxon": "Homo sapiens",
    }
    sample = {
        "gsm": "GSM9477523",
        "title": "Frontal cortex (Motor), Control, Cont-1",
        "organism": "Homo sapiens",
        "source_name": "Frontal cortex (Motor)",
        "library_strategy": "RNA-Seq",
        "library_source": "transcriptomic single cell",
        "characteristics": [{"key": "tissue", "value": "Frontal cortex (Motor)", "raw": "tissue: Frontal cortex (Motor)"}],
    }
    call = infer_sample_assay(sample, study)
    assert call.kind != "snrna_seq"
    assert assay_relation(["snrna_seq"], call) != "ok"
    assay = next(j for j in rule_judgements(spec, study, [sample]) if j.criterion_id == "assay")
    assert assay.verdict != "pass"


def test_nuclei_protocol_beats_tenx_single_cell_kit_wording():
    spec = heuristic_parse("阿尔茨海默病脑组织 snRNA-seq")
    study = {
        "title": "Mass spectrometry-based proteomic profiling of human postmortem brain tissues in tauopathies",
        "summary": "Homogenates were analyzed by mass spectrometry. snRNA-seq was performed on the same brains.",
        "gdstype": "Expression profiling by high throughput sequencing",
        "taxon": "Homo sapiens",
    }
    sample = {
        "gsm": "GSM9477523",
        "title": "Frontal cortex (Motor), Control, Cont-1",
        "organism": "Homo sapiens",
        "library_strategy": "RNA-Seq",
        "library_source": "transcriptomic single cell",
        "protocol": (
            "Nuclei were isolated using the Minute Single Nucleus Isolation Kit. "
            "Approximately 10,000 nuclei were processed with the Chromium Next GEM "
            "Single Cell 3' Kit v3.1 for single-nucleus RNA sequencing."
        ),
        "characteristics": [{"key": "tissue", "value": "Frontal cortex (Motor)", "raw": "tissue: Frontal cortex (Motor)"}],
    }
    call = infer_sample_assay(sample, study)
    assert call.kind == "snrna_seq"
    assert call.source == "sample"
    assert "scrna_seq" not in call.kinds
    assert assay_relation(["snrna_seq"], call) == "ok"
    assay = next(j for j in rule_judgements(spec, study, [sample]) if j.criterion_id == "assay")
    assert assay.verdict != "fail"
