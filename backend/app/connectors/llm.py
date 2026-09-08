from __future__ import annotations

import json
import logging
import re
from typing import Any
from collections.abc import Callable
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from app.core.credentials import SessionCredentials
from app.core.redact import redact_text
from app.core.usage import add_usage
from app.schemas.spec import ModelAssessment

logger = logging.getLogger("geoscout.llm")

PROMPT_VERSIONS = {
    "parse_research_spec": "v1",
    "expand_queries": "v1",
    "assess_dataset": "v1",
    "verify_dataset": "v1",
}


class LLMError(Exception):
    def __init__(self, message: str, status_code: int | None = None, retryable: bool = False, kind: str = "output") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.kind = kind
        self.usage: dict[str, Any] = {}


class LLMProvider:
    def __init__(self, creds: SessionCredentials, *, mock: bool = False,
                 on_usage: Callable[[dict[str, Any]], None] | None = None,
                 before_request: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.creds = creds
        self.mock = mock
        self.on_usage = on_usage
        self.before_request = before_request

    async def complete_json(
        self,
        *,
        prompt_name: str,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.mock:
            payload = _mock_payload(prompt_name, user)
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "estimated": False, "source": "mock"}
            if self.on_usage:
                self.on_usage(usage)
            return payload, usage
        if not self.creds.llm_api_key:
            raise LLMError("未提供模型 API Key", status_code=401)
        system = _ensure_json_instruction(system)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_error: LLMError | None = None
        total: dict[str, Any] = {}
        for body in _completion_bodies(
            self.creds.llm_base_url,
            model=self.creds.llm_model,
            messages=messages,
            schema=schema,
            prompt_name=prompt_name,
            max_tokens=max_output_tokens or 4096,
        ):
            if self.before_request:
                self.before_request(body)
            accounted = False
            try:
                data, usage = await self._post(body, allow_schema_fallback=False)
                measured = self._measure_usage(body, usage)
                total = add_usage(total, measured)
                accounted = True
                content = _message_content(data)
                if not content.strip():
                    raise LLMError("模型返回空 content", retryable=True)
                return _loads_json_object(content), {**total, "source": "estimated" if total.get("estimated") else "provider"}
            except LLMError as exc:
                if not accounted:
                    total = add_usage(total, self._measure_usage(body, {}))
                exc.usage = total
                last_error = exc
                if exc.status_code in {401, 403} or exc.kind == "network":
                    raise
                continue
        assert last_error is not None
        raise last_error

    def _measure_usage(self, body: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
        missing = usage.get("prompt_tokens") is None or usage.get("completion_tokens") is None
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        if prompt is None:
            prompt = max(32, len(json.dumps(body.get("messages", []), ensure_ascii=False)) // 4)
        if completion is None:
            # Unknown output is conservatively reserved, never displayed as zero cost.
            completion = int(body.get("max_tokens") or 4096)
        measured = {"prompt_tokens": int(prompt), "completion_tokens": int(completion),
                    "estimated": bool(missing or usage.get("estimated")), "request_count": 1,
                    "missing_usage_requests": int(missing)}
        if self.on_usage:
            self.on_usage(measured)
        return measured

    async def test_connection(self) -> dict[str, Any]:
        if self.mock:
            return {
                "ok": True,
                "mode": "mock",
                "model": self.creds.llm_model,
                "json_schema_supported": True,
                "message": "当前为 mock 模型模式，未向外部发送请求。",
            }
        if not self.creds.llm_api_key:
            return {"ok": False, "message": "请先填写模型 API Key。"}
        deepseek = _deepseek_host(self.creds.llm_base_url)
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}, "echo": {"type": "string"}},
            "required": ["ok", "echo"],
            "additionalProperties": False,
        }
        try:
            parsed, usage = await self.complete_json(
                prompt_name="connection_test",
                system="Return JSON only.",
                user='Reply with {"ok": true, "echo": "geoscout"}',
                schema=None if deepseek else schema,
            )
            if deepseek:
                return {
                    "ok": bool(parsed.get("ok")),
                    "mode": "live",
                    "model": self.creds.llm_model,
                    "target": redact_text(self.creds.llm_base_url),
                    "json_schema_supported": False,
                    "json_object_used": True,
                    "parsed": parsed,
                    "usage": usage,
                    "message": "连接成功。DeepSeek 官方 JSON Output 使用 json_object；已关闭 thinking。不支持 json_schema。",
                }
            return {
                "ok": bool(parsed.get("ok")),
                "mode": "live",
                "model": self.creds.llm_model,
                "target": redact_text(self.creds.llm_base_url),
                "json_schema_supported": True,
                "parsed": parsed,
                "usage": usage,
                "message": "连接成功，支持 JSON Schema 结构化输出。",
            }
        except LLMError as exc:
            if "response_format" in str(exc).lower() or exc.status_code == 400:
                parsed, usage = await self.complete_json(
                    prompt_name="connection_test",
                    system="Return JSON only.",
                    user='Reply with {"ok": true, "echo": "geoscout"}',
                    schema=None,
                )
                return {
                    "ok": bool(parsed.get("ok")),
                    "mode": "live",
                    "model": self.creds.llm_model,
                    "target": redact_text(self.creds.llm_base_url),
                    "json_schema_supported": False,
                    "parsed": parsed,
                    "usage": usage,
                    "message": "连接成功，但该接口不支持 json_schema；已回退到 JSON 指令 + 本地校验。",
                }
            return {
                "ok": False,
                "mode": "live",
                "model": self.creds.llm_model,
                "target": redact_text(self.creds.llm_base_url),
                "message": str(exc),
                "usage": exc.usage,
                "hint": _hint_for(exc),
            }

    async def list_models(self) -> dict[str, Any]:
        if self.mock:
            return {
                "ok": True,
                "models": ["mock-model"],
                "message": "当前为 mock 模型模式，未向外部请求模型列表。",
            }
        if not self.creds.llm_base_url.strip():
            return {"ok": False, "models": [], "message": "请先填写模型 Base URL。"}
        if not self.creds.llm_api_key:
            return {"ok": False, "models": [], "message": "请先填写模型 API Key。"}
        url = models_url(self.creds.llm_base_url)
        headers = {
            "Authorization": f"Bearer {self.creds.llm_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.creds.llm_timeout_s) as client:
                response = await client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMError("拉取模型列表超时", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"拉取模型列表网络错误: {exc}", retryable=True) from exc
        if response.status_code in {401, 403}:
            return {
                "ok": False,
                "models": [],
                "target": redact_text(url),
                "message": "模型认证失败，请检查 API Key 与 Base URL。",
            }
        if response.status_code >= 400:
            return {
                "ok": False,
                "models": [],
                "target": redact_text(url),
                "message": f"该接口不提供模型列表（HTTP {response.status_code}）。请手工填写模型名。",
            }
        try:
            payload = response.json()
        except ValueError:
            return {"ok": False, "models": [], "message": "模型列表不是 JSON。"}
        models = parse_model_ids(payload)
        return {
            "ok": True,
            "models": models,
            "target": redact_text(url),
            "message": f"找到 {len(models)} 个模型。" if models else "已连接，但列表为空，请手工填写模型名。",
        }

    async def _post(self, body: dict[str, Any], *, allow_schema_fallback: bool) -> tuple[dict[str, Any], dict[str, Any]]:
        url = self.creds.llm_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.creds.llm_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.creds.llm_timeout_s) as client:
                response = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise LLMError("模型请求超时", retryable=True, kind="network") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"模型网络错误: {exc}", retryable=True, kind="network") from exc
        if response.status_code in {401, 403}:
            raise LLMError("模型认证失败，请检查 API Key 与 Base URL", status_code=response.status_code)
        if response.status_code >= 400:
            text = response.text[:400]
            if allow_schema_fallback and response.status_code == 400:
                raise LLMError(f"response_format 不被支持: {text}", status_code=400)
            raise LLMError(f"模型 HTTP {response.status_code}: {redact_text(text)}", status_code=response.status_code,
                           kind="network" if response.status_code >= 500 or response.status_code == 429 else "output")
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("模型响应不是 JSON") from exc
        if not isinstance(data, dict):
            raise LLMError("模型响应必须是 JSON 对象")
        usage_raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        usage = {
            "prompt_tokens": usage_raw.get("prompt_tokens"),
            "completion_tokens": usage_raw.get("completion_tokens"),
            "total_tokens": usage_raw.get("total_tokens"),
            "estimated": usage_raw.get("prompt_tokens") is None,
            "source": "provider" if usage_raw else "missing",
        }
        return data, usage


