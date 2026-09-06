import pytest

from app.connectors.ncbi import NCBIClient, gse_from_summary


@pytest.mark.network
@pytest.mark.asyncio
async def test_live_esearch_and_esummary_gse1000():
    client = NCBIClient(tool="GEOScout", email="")
    result = await client.esearch("GSE1000[Accession]", retmax=5)
    assert result["count"] >= 1
    assert "200001000" in result["idlist"] or any(i.startswith("200") for i in result["idlist"])
    records = await client.esummary(result["idlist"][:5])
    types = {r.get("entrytype") for r in records}
    assert "GSE" in types
    gses = [gse_from_summary(r) for r in records]
    assert "GSE1000" in gses
    assert None in gses or len([g for g in gses if g]) < len(records) or "GDS" in types or "GPL" in types
