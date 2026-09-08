from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.pipeline.budget import BudgetStop, check_before_external, estimate_tokens, review_token_reserve, token_totals
from app.schemas.spec import Budget, resolve_run_budget


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


def test_screen_budget_skips_soft():
    screen = Budget.screen()
    deep = Budget.deep()
    assert screen.max_deep_verify == 0
    assert screen.max_unique_gse < deep.max_unique_gse
    assert screen.max_tokens < deep.max_tokens
    assert deep.max_tokens >= 1_000_000


def test_resolve_run_budget_tiers():
    screen, screen_tier = resolve_run_budget(True, None)
    deep, deep_tier = resolve_run_budget(False, None)
    custom, custom_tier = resolve_run_budget(True, Budget(max_unique_gse=3, max_deep_verify=1))
    assert screen_tier == "screen"
    assert deep_tier == "deep"
    assert custom_tier == "custom"
    assert screen.max_deep_verify == 0
    assert deep.max_deep_verify == 80
    assert custom.max_unique_gse == 3


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


def test_assess_reserve_counts_two_input_rounds():
    budget = Budget(max_tokens=100_000, max_completion_tokens=4096)
    used = budget.max_tokens - 20_000
    run = SimpleNamespace(
        started_at=datetime.now(timezone.utc),
        token_usage_json=f'{{"prompt_tokens": {used}, "completion_tokens": 0}}',
        counters_json="{}",
        checkpoint_json="{}",
    )
    reserve = review_token_reserve(budget, phase="assess", input_tokens=15_000)
    assert reserve >= 30_000
    with pytest.raises(BudgetStop) as exc:
        check_before_external(run, budget, next_action="llm", reserve=reserve)
    assert "完整核验" in exc.value.reason


def test_verify_reserve_still_needs_input_after_assess():
    budget = Budget(max_tokens=100_000, max_completion_tokens=4096)
    used = budget.max_tokens - 5_000
    run = SimpleNamespace(
        started_at=datetime.now(timezone.utc),
        token_usage_json=f'{{"prompt_tokens": {used}, "completion_tokens": 0}}',
        counters_json="{}",
        checkpoint_json="{}",
    )
    with pytest.raises(BudgetStop):
        check_before_external(
            run, budget, next_action="llm",
            reserve=review_token_reserve(budget, phase="verify", input_tokens=15_000),
        )


def test_small_known_prompt_can_start_under_tight_mock_budget():
    budget = Budget(max_tokens=5500, max_completion_tokens=400)
    run = SimpleNamespace(
        started_at=datetime.now(timezone.utc),
        token_usage_json='{"prompt_tokens": 0, "completion_tokens": 0}',
        counters_json="{}",
        checkpoint_json="{}",
    )
    check_before_external(
        run, budget, next_action="llm",
        reserve=review_token_reserve(budget, phase="assess", input_tokens=200),
    )
