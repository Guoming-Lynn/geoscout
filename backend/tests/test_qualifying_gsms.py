from app.pipeline.assessment import check_model_assessment
from app.pipeline.screening import classify
from app.pipeline.spec_parse import heuristic_parse
from app.schemas.spec import CriterionJudgement

EV = [{"evidence_id": "ev_ok", "text": "taxon: Homo sapiens single-cell RNA sequencing atherosclerosis"}]

SAMPLES = [
    {
        "gsm": "GSM9001",
        "organism": "Homo sapiens",
        "library_strategy": "RNA-Seq",
        "title": "single-cell RNA-seq lesion",
        "characteristics": [{"key": "group", "value": "lesion", "raw": "group: lesion"}],
    },
    {
        "gsm": "GSM9002",
        "organism": "Homo sapiens",
        "library_strategy": "RNA-Seq",
        "title": "single-cell RNA-seq healthy control",
        "characteristics": [{"key": "group", "value": "healthy control", "raw": "group: healthy control"}],
    },
]


def _spec():
    return heuristic_parse("human atherosclerosis scRNA-seq")


def _pass_all(qualifying):
    return {
        "judgements": [
            {
                "criterion_id": "organism",
                "verdict": "pass",
                "evidence_ids": ["ev_ok"],
                "quote": "Homo sapiens",
                "reason": "ok",
                "qualifying_gsms": qualifying,
            },
            {
                "criterion_id": "assay",
                "verdict": "pass",
                "evidence_ids": ["ev_ok"],
                "quote": "single-cell",
                "reason": "ok",
                "qualifying_gsms": qualifying,
            },
            {
                "criterion_id": "disease",
                "verdict": "pass",
                "evidence_ids": ["ev_ok"],
                "quote": "atherosclerosis",
                "reason": "ok",
            },
        ]
    }


def test_invented_gsm_cannot_recommend():
    spec = _spec()
    checked = check_model_assessment(spec, _pass_all(["GSM999999"]), EV, samples=SAMPLES)
    assert checked.invalid
    cat, _ = classify(spec, checked.judgements, verified=True, conflict=False, model_invalid=True)
    assert cat != "recommended"


def test_foreign_gse_gsm_cannot_recommend():
    spec = _spec()
    checked = check_model_assessment(spec, _pass_all(["GSM15787"]), EV, samples=SAMPLES)
    assert checked.invalid
    cat, _ = classify(spec, checked.judgements, verified=True, conflict=False, model_invalid=True)
    assert cat != "recommended"


def test_real_matching_gsm_is_accepted():
    spec = _spec()
    checked = check_model_assessment(spec, _pass_all(["GSM9001"]), EV, samples=SAMPLES)
    assert not checked.invalid
    org = next(j for j in checked.judgements if j.criterion_id == "organism")
    assert org.qualifying_gsms == ["GSM9001"]
    cat, _ = classify(
        spec,
        [
            CriterionJudgement(
                criterion_id="organism",
                verdict="pass",
                evidence_ids=["ev_ok"],
                quote="Homo sapiens",
                qualifying_gsms=["GSM9001"],
                judge_source="verify",
            ),
            CriterionJudgement(
                criterion_id="assay",
                verdict="pass",
                evidence_ids=["ev_ok"],
                quote="single-cell",
                qualifying_gsms=["GSM9001"],
                judge_source="verify",
            ),
            CriterionJudgement(
                criterion_id="disease",
                verdict="pass",
                evidence_ids=["ev_ok"],
                quote="atherosclerosis",
                judge_source="verify",
            ),
        ],
        verified=True,
        conflict=False,
        model_invalid=False,
        depth_complete=True,
        review_complete=True,
    )
    assert cat == "recommended"


def test_gsm_wrong_organism_rejected():
    spec = _spec()
    mouse = [
        {
            "gsm": "GSM9001",
            "organism": "Mus musculus",
            "library_strategy": "RNA-Seq",
            "characteristics": [],
        }
    ]
    checked = check_model_assessment(spec, _pass_all(["GSM9001"]), EV, samples=mouse)
    assert checked.invalid


def test_qualifying_gsms_without_samples_invalid():
    spec = _spec()
    checked = check_model_assessment(spec, _pass_all(["GSM9001"]), EV, samples=[])
    assert checked.invalid
