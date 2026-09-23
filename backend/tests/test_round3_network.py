import pytest

from app.connectors.llm import LLMError, LLMProvider
from app.core.credentials import SessionCredentials


def _provider() -> LLMProvider:
    return LLMProvider(
        SessionCredentials(
            session_id="round3",
            llm_api_key="test-key",
            llm_base_url="https://api.deepseek.com",
            llm_model="deepseek-v4-flash",
        )
    )


@pytest.mark.asyncio
async def test_connect_error_is_retried(monkeypatch):
    monkeypatch.setattr("app.connectors.llm._NETWORK_BACKOFF_S", (0, 0))
    calls = {"n": 0}

    async def _post(self, body, *, allow_schema_fallback):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LLMError("模型网络错误: ConnectError: down", retryable=True, kind="network", maybe_billed=False)
        return {"choices": [{"message": {"content": "{\"ok\": true}"}}]}, {"prompt_tokens": 3, "completion_tokens": 2}

    monkeypatch.setattr(LLMProvider, "_post", _post)
    parsed, _usage = await _provider().complete_json(
        prompt_name="connection_test", system="Return JSON only.", user="{}", schema=None,
    )
    assert parsed["ok"] is True
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_read_timeout_retries_once_and_marks_billing(monkeypatch):
    monkeypatch.setattr("app.connectors.llm._NETWORK_BACKOFF_S", (0, 0))
    calls = {"n": 0}

    async def _post(self, body, *, allow_schema_fallback):
        calls["n"] += 1
        raise LLMError("模型网络错误: ReadTimeout: timed out", retryable=True, kind="network", maybe_billed=True)

    monkeypatch.setattr(LLMProvider, "_post", _post)
    provider = _provider()
    with pytest.raises(LLMError) as caught:
        await provider.complete_json(prompt_name="connection_test", system="Return JSON only.", user="{}", schema=None)
    assert calls["n"] == 2
    assert provider.billing_uncertain is True
    assert "ReadTimeout" in str(caught.value)
