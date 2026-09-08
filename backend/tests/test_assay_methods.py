from app.pipeline.assessment import _restrict_to_common_subset, _sample_fits_all_hard
from app.pipeline.assay import assay_method_relation, detect_epigen_methods, infer_sample_assay, infer_study_assay, sample_method_relation
from app.pipeline.query_planner import plan_queries
from app.pipeline.ranking import relevance
from app.pipeline.screening import classify, rule_judgements
from app.pipeline.spec_parse import heuristic_parse, merge_model_parse
from app.schemas.spec import CriterionJudgement


def _method(spec, summary, samples=None):
    return next(j for j in rule_judgements(spec, summary, samples or []) if j.criterion_id == "assay_method")


def test_parse_keeps_epigenomics_class_and_specific_method():
    spec = heuristic_parse("human intestinal tissue ATAC-seq")
    assert spec.assay_types == ["epigenomics"]
    assert spec.assay_methods == ["ATAC-seq"]
    assert any(c.criterion_id == "assay_method" and c.priority == "hard" for c in spec.inclusion_criteria)
    generic = heuristic_parse("human brain epigenomics")
    assert generic.assay_types == ["epigenomics"]
    assert generic.assay_methods == []
    visium = heuristic_parse("人动脉粥样硬化斑块空间转录组")
    assert visium.assay_types == ["spatial_transcriptomics"]
    assert visium.assay_methods == []


def test_model_cannot_clear_or_swap_atac_method():
    base = heuristic_parse("human brain ATAC-seq")
    cleared = merge_model_parse(base, {"assay_methods": []})
    assert cleared.assay_methods == ["ATAC-seq"]
    swapped = merge_model_parse(base, {"assay_methods": ["ChIP-seq"]})
    assert swapped.assay_methods == ["ATAC-seq"]
    invented = merge_model_parse(heuristic_parse("human brain 表观组"), {"assay_methods": ["ATAC-seq"]})
    assert invented.assay_methods == []


def test_chip_title_does_not_satisfy_atac():
    spec = heuristic_parse("human intestinal tissue ATAC-seq")
    chip = {
        "title": "Histone ChIP-seq from transverse colon",
        "gdstype": "Genome binding/occupancy profiling by high throughput sequencing",
    }
    assay = next(j for j in rule_judgements(spec, chip) if j.criterion_id == "assay")
    method = _method(spec, chip)
    assert assay.verdict == "pass"
    assert method.verdict == "fail"
    assert classify(spec, rule_judgements(spec, chip), verified=True, conflict=False, model_invalid=False,
                    depth_complete=False, review_complete=False)[0] == "excluded"


def test_atac_title_passes_method_and_class():
    spec = heuristic_parse("human intestinal tissue ATAC-seq")
    hit = {
        "title": "Colon ATAC-seq of primary intestinal tissue",
        "gdstype": "Genome binding/occupancy profiling by high throughput sequencing",
    }
    assert _method(spec, hit).verdict == "pass"
    ranked = relevance(spec, {
        "title": "Histone ChIP-seq from transverse colon",
        "gdstype": "Genome binding/occupancy profiling by high throughput sequencing",
    }, [])
    assert "off_assay_method" in ranked["reasons"]


def test_methylation_and_hic_are_not_atac():
    spec = heuristic_parse("human brain ATAC-seq")
    methyl = _method(spec, {"title": "WGBS methylation profiling of human cortex"})
    hic = _method(spec, {"title": "Hi-C of human cortex"})
    assert methyl.verdict == "fail"
    assert hic.verdict == "fail"
    dnase = infer_sample_assay({"library_strategy": "DNase-Seq"})
    assert dnase.kind == "epigenomics"
    assert "ATAC-seq" not in dnase.methods
    assert assay_method_relation(["ATAC-seq"], dnase.methods) != "ok"
    assert "hic" not in detect_epigen_methods("HiSeq 4000 RNA-seq")


def test_mixed_study_requires_atac_samples():
    spec = heuristic_parse("human intestinal tissue ATAC-seq")
    study = {"title": "ATAC-seq and ChIP-seq of human colon"}
    mixed = _method(spec, study)
    assert mixed.verdict == "unknown"
    samples = [
        {"gsm": "GSM1", "organism": "Homo sapiens", "title": "colon ATAC", "source_name": "colon tissue",
         "library_strategy": "ATAC-seq"},
        {"gsm": "GSM2", "organism": "Homo sapiens", "title": "colon H3K27ac", "source_name": "colon tissue",
         "library_strategy": "ChIP-Seq"},
    ]
    judged = _method(spec, study, samples)
    assert judged.verdict == "pass"
    assert judged.qualifying_gsms == ["GSM1"]
    assert _sample_fits_all_hard(samples[0], spec, study)
    assert not _sample_fits_all_hard(samples[1], spec, study)
    js = [
        CriterionJudgement(
            criterion_id=c.criterion_id,
            verdict="pass",
            support_text="ok",
            qualifying_gsms=["GSM1", "GSM2"] if c.criterion_id in {"assay", "assay_method"} else [],
        )
        for c in spec.inclusion_criteria
    ]
    result = _restrict_to_common_subset(spec, js, samples, study)
    method = next(j for j in result if j.criterion_id == "assay_method")
    assert method.verdict in {"pass", "unknown"}
    if method.verdict == "pass":
        assert method.qualifying_gsms == ["GSM1"]


def test_chip_only_samples_fail_atac():
    spec = heuristic_parse("human intestinal tissue ATAC-seq")
    samples = [
        {"gsm": "GSM1", "title": "H3K4me3", "library_strategy": "ChIP-Seq"},
        {"gsm": "GSM2", "title": "H3K27ac", "library_strategy": "ChIP-Seq"},
    ]
    judged = _method(spec, {"title": "Histone ChIP-seq from transverse colon"}, samples)
    assert judged.verdict == "fail"


