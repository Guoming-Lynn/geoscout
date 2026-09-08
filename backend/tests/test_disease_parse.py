from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.connectors.llm import LLMError
from app.core.credentials import store
from app.db.session import init_db
from app.main import app
from app.pipeline.assay import assay_relation, infer_sample_assay
from app.pipeline.engine import parse_spec_with_optional_llm
from app.pipeline.lexicon import lexicon_terms
from app.pipeline.query_planner import plan_queries
from app.pipeline.screening import classify, rule_judgements
from app.pipeline.spec_parse import (
    UNRESOLVED_DISEASE_PREFIX,
    disease_parse_incomplete,
    heuristic_parse,
    merge_model_parse,
)
from app.schemas.spec import CriterionJudgement

IBD_ATAC = "human primary inflammatory bowel disease intestinal tissue ATAC-seq"
TECH_ATAC = "human intestinal tissue ATAC-seq"
RARE_DISEASE = "human primary Niemann-Pick disease brain ATAC-seq"


def _pass_hard(spec):
    return [
        CriterionJudgement(
            criterion_id=item.criterion_id,
            verdict="pass",
            support_text="ok",
            evidence_ids=["e1"],
        )
        for item in spec.inclusion_criteria
        if item.priority == "hard"
    ]


def test_ibd_english_and_chinese_aliases_are_distinct_from_subtypes():
    ibd = heuristic_parse(IBD_ATAC)
    assert ibd.disease == ["inflammatory bowel disease"]
    assert not disease_parse_incomplete(ibd)
    assert "intestine" in ibd.tissues
    assert ibd.tissue_required is True
    terms = {item.term.casefold() for item in lexicon_terms("disease", ibd.disease)}
    assert "ibd" in terms
    assert "炎症性肠病" in terms
    assert "crohn's disease" not in terms
    assert "ulcerative colitis" not in terms
    assert "克罗恩病" not in terms
    assert "溃疡性结肠炎" not in terms
    planned = " ".join(item.term for item in plan_queries(ibd)).casefold()
    assert "inflammatory bowel disease" in planned or "ibd" in planned
    assert "crohn" not in planned

    zh = heuristic_parse("人炎症性肠病肠组织 ATAC-seq")
    assert zh.disease == ["inflammatory bowel disease"]
    assert not disease_parse_incomplete(zh)

    crohn = heuristic_parse("human Crohn's disease intestinal tissue RNA-seq")
    assert crohn.disease == ["Crohn's disease"]
    assert "inflammatory bowel disease" not in crohn.disease
    uc = heuristic_parse("人溃疡性结肠炎肠组织 RNA-seq")
    assert uc.disease == ["ulcerative colitis"]
    assert "inflammatory bowel disease" not in uc.disease
    zh_crohn = heuristic_parse("人克罗恩病肠组织 RNA-seq")
    assert zh_crohn.disease == ["Crohn's disease"]


def test_unlisted_disease_is_kept_and_not_silently_dropped():
    spec = heuristic_parse(RARE_DISEASE)
    assert spec.disease == ["Niemann-Pick disease"]
    assert any(item.startswith(UNRESOLVED_DISEASE_PREFIX) for item in spec.unresolved_questions)
    assert "Niemann-Pick disease" in spec.unresolved_questions[0]
    assert disease_parse_incomplete(spec)
    cat, reason = classify(
        spec,
        _pass_hard(spec),
        verified=True,
        conflict=False,
        model_invalid=False,
    )
    assert cat == "needs_review"
    assert "疾病" in reason
    assert cat != "recommended"


def test_model_empty_or_invented_disease_does_not_erase_or_invent():
    base = heuristic_parse(IBD_ATAC)
    empty = merge_model_parse(base, {"disease": []})
    assert empty.disease == ["inflammatory bowel disease"]
    omitted = merge_model_parse(base, {"tissues": ["liver"]})
    assert omitted.disease == ["inflammatory bowel disease"]
    invented = merge_model_parse(
        base,
        {"disease": ["atherosclerosis", "Crohn's disease", "ulcerative colitis"]},
    )
    assert invented.disease == ["inflammatory bowel disease"]
    assert "atherosclerosis" not in invented.disease
    assert "Crohn's disease" not in invented.disease
    rare = heuristic_parse(RARE_DISEASE)
    kept = merge_model_parse(rare, {"disease": []})
    assert kept.disease == ["Niemann-Pick disease"]
    assert disease_parse_incomplete(kept)


@pytest.mark.asyncio
async def test_llm_failure_keeps_heuristic_disease(monkeypatch):
    monkeypatch.setattr("app.pipeline.engine.settings.llm_mode", "live")
    store.update("disease-parse-session", llm_api_key="test-only-key")
    monkeypatch.setattr(
        "app.pipeline.engine.LLMProvider.complete_json",
        AsyncMock(side_effect=LLMError("forced")),
    )
    spec = await parse_spec_with_optional_llm(IBD_ATAC, "disease-parse-session")
    assert spec.disease == ["inflammatory bowel disease"]
    assert not disease_parse_incomplete(spec)


def test_unsuffixed_disease_names_are_not_silently_dropped():
    flu = heuristic_parse("human influenza lung bulk RNA-seq")
    assert flu.disease == ["influenza"]
    assert not disease_parse_incomplete(flu)
    assert all(item not in flu.disease for item in ("lung", "bulk", "human", "RNA-seq"))
    zh_flu = heuristic_parse("人流感肺组织 RNA-seq")
    assert zh_flu.disease == ["influenza"]
    assert not disease_parse_incomplete(zh_flu)

    zh_ms = heuristic_parse("人多发性硬化脑组织单细胞")
    assert zh_ms.disease == ["multiple sclerosis"]
    assert not disease_parse_incomplete(zh_ms)
    assert "brain" in zh_ms.tissues
    assert zh_ms.tissue_required is True
    assert "scrna_seq" in zh_ms.assay_types
    en_ms = heuristic_parse("human multiple sclerosis brain snRNA-seq")
    assert en_ms.disease == ["multiple sclerosis"]
    assert not disease_parse_incomplete(en_ms)


