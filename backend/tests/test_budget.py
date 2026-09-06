from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.pipeline.budget import BudgetStop, check_before_external, estimate_tokens, token_totals
from app.schemas.spec import Budget


def test_missing_tokens_are_estimated_not_zero():
    total, estimated = token_totals({"prompt_tokens": None, "completion_tokens": None, "estimated": False})
    assert estimated
    assert estimate_tokens("abcd" * 100) >= 32


def test_runtime_budget_stops_before_next_call():
    run = SimpleNamespace(
        started_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        token_usage_json='{"prompt_tokens": 0, "completion_tokens": 0}',
        counters_json="{}",
        checkpoint_json="{}",
    )
    with pytest.raises(BudgetStop) as exc:
        check_before_external(run, Budget(max_runtime_s=1), next_action="search")
    assert "时间" in exc.value.reason


def test_token_budget_uses_accumulated_usage():
    run = SimpleNamespace(
        started_at=datetime.now(timezone.utc),
        token_usage_json='{"prompt_tokens": 80, "completion_tokens": 30, "estimated": true}',
        counters_json="{}",
        checkpoint_json="{}",
    )
    with pytest.raises(BudgetStop):
        check_before_external(run, Budget(max_tokens=100), next_action="llm")


def test_unique_gse_and_query_caps():
    run = SimpleNamespace(
        started_at=datetime.now(timezone.utc),
        token_usage_json="{}",
        counters_json='{"queries_done": 3, "unique_gse": 5, "deep_done": 2}',
        checkpoint_json="{}",
    )
    with pytest.raises(BudgetStop):
        check_before_external(run, Budget(max_queries=3), next_action="search")
    with pytest.raises(BudgetStop):
        check_before_external(run, Budget(max_unique_gse=5), next_action="summary")
    with pytest.raises(BudgetStop):
        check_before_external(run, Budget(max_deep_verify=2), next_action="deep")
