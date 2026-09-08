import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from app.main import app
from app.db.session import init_db
from app.schemas.spec import Budget, RunCreate, resolve_run_budget


def test_intensity_validation_and_custom_precedence():
    with pytest.raises(ValidationError):
        RunCreate(tier="unlimited")
    custom = Budget(max_unique_gse=7)
    assert resolve_run_budget(False, custom, "ultra") == (custom, "custom")
    tiers = [Budget.preset(t) for t in ("low", "medium", "high", "ultra")]
    for field in ("max_queries", "max_unique_gse", "max_deep_verify", "max_tokens", "max_runtime_s"):
        values = [getattr(t, field) for t in tiers]
        assert values == sorted(set(values))


@pytest.mark.asyncio
async def test_presets_match_created_run_snapshots():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        presets = (await client.get('/api/budget-presets')).json()
        project = (await client.post('/api/projects', json={'original_request':'human breast cancer RNA-seq'})).json()
        for tier in ('low', 'medium', 'high', 'ultra'):
            response = await client.post(f"/api/projects/{project['id']}/runs", json={'mode':'full', 'tier':tier})
            assert response.status_code == 200
            run = response.json()
            assert run['config']['budget_tier'] == tier
            assert run['budget'] == presets[tier]
            await client.post(f"/api/runs/{run['id']}/cancel")


@pytest.mark.asyncio
async def test_deep_override_preserves_tier_budget_and_custom_precedence():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        project = (await client.post('/api/projects', json={'original_request': 'human RNA-seq'})).json()
        url = f"/api/projects/{project['id']}/runs"
        run = (await client.post(url, json={'tier': 'medium', 'deep_limit': 12})).json()
        assert run['budget']['max_deep_verify'] == 12
        assert run['budget']['max_tokens'] == Budget.preset('medium').max_tokens
        assert (await client.post(url, json={'tier': 'low', 'deep_limit': 81})).status_code == 422
        custom = (await client.post(url, json={'tier': 'medium', 'deep_limit': 12, 'budget': {'max_deep_verify': 2}})).json()
        assert custom['budget']['max_deep_verify'] == 2
