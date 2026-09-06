from types import SimpleNamespace

import pytest

from app.pipeline.engine import WaitingForCredentials, hydrate_credentials
from app.core.credentials import store
from httpx import Response


@pytest.mark.asyncio
async def test_hydrate_404_does_not_wait(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers=None):
            return Response(404, json={"detail": "missing"})

    monkeypatch.setattr("app.pipeline.engine.httpx.AsyncClient", FakeClient)
    store._items.pop("missing-session", None)
    await hydrate_credentials("missing-session")
    assert store.get("missing-session") is None


def test_live_llm_without_key_raises_wait(monkeypatch):
    from app.pipeline.engine import Engine

    monkeypatch.setattr("app.pipeline.engine.settings.llm_mode", "live")
    engine = Engine(session=SimpleNamespace(), job=SimpleNamespace(run_id="r", step="assess"), worker_id="w")
    run = SimpleNamespace(session_id="no-key", config_summary="{}")
    with pytest.raises(WaitingForCredentials):
        engine._llm(run)
