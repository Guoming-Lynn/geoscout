from unittest.mock import ANY, AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.db.session import init_db
from app.pipeline.spec_parse import heuristic_parse


@pytest.mark.asyncio
async def test_creation_with_key_does_not_parse_until_requested(monkeypatch):
    await init_db()
    text = "human breast cancer RNA-seq"
    parser = AsyncMock(return_value=heuristic_parse(text))
    monkeypatch.setattr("app.api.parse_spec_with_optional_llm", parser)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        saved = await client.put("/api/connections", json={"llm_api_key": "test-only-key"})
        assert saved.status_code == 200
        response = await client.post("/api/projects", json={"original_request": text})
        assert response.status_code == 200
        parser.assert_not_awaited()
        project = response.json()
        assert project["spec"] == heuristic_parse(text).model_dump()
        parsed = await client.post(f"/api/projects/{project['id']}/spec/parse")
        assert parsed.status_code == 200
        parser.assert_awaited_once_with(text, saved.json()["session_id"], on_usage=ANY)
