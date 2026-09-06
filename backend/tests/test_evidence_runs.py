import pytest
from sqlalchemy import select

from app.db.models import Assessment, Evidence, Project, Run
from app.db.session import SessionLocal, init_db
from app.evidence.store import add_evidence, evidence_bundle, evidence_id_for, new_id
from app.exporters.excel import read_sheet_maps
from app.exporters.service import create_export
from app.pipeline.repo import dump
from app.schemas.spec import ResearchSpec


async def _two_runs() -> tuple[str, str]:
    await init_db()
    async with SessionLocal() as session:
        if await session.get(Project, "p-ev") is None:
            session.add(Project(id="p-ev", name="evidence", original_request="human scRNA-seq"))
        a = Run(
            id=new_id(),
            project_id="p-ev",
            session_id="s-ev-a",
            mode="manual_query",
            spec_snapshot=dump(ResearchSpec(original_request="human scRNA-seq").model_dump()),
            status="running",
        )
        b = Run(
            id=new_id(),
            project_id="p-ev",
            session_id="s-ev-b",
            mode="manual_query",
            spec_snapshot=dump(ResearchSpec(original_request="human scRNA-seq").model_dump()),
            status="running",
        )
        session.add_all([a, b])
        await session.commit()
        return a.id, b.id


@pytest.mark.asyncio
async def test_two_runs_both_read_same_evidence_without_rewriting_first():
    run_a, run_b = await _two_runs()
    async with SessionLocal() as session:
        first = await add_evidence(
            session,
            run_id=run_a,
            gse="GSEEV-A",
            source_url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSEEV-A",
            field_path="esummary.title",
            text="Osteosarcoma TE85 unique-v3",
        )
        second = await add_evidence(
            session,
            run_id=run_b,
            gse="GSEEV-A",
            source_url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSEEV-A",
            field_path="esummary.title",
            text="Osteosarcoma TE85 unique-v3",
        )
        await session.commit()
        bundle_a = await evidence_bundle(session, run_a, "GSEEV-A")
        bundle_b = await evidence_bundle(session, run_b, "GSEEV-A")
        stored = await session.get(Evidence, first.id)
    assert len(bundle_a) == 1
    assert len(bundle_b) == 1
    assert bundle_a[0]["text"] == "Osteosarcoma TE85 unique-v3"
    assert bundle_b[0]["text"] == "Osteosarcoma TE85 unique-v3"
    assert first.id == evidence_id_for("GSEEV-A", "esummary.title", "Osteosarcoma TE85 unique-v3")
    assert second.id == first.id
    assert stored is not None
    assert stored.run_id != run_b
    assert stored.text == "Osteosarcoma TE85 unique-v3"


@pytest.mark.asyncio
async def test_same_run_does_not_duplicate_evidence():
    run_a, _ = await _two_runs()
    async with SessionLocal() as session:
        await add_evidence(session, run_id=run_a, gse="GSE1", source_url="http://a", field_path="esummary.taxon", text="Homo sapiens")
        await add_evidence(session, run_id=run_a, gse="GSE1", source_url="http://a", field_path="esummary.taxon", text="Homo sapiens")
        await session.commit()
        bundle = await evidence_bundle(session, run_a, "GSE1")
        n = len((await session.execute(select(Evidence).where(Evidence.gse == "GSE1", Evidence.field_path == "esummary.taxon"))).scalars().all())
    assert len(bundle) == 1
    assert n == 1


@pytest.mark.asyncio
async def test_second_run_excel_evidence_is_linked():
    run_a, run_b = await _two_runs()
    async with SessionLocal() as session:
        shared = await add_evidence(
            session,
            run_id=run_a,
            gse="GSE9",
            source_url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE9",
            field_path="esummary.summary",
            text="human single-cell RNA-seq",
        )
        await add_evidence(
            session,
            run_id=run_b,
            gse="GSE9",
            source_url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE9",
            field_path="esummary.summary",
            text="human single-cell RNA-seq",
        )
        session.add(
            Assessment(
                id=new_id(),
                run_id=run_b,
                gse="GSE9",
                criterion_id="assay",
                verdict="unknown",
                stage="final",
                evidence_ids=dump([shared.id]),
                reason="linked",
            )
        )
        bundle = await evidence_bundle(session, run_b, "GSE9")
        run = await session.get(Run, run_b)
        export = await create_export(session, run, include_json=False)
        await session.commit()
        rows = read_sheet_maps(export.path, "Evidence")
    assert bundle
    assert bundle[0]["text"] == "human single-cell RNA-seq"
    linked = [r for r in rows if r.get("GSE") == "GSE9"]
    assert linked
    assert any(shared.id in str(r.get("evidence_id") or "") for r in linked) or any(
        "human single-cell" in str(r.get("引文") or r.get("支持文本") or "") for r in linked
    )


@pytest.mark.asyncio
async def test_updated_metadata_keeps_old_run_text():
    run_a, run_b = await _two_runs()
    async with SessionLocal() as session:
        old = await add_evidence(
            session,
            run_id=run_a,
            gse="GSE2",
            source_url="http://old",
            field_path="esummary.title",
            text="old title",
        )
        new = await add_evidence(
            session,
            run_id=run_b,
            gse="GSE2",
            source_url="http://new",
            field_path="esummary.title",
            text="new title after update",
        )
        await session.commit()
        bundle_a = await evidence_bundle(session, run_a, "GSE2")
        bundle_b = await evidence_bundle(session, run_b, "GSE2")
        stored_old = await session.get(Evidence, old.id)
    assert old.id != new.id
    assert [row["text"] for row in bundle_a] == ["old title"]
    assert [row["text"] for row in bundle_b] == ["new title after update"]
    assert stored_old is not None
    assert stored_old.source_url == "http://old"
    assert stored_old.text == "old title"


@pytest.mark.asyncio
async def test_different_source_same_text_keeps_both_run_urls():
    run_a, run_b = await _two_runs()
    async with SessionLocal() as session:
        await add_evidence(session, run_id=run_a, gse="GSE3", source_url="http://ftp.old/soft", field_path="soft.design", text="same protocol text")
        await add_evidence(session, run_id=run_b, gse="GSE3", source_url="http://ftp.new/soft", field_path="soft.design", text="same protocol text")
        await session.commit()
        bundle_a = await evidence_bundle(session, run_a, "GSE3")
        bundle_b = await evidence_bundle(session, run_b, "GSE3")
    assert bundle_a[0]["source_url"] == "http://ftp.old/soft"
    assert bundle_b[0]["source_url"] == "http://ftp.new/soft"
    assert bundle_a[0]["text"] == bundle_b[0]["text"]