def models_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/models"


def parse_model_ids(payload: Any) -> list[str]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        raw = payload.get("data")
        if not isinstance(raw, list):
            raw = payload.get("models")
        items = raw if isinstance(raw, list) else []
    else:
        items = []
    ids: list[str] = []
    seen: set[str] = set()
    for item in items:
        name = item if isinstance(item, str) else None
        if isinstance(item, dict):
            value = item.get("id") or item.get("name") or item.get("model")
            name = str(value) if value else None
        if not name or name in seen:
            continue
        seen.add(name)
        ids.append(name)
    return ids


def _deepseek_host(base_url: str) -> bool:
    host = (urlparse(base_url).hostname or "").lower()
    return host == "api.deepseek.com" or host.endswith(".deepseek.com")


def _ensure_json_instruction(system: str) -> str:
    if "json" in system.lower():
        return system
    return system.rstrip() + "\nReturn a JSON object only."


def _completion_bodies(
    base_url: str,
    *,
    model: str,
    messages: list[dict[str, str]],
    schema: dict[str, Any] | None,
    prompt_name: str,
    max_tokens: int,
) -> list[dict[str, Any]]:
    base: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    bodies: list[dict[str, Any]] = []
    if _deepseek_host(base_url):
        # Official JSON Output is json_object. Thinking is on by default and can
        # exhaust max_tokens, leaving empty content. Disable thinking for JSON.
        deepseek = {
            **base,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
        }
        bodies.append(deepseek)
        bodies.append({**base, "thinking": {"type": "disabled"}})
        return bodies
    if schema:
        bodies.append(
            {
                **base,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": prompt_name, "schema": schema, "strict": True},
                },
            }
        )
        bodies.append({**base, "response_format": {"type": "json_object"}})
    bodies.append(base)
    return bodies


