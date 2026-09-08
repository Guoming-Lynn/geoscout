import json
from types import SimpleNamespace

import httpx
import pytest
import respx

from app.connectors.llm import LLMError, LLMProvider
from app.core.credentials import SessionCredentials
from app.pipeline.engine import Engine
from app.pipeline.budget import BudgetStop
from app.schemas.spec import Budget


def provider(**kwargs):
    return LLMProvider(SessionCredentials(session_id="test", llm_base_url="https://api.deepseek.com", llm_api_key="test-only"), **kwargs)


def response(content="", prompt=100, completion=200):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                   "usage": {"prompt_tokens": prompt, "completion_tokens": completion}})


@pytest.mark.asyncio
async def test_empty_response_usage_survives_failure_and_fallback():
    usage = []
    with respx.mock as router:
        route = router.post("https://api.deepseek.com/chat/completions").mock(return_value=response())
        with pytest.raises(LLMError) as err:
            await provider(on_usage=usage.append).complete_json(prompt_name="test", system="JSON", user="test")
    assert len(usage) == len(route.calls) == 2
    assert err.value.usage["total_tokens"] == 600
    assert all(json.loads(c.request.content)["thinking"] == {"type": "disabled"} for c in route.calls)


@pytest.mark.asyncio
async def test_success_returns_all_attempts_usage():
    with respx.mock as router:
        router.post("https://api.deepseek.com/chat/completions").mock(side_effect=[response(), response('{"ok":true}', 10, 20)])
        _, usage = await provider().complete_json(prompt_name="test", system="JSON", user="test")
    assert usage["total_tokens"] == 330
    assert usage["request_count"] == 2


@pytest.mark.asyncio
async def test_network_failure_is_visible_and_does_not_switch_request_format():
    measured = []
    with respx.mock as router:
        route = router.post("https://api.deepseek.com/chat/completions").mock(return_value=httpx.Response(502))
        with pytest.raises(LLMError) as err:
            await provider(on_usage=measured.append).complete_json(prompt_name="test", system="JSON", user="test", max_output_tokens=128)
    assert len(route.calls) == 1
    assert err.value.kind == "network"
    assert measured[0]["estimated"]
    assert measured[0]["completion_tokens"] == 128
    assert measured[0]["missing_usage_requests"] == 1


@pytest.mark.asyncio
async def test_budget_checked_before_fallback(monkeypatch):
    from app.core.credentials import store
    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_mode", "live")
    creds = store.get_or_create(None)
    creds.llm_api_key = "test-only"
    creds.llm_base_url = "https://api.deepseek.com"
    run = SimpleNamespace(session_id=creds.session_id, config_summary="{}", token_usage_json="{}", counters_json="{}",
                          budget_json=Budget(max_tokens=1000).model_dump_json())
    engine = Engine(None, None, "test")
    with respx.mock as router:
        route = router.post("https://api.deepseek.com/chat/completions").mock(return_value=response(prompt=500, completion=500))
        with pytest.raises(BudgetStop):
            await engine._llm(run).complete_json(prompt_name="test", system="JSON", user="test", max_output_tokens=128)
    assert len(route.calls) == 1
    assert json.loads(run.token_usage_json)["total_tokens"] == 1000


@pytest.mark.asyncio
async def test_parse_failure_usage_saved_separately(monkeypatch):
    from app.core.config import settings
    from app.db.session import init_db
    from app.main import app

    monkeypatch.setattr(settings, "llm_mode", "live")
    await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        await client.put("/api/connections", json={"llm_api_key": "test-only", "llm_base_url": "https://api.deepseek.com"})
        project = (await client.post("/api/projects", json={"original_request": "human breast cancer RNA-seq"})).json()
        with respx.mock as router:
            route = router.post("https://api.deepseek.com/chat/completions").mock(return_value=response(prompt=10, completion=20))
            parsed = (await client.post(f"/api/projects/{project['id']}/spec/parse")).json()
        assert len(route.calls) == 2
        assert parsed["token_usage"]["total_tokens"] == 60
        projects = (await client.get("/api/projects")).json()
        assert next(p for p in projects if p["id"] == project["id"])["parse_token_usage"]["total_tokens"] == 60
