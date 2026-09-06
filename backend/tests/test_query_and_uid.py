from app.connectors.ncbi import gse_from_summary, is_gse_record, public_summary
from app.core.urls import geo_bucket
from app.pipeline.query_planner import plan_queries
from app.pipeline.spec_parse import heuristic_parse


def test_empty_disease_does_not_use_assay_tokens_as_disease():
    spec = heuristic_parse("小鼠肝脏 bulk RNA-seq")
    spec.tissues = ["liver"]
    planned = plan_queries(spec)
    round1 = planned[0].term.lower()
    assert "liver" in round1
    assert '"mus musculus"[orgn]' in round1
    assert "bulk or rna-seq" not in round1.split("and")[0]
    spec = heuristic_parse("human atherosclerosis scRNA-seq")
    planned = plan_queries(spec)
    terms = [p.term for p in planned]
    assert len(terms) == len(set(terms))
    assert all('"gse"[ETYP]' in t for t in terms)
    assert any("[ORGN]" in t for t in terms)


def test_uid_is_not_accession():
    gds = {"uid": "562", "accession": "GDS562", "entrytype": "GDS"}
    gse = {"uid": "200001000", "accession": "GSE1000", "entrytype": "GSE", "title": "x", "n_samples": 10, "samples": []}
    assert not is_gse_record(gds)
    assert gse_from_summary(gds) is None
    assert gse_from_summary(gse) == "GSE1000"
    pub = public_summary(gse)
    assert pub["uid"] == "200001000"
    assert pub["accession"] == "GSE1000"


def test_geo_bucket_matches_ncbi_rule():
    assert geo_bucket("GSE1000") == "GSE1nnn"
    assert geo_bucket("GSE333565") == "GSE333nnn"
    assert geo_bucket("GSM575") == "GSMnnn"