def _message_content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise LLMError("模型返回缺少 choices")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content)


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def _loads_json_object(content: str) -> dict[str, Any]:
    text = _FENCE_RE.sub("", content.strip()).strip()
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise LLMError(f"模型未返回 JSON: {exc}") from exc
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as inner:
            raise LLMError(f"模型未返回 JSON: {inner}") from inner
    if not isinstance(parsed, dict):
        raise LLMError("模型 JSON 必须是对象")
    return parsed


def _hint_for(exc: LLMError) -> str:
    if exc.status_code in {401, 403}:
        return "检查 Key 是否属于该 Base URL，以及是否误填 NCBI Key。"
    if exc.retryable:
        return "稍后重试，或增大超时时间。"
    return "查看 Base URL 是否包含 /v1，以及模型名是否被该服务支持。"


def _mock_payload(prompt_name: str, user: str) -> dict[str, Any]:
    if prompt_name == "parse_research_spec":
        return {
            "disease": ["atherosclerosis"],
            "tissues": ["artery"],
            "organisms": ["Homo sapiens"],
            "assay_types": ["scrna_seq"],
            "required_groups": ["lesion", "control"],
            "minimum_donors_per_group": 3,
            "paired_design": None,
            "required_metadata": [],
            "preferred_metadata": ["age", "sex"],
            "processed_matrix_requirement": "preferred",
            "unresolved_questions": [],
        }
    if prompt_name == "expand_queries":
        return {
            "terms": [
                {"term": "atherosclerosis", "group": "disease", "origin": "model"},
                {"term": "single-cell RNA sequencing", "group": "assay", "origin": "model"},
            ]
        }
    if prompt_name in {"assess_dataset", "verify_dataset"}:
        return _mock_assess(user)
    return {"ok": True, "echo": "geoscout"}


