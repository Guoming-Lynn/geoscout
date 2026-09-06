from app.pipeline.assessment import check_model_assessment
from app.pipeline.screening import classify
from app.pipeline.spec_parse import heuristic_parse
from app.schemas.spec import CriterionJudgement, ResearchSpec

EV = [{"evidence_id": "ev_ok", "text": "taxon: Homo sapiens single-cell RNA sequencing atherosclerosis bulk RNA-seq"}]


def _spec_scrna() -> ResearchSpec:
    return heuristic_parse("human atherosclerosis scRNA-seq")


def _spec_snrna() -> ResearchSpec:
    return heuristic_parse("human atherosclerosis snRNA-seq")


def _pass_ids(qualifying_by_id: dict[str, list[str]]) -> dict:
    return {
        "judgements": [
            {
                "criterion_id": "organism",
                "verdict": "pass",
                "evidence_ids": ["ev_ok"],
                "quote": "Homo sapiens",
                "reason": "ok",
                "qualifying_gsms": qualifying_by_id.get("organism", qualifying_by_id.get("all", [])),
            },
            {
                "criterion_id": "assay",
                "verdict": "pass",
                "evidence_ids": ["ev_ok"],
                "quote": "single-cell",
                "reason": "ok",
                "qualifying_gsms": qualifying_by_id.get("assay", qualifying_by_id.get("all", [])),
            },
            {
                "criterion_id": "disease",
                "verdict": "pass",
                "evidence_ids": ["ev_ok"],
                "quote": "atherosclerosis",
                "reason": "ok",
                "qualifying_gsms": qualifying_by_id.get("disease", qualifying_by_id.get("all", [])),
            },
        ]
    }


def _sample(gsm: str, **kwargs) -> dict:
    row = {
        "gsm": gsm,
        "organism": kwargs.get("organism", "Homo sapiens"),
        "library_strategy": kwargs.get("library_strategy", "RNA-Seq"),
        "title": kwargs.get("title", gsm),
        "source_name": kwargs.get("source_name", ""),
        "characteristics": kwargs.get("characteristics") or [],
        "donor_key": kwargs.get("donor_key", gsm),
    }
    return row


def _classify(spec: ResearchSpec, judgements: list[CriterionJudgement]):
    return classify(
        spec,
        judgements,
        verified=True,
        conflict=False,
        model_invalid=False,
        depth_complete=True,
        review_complete=True,
    )


def test_explicit_bulk_cannot_satisfy_scrna():
    spec = _spec_scrna()
    samples = [_sample("GSMB1", title="bulk RNA-seq of carotid plaque")]
    checked = check_model_assessment(spec, _pass_ids({"all": ["GSMB1"]}), EV, samples=samples)
    assay = next(j for j in checked.judgements if j.criterion_id == "assay")
    assert assay.verdict != "pass"
    cat, _ = _classify(spec, checked.judgements)
    assert cat != "recommended"


def test_rnaseq_only_cannot_auto_pass_scrna_or_sn():
    spec = _spec_scrna()
    samples = [_sample("GSMR1", title="RNA-seq sample 1")]
    checked = check_model_assessment(spec, _pass_ids({"all": ["GSMR1"]}), EV, samples=samples)
    assert not checked.invalid
    assay = next(j for j in checked.judgements if j.criterion_id == "assay")
    assert assay.verdict != "pass"
    sn = check_model_assessment(_spec_snrna(), _pass_ids({"all": ["GSMR1"]}), EV, samples=samples)
    sn_assay = next(j for j in sn.judgements if j.criterion_id == "assay")
    assert sn_assay.verdict != "pass"


def test_explicit_sc_and_sn_match_their_own_assay():
    sc = [_sample("GSMSC1", title="single-cell RNA-seq of plaque")]
    sn = [_sample("GSMSN1", title="single-nucleus RNA-seq of plaque")]
    sc_checked = check_model_assessment(_spec_scrna(), _pass_ids({"all": ["GSMSC1"]}), EV, samples=sc)
    sn_checked = check_model_assessment(_spec_snrna(), _pass_ids({"all": ["GSMSN1"]}), EV, samples=sn)
    assert next(j for j in sc_checked.judgements if j.criterion_id == "assay").verdict == "pass"
    assert next(j for j in sn_checked.judgements if j.criterion_id == "assay").verdict == "pass"
    sc_on_sn = check_model_assessment(_spec_scrna(), _pass_ids({"all": ["GSMSN1"]}), EV, samples=sn)
    assert next(j for j in sc_on_sn.judgements if j.criterion_id == "assay").verdict != "pass"


def test_mixed_study_keeps_only_matching_subset_for_groups():
    spec = heuristic_parse("human atherosclerosis scRNA-seq lesion control")
    samples = [
        _sample(
            "GSMSC1",
            title="single-cell RNA-seq lesion",
            characteristics=[{"key": "group", "value": "lesion", "raw": "group: lesion"}],
            donor_key="D1",
        ),
        _sample(
            "GSMSC2",
            title="single-cell RNA-seq healthy control",
            characteristics=[{"key": "group", "value": "healthy control", "raw": "group: healthy control"}],
            donor_key="D2",
        ),
        _sample(
            "GSMBK1",
            title="bulk RNA-seq lesion",
            characteristics=[{"key": "group", "value": "lesion", "raw": "group: lesion"}],
            donor_key="D3",
        ),
    ]
    raw = _pass_ids({"all": ["GSMSC1", "GSMSC2", "GSMBK1"]})
    if spec.required_groups:
        raw["judgements"].append(
            {
                "criterion_id": "groups",
                "verdict": "pass",
                "evidence_ids": ["ev_ok"],
                "quote": "lesion",
                "reason": "ok",
                "qualifying_gsms": ["GSMSC1", "GSMSC2", "GSMBK1"],
            }
        )
    checked = check_model_assessment(spec, raw, EV, samples=samples)
    assay = next(j for j in checked.judgements if j.criterion_id == "assay")
    assert "GSMBK1" not in (assay.qualifying_gsms or [])
    if assay.verdict == "pass":
        assert set(assay.qualifying_gsms) <= {"GSMSC1", "GSMSC2"}


def test_disjoint_criterion_subsets_cannot_recommend():
    spec = _spec_scrna()
    samples = [
        _sample("GSMH1", title="bulk RNA-seq human", organism="Homo sapiens"),
        _sample("GSMS1", title="single-cell RNA-seq human", organism="Homo sapiens"),
    ]
    raw = _pass_ids({"organism": ["GSMH1"], "assay": ["GSMS1"], "disease": ["GSMH1"]})
    checked = check_model_assessment(spec, raw, EV, samples=samples)
    cat, _ = _classify(spec, checked.judgements)
    assert cat != "recommended"
    assert any(j.verdict != "pass" for j in checked.judgements if j.criterion_id in {"organism", "assay"})
