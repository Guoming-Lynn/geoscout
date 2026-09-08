from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.pipeline.repo import load
from app.schemas.spec import Budget


class BudgetStop(Exception):
    def __init__(self, reason: str, unfinished: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.unfinished = unfinished


def token_totals(token_usage: dict[str, Any]) -> tuple[int, bool]:
    prompt = token_usage.get("prompt_tokens")
    completion = token_usage.get("completion_tokens")
    estimated = bool(token_usage.get("estimated"))
    if prompt is None or completion is None:
        estimated = True
    total = int(prompt or 0) + int(completion or 0)
    return total, estimated


def estimate_tokens(text: str) -> int:
    """Character-based stand-in when the provider omits usage. Never treated as zero."""
    return max(32, len(text) // 4)


def check_before_external(run: Any, budget: Budget, *, next_action: str, reserve: int = 0) -> None:
    """Raise BudgetStop if the next NCBI/LLM/FTP call must not be scheduled."""
    now = datetime.now(timezone.utc)
    started = getattr(run, "started_at", None)
    if started is not None:
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed = (now - started).total_seconds()
        if elapsed >= budget.max_runtime_s:
            raise BudgetStop("达到运行时间预算", unfinished=next_action)
    usage = load(getattr(run, "token_usage_json", None), {})
    total, estimated = token_totals(usage)
    if total >= budget.max_tokens:
        label = "达到 token 预算"
        if estimated:
            label += "（含估算用量，缺失值未当作 0）"
        raise BudgetStop(label, unfinished=next_action)
    if reserve and total + reserve > budget.max_tokens:
        raise BudgetStop("剩余 token 不足以完成一条完整核验（含输出与格式修复额度）", unfinished=next_action)
    counters = load(getattr(run, "counters_json", None), {})
    if next_action == "search" and int(counters.get("queries_done") or 0) >= budget.max_queries:
        raise BudgetStop("达到查询条数预算", unfinished=next_action)
    if next_action in {"search", "summary"} and int(counters.get("unique_gse") or 0) >= budget.max_unique_gse:
        raise BudgetStop("达到唯一 GSE 初筛预算", unfinished=next_action)
    if next_action == "deep" and int(counters.get("deep_done") or 0) >= budget.max_deep_verify:
        raise BudgetStop("达到深核条目预算", unfinished=next_action)
    if next_action == "llm" and total >= budget.max_tokens:
        raise BudgetStop("达到 token 预算", unfinished=next_action)


def review_token_reserve(budget: Budget, *, phase: str, input_tokens: int = 0) -> int:
    """Tokens that must remain for a complete assess/verify (inputs, output, format repair)."""
    output = int(budget.max_completion_tokens or 4096)
    inp = max(0, int(input_tokens))
    rounds = 2 if phase in {"assess", "assess_dataset"} else 1
    return rounds * inp + (2 * rounds) * output
