import json

import httpx
import pytest
import respx

from app.connectors.llm import LLMError, LLMProvider, _completion_bodies, _loads_json_object
from app.core.credentials import SessionCredentials


def _creds() -> SessionCredentials:
    return SessionCredentials(
        session_id="s",
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-v4-flash",
        llm_api_key="test-key",
    )


def test_deepseek_bodies_use_json_object_and_disable_thinking():
    bodies = _completion_bodies(
        "https://api.deepseek.com",
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "x"}],
        schema={"type": "object"},
        prompt_name="connection_test",
        max_tokens=128,
    )
    assert bodies[0]["response_format"] == {"type": "json_object"}
    assert bodies[0]["thinking"] == {"type": "disabled"}
    assert "json_schema" not in json.dumps(bodies[0])


def test_loads_json_object_strips_fences():
    assert _loads_json_object('```json\n{"ok": true}\n```') == {"ok": True}


@pytest.mark.asyncio
async def test_deepseek_complete_json_posts_json_object():
    provider = LLMProvider(_creds())
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://api.deepseek.com/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"ok": true, "echo": "geoscout"}'}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
                },
            )
        )
        parsed, usage = await provider.complete_json(
            prompt_name="connection_test",
            system="Return JSON only.",
            user="ping",
            schema={"type": "object"},
        )
    assert parsed == {"ok": True, "echo": "geoscout"}
    assert usage["source"] == "provider"
    body = json.loads(route.calls[0].request.content)
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_empty_content_retries_without_thinking():
    provider = LLMProvider(_creds())
    with respx.mock(assert_all_called=True) as router:
        router.post("https://api.deepseek.com/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json={"choices": [{"message": {"content": "", "reasoning_content": "cot"}}]}),
                httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}),
            ]
        )
        parsed, _usage = await provider.complete_json(
            prompt_name="connection_test",
            system="Return JSON only.",
            user="ping",
        )
    assert parsed == {"ok": True}


@pytest.mark.asyncio
async def test_auth_error_does_not_retry():
    provider = LLMProvider(_creds())
    with respx.mock:
        respx.post("https://api.deepseek.com/chat/completions").mock(return_value=httpx.Response(401, text="nope"))
        with pytest.raises(LLMError) as exc:
            await provider.complete_json(prompt_name="t", system="Return JSON only.", user="ping")
    assert exc.value.status_code == 401


def test_models_url_and_parse_ids():
    from app.connectors.llm import models_url, parse_model_ids

    assert models_url("https://api.openai.com/v1") == "https://api.openai.com/v1/models"
    assert models_url("https://api.deepseek.com/") == "https://api.deepseek.com/models"
    assert parse_model_ids({"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o"}, {"id": "gpt-4o"}]}) == [
        "gpt-4o-mini",
        "gpt-4o",
    ]
    assert parse_model_ids({"models": [{"name": "llama3"}]}) == ["llama3"]


@pytest.mark.asyncio
async def test_list_models_openai_compatible():
    provider = LLMProvider(_creds())
    with respx.mock:
        respx.get("https://api.deepseek.com/models").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "deepseek-v4-flash"}, {"id": "deepseek-chat"}]})
        )
        result = await provider.list_models()
    assert result["ok"] is True
    assert result["models"] == ["deepseek-v4-flash", "deepseek-chat"]
    assert "key" not in str(result).lower() or "test-key" not in str(result)