def test_atac_queries_do_not_search_chip():
    planned = " ".join(item.term for item in plan_queries(heuristic_parse("human intestinal tissue ATAC-seq"))).casefold()
    assert "atac-seq" in planned
    assert "chip-seq" not in planned
    call = infer_study_assay({"title": "Histone ChIP-seq from transverse colon"})
    assert call.methods == ("ChIP-seq",)
    assert infer_sample_assay({"library_strategy": "ATAC-seq"}).methods == ("ATAC-seq",)


def test_replay_last_trial_tech_medium_titles():
    spec = heuristic_parse("human intestinal tissue ATAC-seq")
    rows = [
        ("GSE307633", "scATACseq of sorted stromal cell compartment from patients with Crohn's disease", "pass"),
        ("GSE282442", "Epigenetic Memory of Intestinal Epithelial Cells in Inflammatory Bowel Disease [ATAC-seq]", "pass"),
        ("GSE319550", "Chromatin accessibility in human colonic fibroblasts", "unknown"),
        ("GSE332645", "Histone ChIP-seq from transverse colon (ENCSR208QRN)", "fail"),
    ]
    for gse, title, verdict in rows:
        judged = _method(spec, {"title": title})
        assert judged.verdict == verdict, (gse, judged.verdict, judged.reason)


def test_snatac_counts_as_atac_method():
    spec = heuristic_parse("human cortex snATAC-seq")
    assert spec.assay_methods == ["ATAC-seq"]
    assert _method(spec, {"title": "snATAC-seq of human cortex"}).verdict == "pass"


def test_rna_seq_sample_is_not_qualified_by_atac_study_title():
    spec = heuristic_parse("human intestinal tissue ATAC-seq")
    study = {"title": "ATAC-seq of human intestine"}
    sample = {
        "gsm": "GSM1",
        "organism": "Homo sapiens",
        "library_strategy": "RNA-Seq",
        "title": "intestine RNA",
        "source_name": "colon tissue",
    }
    call = infer_sample_assay(sample, study)
    assert "ATAC-seq" not in call.methods
    judged = _method(spec, study, [sample])
    assert judged.verdict != "pass"
    assert "GSM1" not in judged.qualifying_gsms
    atac = {
        "gsm": "GSM2",
        "organism": "Homo sapiens",
        "library_strategy": "ATAC-seq",
        "title": "intestine ATAC",
        "source_name": "colon tissue",
    }
    mixed = _method(spec, study, [sample, atac])
    assert mixed.verdict == "pass"
    assert mixed.qualifying_gsms == ["GSM2"]
    assert not _sample_fits_all_hard(sample, spec, study)
    assert _sample_fits_all_hard(atac, spec, study)


def test_methylation_request_keeps_class_and_method():
    zh = heuristic_parse("人脑组织甲基化")
    assert zh.assay_types == ["epigenomics"]
    assert zh.assay_methods == ["methylation"]
    en = heuristic_parse("human brain methylation")
    assert en.assay_types == ["epigenomics"]
    assert en.assay_methods == ["methylation"]
    assert detect_epigen_methods("人脑组织甲基化") == ("methylation",)
    assert detect_epigen_methods("human brain methylation") == ("methylation",)


def test_chiapet_is_not_chipseq():
    call = infer_sample_assay({"library_strategy": "ChIA-PET"})
    assert call.kind == "epigenomics"
    assert call.methods == ("ChIA-PET",)
    assert "ChIP-seq" not in call.methods
    assert assay_method_relation(["ChIP-seq"], call.methods) != "ok"
    spec = heuristic_parse("human brain ChIP-seq")
    judged = _method(spec, {"title": "ChIA-PET of human cortex"})
    assert judged.verdict != "pass"

def test_shared_protocol_does_not_qualify_rna_seq_as_atac():
    spec = heuristic_parse("human intestinal tissue ATAC-seq")
    shared = "RNA-seq and ATAC-seq libraries were prepared in this study."
    rna = {
        "gsm": "GSM1",
        "organism": "Homo sapiens",
        "library_strategy": "RNA-Seq",
        "title": "colon RNA sample",
        "source_name": "colon tissue",
        "protocol": shared,
    }
    assert sample_method_relation(["ATAC-seq"], rna) == "contradict"
    assert "ATAC-seq" not in infer_sample_assay(rna).methods
    judged = _method(spec, {"title": "Colon multiome libraries"}, [rna])
    assert judged.verdict != "pass"
    assert "GSM1" not in judged.qualifying_gsms
    assert not _sample_fits_all_hard(rna, spec, {"title": "Colon multiome libraries"})

    atac = {
        "gsm": "GSM2",
        "organism": "Homo sapiens",
        "library_strategy": "ATAC-seq",
        "title": "colon ATAC sample",
        "source_name": "colon tissue",
        "protocol": shared,
    }
    assert sample_method_relation(["ATAC-seq"], atac) == "ok"
    assert _method(spec, {"title": "Colon multiome libraries"}, [atac]).qualifying_gsms == ["GSM2"]

    title_evidence = {
        "gsm": "GSM3",
        "organism": "Homo sapiens",
        "title": "colon ATAC nuclei",
        "source_name": "colon tissue",
        "protocol": shared,
    }
    assert sample_method_relation(["ATAC-seq"], title_evidence) == "ok"

    protocol_only = {
        "gsm": "GSM4",
        "organism": "Homo sapiens",
        "title": "colon sample",
        "source_name": "colon tissue",
        "protocol": shared,
    }
    assert sample_method_relation(["ATAC-seq"], protocol_only) != "ok"