def _mock_assess(user: str) -> dict[str, Any]:
    try:
        payload = json.loads(user) if user else {}
    except json.JSONDecodeError:
        payload = {}
    spec = payload.get("spec") or {}
    evidence = payload.get("evidence") or []
    criteria = spec.get("inclusion_criteria") or []
    needles = {
        "organism": ["Homo sapiens", "Mus musculus"],
        "assay": ["single-cell", "high throughput", "RNA-seq", "Expression profiling"],
        "disease": ["atherosclerosis", "HGPS", "plaque"],
        "tissue": ["artery", "vessel", "plaque", "carotid"],
        "groups": ["control", "lesion", "HGPS", "healthy"],
        "donors": ["donor", "patient"],
        "age": ["age"],
        "sex": ["sex", "female", "male"],
        "processed_matrix": ["CSV", "h5ad", "matrix"],
    }
    judgements: list[dict[str, Any]] = []
    samples = payload.get("samples") or []

    def _hit_in_text(text: str, keys: list[str]) -> str:
        lower = text.lower()
        for needle in keys:
            if needle.lower() in lower:
                return needle
        return ""

    def _sample_text(row: dict[str, Any]) -> str:
        bits = [str(v) for k, v in row.items() if k != "characteristics" and v not in (None, "")]
        bits.append(json.dumps(row.get("characteristics") or [], ensure_ascii=False))
        return " ".join(bits)

    for criterion in criteria:
        cid = str(criterion.get("criterion_id") or "")
        field = str(criterion.get("field") or cid)
        keys = needles.get(field) or needles.get(cid) or []
        hit = None
        snippet = ""
        for row in evidence:
            text = str(row.get("text") or "")
            snippet = _hit_in_text(text, keys)
            if snippet:
                hit = row
                break
        if not hit:
            for row in samples:
                snippet = _hit_in_text(_sample_text(row), keys)
                if snippet:
                    eid = str(row.get("evidence_id") or "")
                    if eid:
                        hit = {"evidence_id": eid}
                    break
        if hit:
            judgements.append(
                {
                    "criterion_id": cid,
                    "verdict": "pass",
                    "evidence_ids": [hit["evidence_id"]],
                    "quote": snippet,
                    "quotes": [snippet],
                    "reason": "mock 根据对应证据原文判断。",
                    "judge_source": "model",
                }
            )
        else:
            judgements.append(
                {
                    "criterion_id": cid,
                    "verdict": "unknown",
                    "evidence_ids": [],
                    "quote": "",
                    "reason": "mock 未在证据中找到直接支持。",
                    "judge_source": "model",
                }
            )
    if not judgements:
        judgements.append(
            {
                "criterion_id": "organism",
                "verdict": "unknown",
                "evidence_ids": [],
                "quote": "",
                "reason": "mock 模式仅作结构校验。",
            }
        )
    return {"judgements": judgements, "concerns": [], "missing": []}


_ASSESSMENT_LIST_KEYS = (
    "judgements",
    "assessments",
    "assess_result",
    "verify_result",
    "results",
    "inclusion_criteria_eval",
    "inclusion_criteria_evaluation",
    "criterion_judgements",
    "evaluations",
)
_ASSESSMENT_NEST_KEYS = (
    "assess_dataset",
    "verify_dataset",
    "data",
    "output",
    "result",
    "inclusion_criteria_eval",
)
_VERDICTS = {"pass", "fail", "unknown"}
_FLAT_SKIP_KEYS = {
    "concerns",
    "missing",
    "overall_confidence",
    "confidence",
    "evidence_id",
    "evidence_ids",
    "inclusion_criteria",
}
_VERDICT_FIELD_ALIASES = ("verdict", "result", "judgment", "judgement", "status", "label")
_VERDICT_VALUE_ALIASES = {
    "pass": "pass",
    "fail": "fail",
    "unknown": "unknown",
    "通过": "pass",
    "失败": "fail",
    "不通过": "fail",
    "未知": "unknown",
    "不确定": "unknown",
}