def test_unlisted_unsuffixed_disease_phrase_is_kept_unresolved():
    spec = heuristic_parse("人系统性硬化肺组织 RNA-seq")
    assert spec.disease == ["系统性硬化"]
    assert any(item.startswith(UNRESOLVED_DISEASE_PREFIX) and "系统性硬化" in item for item in spec.unresolved_questions)
    assert disease_parse_incomplete(spec)
    glioma = heuristic_parse("human glioma brain snRNA-seq")
    assert glioma.disease == ["glioma"]
    assert disease_parse_incomplete(glioma)
    assert "brain" not in glioma.disease
    assert "snRNA-seq" not in glioma.disease


def test_healthy_stroma_search_is_not_disease():
    for text in (
        "human healthy breast stroma RNA-seq",
        "human stroma scRNA-seq",
        "human intestinal stroma ATAC-seq",
        "healthy tissue stroma RNA-seq",
        "human stromal cells RNA-seq",
        "人健康乳腺基质 RNA-seq",
    ):
        spec = heuristic_parse(text)
        assert spec.disease == [], text
        assert not disease_parse_incomplete(spec), text
        assert not any("stroma" in item.casefold() or "基质" in item for item in spec.unresolved_questions), text
    glioma = heuristic_parse("human glioma brain snRNA-seq")
    assert glioma.disease == ["glioma"]
    assert disease_parse_incomplete(glioma)


def test_tech_tissue_search_does_not_require_disease():
    spec = heuristic_parse(TECH_ATAC)
    assert spec.disease == []
    assert not any(item.startswith(UNRESOLVED_DISEASE_PREFIX) for item in spec.unresolved_questions)
    assert not disease_parse_incomplete(spec)
    assert "intestine" in spec.tissues
    assert spec.tissue_required is True
    grouped = heuristic_parse("type 2 diabetes human RNA-seq disease and control")
    assert grouped.disease == ["type 2 diabetes"]
    assert not disease_parse_incomplete(grouped)


@pytest.mark.asyncio
async def test_unresolved_disease_survives_save_run_and_blocks_recommend(monkeypatch):
    await init_db()
    parser = AsyncMock(return_value=heuristic_parse(RARE_DISEASE))
    monkeypatch.setattr("app.api.parse_spec_with_optional_llm", parser)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        created = (await client.post("/api/projects", json={"original_request": RARE_DISEASE})).json()
        parser.assert_not_awaited()
        spec = created["spec"]
        assert spec["disease"] == ["Niemann-Pick disease"]
        assert any(item.startswith(UNRESOLVED_DISEASE_PREFIX) for item in spec["unresolved_questions"])
        saved = (await client.put(f"/api/projects/{created['id']}/spec", json=spec)).json()["spec"]
        assert saved["unresolved_questions"] == spec["unresolved_questions"]
        assert saved["disease"] == spec["disease"]
        run = (await client.post(
            f"/api/projects/{created['id']}/runs",
            json={"mode": "full", "tier": "low"},
        )).json()
        assert run["spec"]["unresolved_questions"] == spec["unresolved_questions"]
        assert run["spec"]["disease"] == spec["disease"]
    from app.schemas.spec import ResearchSpec
    snap = ResearchSpec.model_validate(run["spec"])
    cat, _ = classify(snap, _pass_hard(snap), verified=True, conflict=False, model_invalid=False)
    assert cat == "needs_review"


def test_intestinal_tissue_rejects_pbmc():
    spec = heuristic_parse("人炎症性肠病肠组织 ATAC-seq")
    judgements = rule_judgements(
        spec,
        {
            "title": "PBMC ATAC-seq in IBD",
            "summary": "Intestinal inflammation in IBD; PBMCs were profiled.",
            "taxon": "Homo sapiens",
            "gdstype": "Genome binding/occupancy profiling by high throughput sequencing",
        },
        [{
            "gsm": "GSM1",
            "organism": "Homo sapiens",
            "source_name": "PBMC",
            "library_strategy": "ATAC-seq",
            "characteristics": [{"key": "tissue", "value": "blood", "raw": "tissue: blood"}],
        }],
    )
    assert next(item for item in judgements if item.criterion_id == "tissue").verdict == "fail"
    cat, _ = classify(spec, judgements, verified=True, conflict=False, model_invalid=False)
    assert cat != "recommended"


def test_visium_rna_seq_is_spatial():
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
        item
        for item in rule_judgements(
            spec,
            {
                "title": "Visium of breast cancer",
                "gdstype": "Expression profiling by high throughput sequencing",
            },
            [{"gsm": "GSM1", "title": "Visium section", "library_strategy": "RNA-Seq",
              "protocol": "10x Visium"}],
        )
        if item.criterion_id == "assay"
    )
    assert assay.verdict == "pass"
    assert spec.disease == ["breast cancer"]
    assert spec.tissues == ["breast"]
    assert spec.tissue_required is True
    assert spec.assay_types == ["spatial_transcriptomics"]
    assert spec.organisms == []
    assert not disease_parse_incomplete(spec)
    named = heuristic_parse("人乳腺癌空间转录组")
    assert named.organisms == ["Homo sapiens"]
    assert named.tissues == ["breast"]
    assert named.tissue_required is True
    cleared = merge_model_parse(spec, {"tissues": [], "organisms": [], "tissue_required": False})
    assert cleared.tissues == ["breast"]
    assert cleared.tissue_required is True