def normalize_model_assessment_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """DeepSeek json_object often wraps or renames the judgements array."""
    if not isinstance(payload, dict):
        return payload
    data = dict(payload)
    if isinstance(data.get("judgements"), list) and _looks_like_judgements(data["judgements"]):
        return _coerce_judgement_items(data)
    for key in _ASSESSMENT_LIST_KEYS:
        if key == "judgements":
            continue
        value = data.get(key)
        lifted = _lift_judgements(value)
        if lifted is not None:
            data["judgements"] = lifted
            return _coerce_judgement_items(data)
    for key in _ASSESSMENT_NEST_KEYS:
        inner = data.get(key)
        if isinstance(inner, dict):
            return normalize_model_assessment_payload(inner)
        lifted = _lift_judgements(inner)
        if lifted is not None:
            return _coerce_judgement_items(
                {"judgements": lifted, "concerns": data.get("concerns") or [], "missing": data.get("missing") or []}
            )
    flat: list[dict[str, Any]] = []
    leftover = False
    for key, value in data.items():
        if key in _FLAT_SKIP_KEYS or value is None:
            continue
        if isinstance(value, str) and value.lower() in _VERDICTS:
            flat.append(
                {"criterion_id": key, "verdict": value.lower(), "evidence_ids": [], "quote": "", "reason": ""}
            )
        elif isinstance(value, dict) and (value.get("verdict") or value.get("criterion_id") or value.get("criterion")):
            item = dict(value)
            item.setdefault("criterion_id", key)
            flat.append(item)
        else:
            leftover = True
    if flat and not leftover:
        return _coerce_judgement_items({"judgements": flat, "concerns": [], "missing": []})
    return _coerce_judgement_items(data)


def _looks_like_judgements(items: list[Any]) -> bool:
    if not items or not isinstance(items[0], dict):
        return False
    row = items[0]
    if "field" in row and "description" in row and "verdict" not in row and "result" not in row:
        return False
    return bool(
        row.get("verdict")
        or row.get("result")
        or row.get("criterion_id")
        or row.get("criterion")
        or row.get("judgment")
        or row.get("judgement")
    )


def _lift_judgements(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, list) and _looks_like_judgements(value):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        items: list[dict[str, Any]] = []
        for key, inner in value.items():
            if isinstance(inner, dict):
                row = dict(inner)
                row.setdefault("criterion_id", key)
                items.append(row)
            elif isinstance(inner, str) and inner.lower() in _VERDICTS:
                items.append({"criterion_id": key, "verdict": inner.lower(), "evidence_ids": [], "quote": "", "reason": ""})
        if _looks_like_judgements(items):
            return items
    return None


def _coerce_judgement_items(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("judgements")
    if not isinstance(items, list):
        return data
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if "criterion_id" not in row and "criterion" in row:
            row["criterion_id"] = row["criterion"]
        raw_verdict = None
        for key in _VERDICT_FIELD_ALIASES:
            value = row.get(key)
            if value is not None and str(value).strip() != "":
                raw_verdict = value
                break
        if isinstance(raw_verdict, str):
            mapped = _VERDICT_VALUE_ALIASES.get(raw_verdict.strip()) or _VERDICT_VALUE_ALIASES.get(raw_verdict.strip().lower())
            if mapped:
                row["verdict"] = mapped
        if isinstance(row.get("evidence_id"), str) and not row.get("evidence_ids"):
            row["evidence_ids"] = [row["evidence_id"]]
        if not isinstance(row.get("evidence_ids"), list):
            row["evidence_ids"] = []
        if row.get("quote") is None:
            row["quote"] = ""
        if not isinstance(row.get("quotes"), list):
            row["quotes"] = []
        if row.get("reason") is None:
            row["reason"] = ""
        out.append(row)
    normalized = dict(data)
    normalized["judgements"] = out
    normalized.setdefault("concerns", [])
    normalized.setdefault("missing", [])
    return normalized


def validate_assessment(payload: dict[str, Any]) -> ModelAssessment:
    try:
        return ModelAssessment.model_validate(normalize_model_assessment_payload(payload))
    except ValidationError as exc:
        raise LLMError(f"模型输出未通过 schema 校验: {exc}") from exc
