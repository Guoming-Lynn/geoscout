from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.geo_ftp import GeoFetchError, GeoFtpClient, classify_suppl_names
from app.connectors.llm import LLMError, LLMProvider
from app.connectors.ncbi import NCBIClient, NCBIError, gse_from_summary, public_summary
from app.core.config import settings
from app.core.credentials import SessionCredentials, store
from app.core.usage import add_usage
from app.core.urls import accession_page
from app.db.models import Assessment, Dataset, DatasetRelation, Job, Override, QueryAttempt, Run, RunDataset, Sample
from app.evidence.soft_parser import count_biosamples, count_independent_donors, parse_soft_bytes, series_as_dict
from app.evidence.store import add_evidence, evidence_bundle, new_id, write_snapshot
from app.pipeline.assay import mixed_omics_note
from app.pipeline.assessment import (
    CheckedAssessment,
    _organism_ok,
    _sample_fits_all_hard,
    bind_rule_evidence,
    check_model_assessment,
    fit_samples,
    judge_user_payload,
    merge_final,
)
from app.pipeline.budget import BudgetStop, check_before_external, estimate_tokens, note_pause, review_token_reserve
from app.pipeline.donors import donors_per_group, infer_group_label
from app.pipeline.query_planner import plan_queries
from app.pipeline.ranking import deep_download_ceiling, deep_target_span, relevance, select_deep_targets
from app.pipeline.source import sorted_fraction
from app.pipeline.repo import (
    add_event,
    bump_counters,
    dump,
    enqueue_job,
    load,
    upsert_dataset,
    upsert_run_dataset,
    upsert_sample,
)
from app.pipeline.screening import classify, rule_gate_ids, rule_judgements, soft_score
from app.pipeline.spec_parse import heuristic_parse, merge_model_parse
from app.prompts import load_prompt
from app.schemas.spec import Budget, CriterionJudgement, ResearchSpec, TermEntry

logger = logging.getLogger("geoscout.engine")

LLM_DATASET_STATUSES = {"soft_loaded", "soft_incomplete", "assessed", "verified", "needs_review"}
TERMINAL = {"completed", "partial", "failed", "cancelled"}


class WaitingForCredentials(Exception):
    pass


class StopForCancel(Exception):
    pass


class Engine:
    def __init__(self, session: AsyncSession, job: Job, worker_id: str) -> None:
        self.session = session
        self.job = job
        self.worker_id = worker_id

    async def run(self) -> None:
        run = await self.session.get(Run, self.job.run_id)
        if run is None:
            self.job.status = "failed"
            self.job.last_error = "run missing"
            return
        if run.cancel_requested:
            run.status = "cancelled"
            run.stop_reason = "用户取消"
            run.finished_at = datetime.now(timezone.utc)
            self.job.status = "cancelled"
            await add_event(self.session, run.id, "任务已取消，保留已完成结果")
            return
        if run.status in TERMINAL:
            self.job.status = "cancelled"
            self.job.last_error = "任务已结束，忽略迟到步骤"
            await add_event(self.session, run.id, f"忽略迟到步骤 {self.job.step}，任务已是 {run.status}")
            return
        if run.pause_requested and run.status not in TERMINAL:
            run.status = "paused"
            run.stop_reason = "用户暂停"
            note_pause(run)
            self.job.status = "queued"
            await add_event(self.session, run.id, "已在原子步骤边界暂停")
            return
        try:
            await hydrate_credentials(run.session_id)
            handler = {
                "plan": self.step_plan,
                "search": self.step_search,
                "fetch_summaries": self.step_fetch_summaries,
                "screen": self.step_screen,
                "deep_fetch": self.step_deep_fetch,
                "assess": self.step_assess,
                "verify": self.step_verify,
                "finalize": self.step_finalize,
            }[self.job.step]
            await handler(run)
        except StopForCancel:
            run.status = "cancelled"
            run.stop_reason = run.stop_reason or "用户取消"
            run.finished_at = datetime.now(timezone.utc)
            self.job.status = "cancelled"
            await add_event(self.session, run.id, "已取消，未发出下一步模型请求")
        except WaitingForCredentials:
            run.status = "waiting_for_credentials"
            run.stop_reason = "进程重启或尚未提供模型 Key，检查点已保留"
            note_pause(run)
            self.job.status = "waiting_credentials"
            await add_event(self.session, run.id, "等待重新提供模型凭据", level="warn")
        except BudgetStop as exc:
            run.stop_reason = exc.reason
            if exc.unfinished:
                ck = load(run.checkpoint_json, {})
                ck["unfinished"] = exc.unfinished
                run.checkpoint_json = dump(ck)
            self.job.status = "done"
            await add_event(self.session, run.id, f"预算停止：{exc.reason}；未完成 {exc.unfinished or '当前步骤'}。已有结果可导出。", level="warn")
            await enqueue_job(self.session, run.id, "finalize")
        except NCBIError as exc:
            if exc.retryable and self.job.attempt < 5:
                self.job.status = "queued"
                self.job.last_error = str(exc)
                run.status = "running"
                await add_event(self.session, run.id, f"NCBI 可恢复错误，将重试: {exc}", level="warn")
                return
            run.status = "failed"
            run.error_message = str(exc)
            run.stop_reason = "NCBI 请求失败（未改用演示数据）"
            run.finished_at = datetime.now(timezone.utc)
            self.job.status = "failed"
            self.job.last_error = str(exc)
            await add_event(self.session, run.id, f"NCBI 失败: {exc}", level="error")
        except Exception as exc:
            logger.exception("job failed")
            run.status = "failed"
            run.error_message = str(exc)
            run.stop_reason = "内部错误"
            run.finished_at = datetime.now(timezone.utc)
            self.job.status = "failed"
            self.job.last_error = str(exc)
            await add_event(self.session, run.id, f"任务失败: {exc}", level="error")

    def _budget(self, run: Run) -> Budget:
        return Budget.model_validate(load(run.budget_json, {}))

    def _spec(self, run: Run) -> ResearchSpec:
        return ResearchSpec.model_validate(load(run.spec_snapshot, {}))

    def _demo(self, run: Run) -> bool:
        cfg = load(run.config_summary, {})
        return bool(cfg.get("demo")) and settings.demo_allowed()

    def _ncbi(self, run: Run) -> NCBIClient:
        creds = store.get(run.session_id)
        if self._demo(run) or settings.ncbi_mode == "mock":
            from app.pipeline.mock_ncbi import MockNCBIClient

            return MockNCBIClient()
        return NCBIClient(
            tool=(creds.ncbi_tool if creds else None),
            email=(creds.ncbi_email if creds else None),
            api_key=(creds.ncbi_api_key if creds else None),
        )

    def _llm(self, run: Run) -> LLMProvider:
        creds = store.get(run.session_id) or SessionCredentials(session_id=run.session_id)
        mock = settings.llm_mode == "mock" or self._demo(run)
        if not mock and not creds.has_llm_key():
            raise WaitingForCredentials()
        return LLMProvider(creds, mock=mock, on_usage=lambda usage: _add_tokens(run, usage),
                           before_request=lambda body: self._guard_llm_request(run, body))

    def _guard_llm_request(self, run: Run, body: dict) -> None:
        self._guard(run, "llm")
        usage = load(run.token_usage_json, {})
        used = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        expected = estimate_tokens(json.dumps(body.get("messages", []), ensure_ascii=False)) + int(body.get("max_tokens") or 0)
        if used + expected > self._budget(run).max_tokens:
            raise BudgetStop("剩余 token 预算不足以容纳下一次请求（预估输入及输出额度）", unfinished="llm")

    def _sample_budget(self, run: Run) -> int:
        return int(getattr(self._budget(run), "sample_char_budget", 40_000) or 40_000)

    def _guard(self, run: Run, next_action: str, *, reserve: int = 0) -> None:
        check_before_external(run, self._budget(run), next_action=next_action, reserve=reserve)

    def _guard_review(self, run: Run, phase: str, *, input_tokens: int = 0) -> None:
        self._guard(run, "llm", reserve=review_token_reserve(self._budget(run), phase=phase, input_tokens=input_tokens))

    async def step_plan(self, run: Run) -> None:
        run.status = "running"
        run.stage = "planning"
        run.started_at = run.started_at or datetime.now(timezone.utc)
        spec = self._spec(run)
        existing_q = (
            await self.session.execute(select(QueryAttempt).where(QueryAttempt.run_id == run.id))
        ).scalars().all()
        if existing_q:
            await add_event(self.session, run.id, "查询计划已存在，跳过重复规划")
            self.job.status = "done"
            await enqueue_job(self.session, run.id, "search")
            return
        extra: list[TermEntry] = []
        creds = store.get(run.session_id)
        if run.mode == "full" and (settings.llm_mode == "mock" or (creds and creds.has_llm_key())):
            try:
                self._guard(run, "llm")
                llm = self._llm(run)
                payload, usage = await llm.complete_json(
                    prompt_name="expand_queries",
                    system=load_prompt("expand_queries"),
                    user=spec.model_dump_json(),
                    schema=None,
                    max_output_tokens=self._budget(run).max_completion_tokens,
                )
                for item in payload.get("terms") or []:
                    extra.append(TermEntry.model_validate(item))
            except WaitingForCredentials:
                extra = []
            except LLMError as exc:
                await add_event(self.session, run.id, f"扩词模型失败，继续使用词典: {exc}", level="warn")
        cfg = load(run.config_summary, {})
        manual = cfg.get("manual_query")
        planned = plan_queries(spec, extra, manual_query=manual)
        budget = self._budget(run)
        planned = planned[: budget.max_queries]
        for query_index, item in enumerate(planned):
            self.session.add(
                QueryAttempt(
                    id=new_id(),
                    run_id=run.id,
                    query_hash=_qhash(item.term),
                    term=item.term,
                    round_no=item.round_no,
                    query_index=query_index,
                    source=item.source,
                    status="pending",
                )
            )
        await add_event(self.session, run.id, f"已规划 {len(planned)} 条检索式（非穷尽）")
        write_snapshot(run.id, "query_plan.json", [p.model_dump() for p in planned])
        self.job.status = "done"
        await enqueue_job(self.session, run.id, "search")

    async def step_search(self, run: Run) -> None:
        run.status = "running"
        run.stage = "searching"
        budget = self._budget(run)
        pending = (
            await self.session.execute(
                select(QueryAttempt)
                .where(QueryAttempt.run_id == run.id, QueryAttempt.status == "pending")
                .order_by(QueryAttempt.query_index, QueryAttempt.id)
            )
        ).scalars().all()
        if not pending:
            self.job.status = "done"
            await enqueue_job(self.session, run.id, "fetch_summaries")
            return
        counters = load(run.counters_json, {})
        unique = int(counters.get("unique_gse") or 0)
        if unique >= budget.max_unique_gse:
            for item in pending:
                item.status = "skipped_budget"
            run.stop_reason = "达到唯一 GSE 初筛预算"
            self.job.status = "done"
            await enqueue_job(self.session, run.id, "fetch_summaries")
            await add_event(self.session, run.id, "查询预算截断，已跳过剩余检索式")
            return
        self._guard(run, "search")
        attempt = pending[0]
        # Reserve a share for every pending query. Unused capacity rolls forward.
        attempt.candidate_limit = attempt.candidate_limit or max(1, (budget.max_unique_gse - unique) // len(pending))
        allowance = min(attempt.candidate_limit, budget.max_unique_gse - unique)
        client = self._ncbi(run)
        attempt.status = "running"
        attempt.started_at = datetime.now(timezone.utc)
        checkpoint = load(run.checkpoint_json, {})
        seen_uids = set(checkpoint.get("search_seen_uids", []))
        try:
            page_size = budget.esearch_page_size
            retstart = attempt.retstart
            first = await client.esearch(attempt.term, retstart=retstart, retmax=min(page_size, allowance))
            attempt.hit_count = first["count"]
            attempt.query_translation = first["querytranslation"]
            ids = [uid for uid in dict.fromkeys(first["idlist"]) if uid not in seen_uids][:allowance]
            retstart += len(first["idlist"])
            fetch_cap = min(first["count"], budget.max_unique_gse + len(seen_uids))
            while retstart < fetch_cap and len(ids) < allowance:
                self._guard(run, "search")
                more = await client.esearch(attempt.term, retstart=retstart, retmax=min(page_size, allowance - len(ids)))
                if not more["idlist"]:
                    break
                batch_ids = [uid for uid in dict.fromkeys(more["idlist"]) if uid not in seen_uids and uid not in ids][:allowance - len(ids)]
                ids.extend(batch_ids)
                retstart += len(more["idlist"])
                attempt.pages_done += 1
            attempt.retstart = retstart
            attempt.pages_done = max(attempt.pages_done, 1)
            attempt.truncated = int(first["count"] or 0) > retstart
            if attempt.truncated:
                run.stop_reason = run.stop_reason or "ESearch 命中超过本次取回上限，查询已截断"
            ck = load(self.job.checkpoint_json, {})
            ck["uids"] = list(dict.fromkeys((ck.get("uids") or []) + ids))
            ck["term"] = attempt.term
            ck["truncated"] = attempt.truncated
            self.job.checkpoint_json = dump(ck)
            checkpoint["search_seen_uids"] = sorted(seen_uids | set(ids))
            run.checkpoint_json = dump(checkpoint)
            write_snapshot(run.id, f"esearch_{attempt.query_hash}.json", first | {"idlist": ids, "truncated": attempt.truncated})
        except NCBIError:
            attempt.status = "pending"
            attempt.error_message = "search failed"
            attempt.finished_at = datetime.now(timezone.utc)
            raise
        attempt.status = "searched"
        attempt.finished_at = datetime.now(timezone.utc)
        await bump_counters(self.session, run, queries_done=1)
        await add_event(
            self.session,
            run.id,
            f"查询完成：命中 {attempt.hit_count}，待摘要 UID {len(load(self.job.checkpoint_json, {}).get('uids') or [])}",
        )
        self.job.status = "done"
        await enqueue_job(self.session, run.id, "fetch_summaries", load(self.job.checkpoint_json, {}))

    async def step_fetch_summaries(self, run: Run) -> None:
        run.stage = "fetching"
        payload = load(self.job.payload_json, {})
        uids: list[str] = list(payload.get("uids") or [])
        term = payload.get("term") or ""
        budget = self._budget(run)
        client = self._ncbi(run)
        skipped = {"GDS": 0, "GPL": 0, "GSM": 0, "other": 0}
        new_unique = 0
        counters = load(run.counters_json, {})
        already = int(counters.get("unique_gse") or 0)
        for i in range(0, len(uids), budget.summary_batch_size):
            if already + new_unique >= budget.max_unique_gse:
                run.stop_reason = run.stop_reason or "达到唯一 GSE 初筛预算"
                break
            self._guard(run, "summary")
            batch = uids[i : i + budget.summary_batch_size]
            records = await client.esummary(batch)
            for rec in records:
                if already + new_unique >= budget.max_unique_gse:
                    run.stop_reason = run.stop_reason or "达到唯一 GSE 初筛预算"
                    break
                pub = public_summary(rec)
                gse = gse_from_summary(rec)
                if not gse:
                    kind = str(rec.get("entrytype") or "other").upper()
                    skipped[kind if kind in skipped else "other"] += 1
                    continue
                await upsert_dataset(self.session, pub)
                _, created = await upsert_run_dataset(self.session, run.id, gse, term)
                if created:
                    new_unique += 1
                url = accession_page(gse)
                await add_evidence(
                    self.session,
                    run_id=run.id,
                    gse=gse,
                    source_url=url,
                    field_path="esummary.title",
                    text=pub.get("title") or "",
                )
                await add_evidence(
                    self.session,
                    run_id=run.id,
                    gse=gse,
                    source_url=url,
                    field_path="esummary.summary",
                    text=pub.get("summary") or "",
                )
                await add_evidence(
                    self.session,
                    run_id=run.id,
                    gse=gse,
                    source_url=url,
                    field_path="esummary.taxon",
                    text=str(pub.get("taxon") or ""),
                )
                await add_evidence(
                    self.session,
                    run_id=run.id,
                    gse=gse,
                    source_url=url,
                    field_path="esummary.gdstype",
                    text=str(pub.get("gdstype") or ""),
                )
        if term:
            qa = (
                await self.session.execute(
                    select(QueryAttempt).where(QueryAttempt.run_id == run.id, QueryAttempt.term == term)
                )
            ).scalar_one_or_none()
            if qa:
                qa.new_unique_gse = new_unique
                qa.status = "done"
        await bump_counters(self.session, run, unique_gse=new_unique, skipped_non_gse=sum(skipped.values()))
        await add_event(
            self.session,
            run.id,
            f"摘要完成：新增唯一 GSE {new_unique}，跳过非 GSE {skipped}",
        )
        pending = (
            await self.session.execute(
                select(QueryAttempt).where(QueryAttempt.run_id == run.id, QueryAttempt.status == "pending")
            )
        ).scalars().all()
        self.job.status = "done"
        if pending:
            await enqueue_job(self.session, run.id, "search")
        else:
            await enqueue_job(self.session, run.id, "screen")

    async def step_screen(self, run: Run) -> None:
        run.stage = "screening"
        spec = self._spec(run)
        overrides = await self._latest_overrides(run.id)
        rows = (await self.session.execute(select(RunDataset).where(RunDataset.run_id == run.id))).scalars().all()
        for rd in rows:
            ds = await self.session.get(Dataset, rd.gse)
            summary = _screen_summary(ds)
            judgements = bind_rule_evidence(rule_judgements(spec, summary, []), await evidence_bundle(self.session, run.id, rd.gse))
            rule_data = [j.model_dump() for j in judgements]
            rd.first_assess_json = dump({"rules": rule_data, "selection": relevance(spec, summary, rule_data)})
            score, coverage, _ = soft_score(spec, judgements)
            rd.soft_score = score
            rd.soft_coverage = coverage
            unknown = [c.criterion_id for c in spec.inclusion_criteria if c.priority == "hard"
                       and not any(j.criterion_id == c.criterion_id and j.verdict in {"pass", "fail"}
                                   and not j.clue_only for j in judgements)]
            rd.hard_unknowns = len(unknown)
            rd.gsm_count = summary.get("n_samples")
            rd.processed_data = "probable" if summary.get("suppfile") else "unknown"
            hard_fail = any(
                j.verdict == "fail" and not j.clue_only and _is_hard(spec, j.criterion_id) for j in judgements
            )
            if hard_fail:
                category, reason = classify(
                    spec,
                    judgements,
                    verified=True,
                    conflict=False,
                    model_invalid=False,
                    depth_complete=False,
                    review_complete=False,
                )
                rd.verification_status = "rule_excluded"
            else:
                category, reason = "needs_review", "初筛完成，未做深度核验。" + ("待核实条件: " + ", ".join(unknown) if unknown else "摘要线索不能替代样本核验。")
                rd.verification_status = "summary_screened"
            kept = overrides.get(rd.gse)
            if kept is not None:
                rd.category = kept.new_category
                rd.reason = kept.reason or reason
            else:
                rd.category, rd.reason = category, reason
            await _replace_assessments(self.session, run.id, rd.gse, "rule_screen", judgements, actor="rule")
        await add_event(self.session, run.id, f"规则初筛完成，{len(rows)} 条 GSE")
        self.job.status = "done"
        if run.mode == "manual_query":
            await enqueue_job(self.session, run.id, "finalize")
        else:
            await enqueue_job(self.session, run.id, "deep_fetch")

    def _backfill_targets(self, rows: list[RunDataset], checkpoint: dict[str, Any], limit: int) -> list[str]:
        taken = set(checkpoint.get("deep_targets") or [])
        pool = sorted(
            (r for r in rows if r.gse not in taken and r.verification_status != "rule_excluded"),
            key=lambda r: (-load(r.first_assess_json, {}).get("selection", {}).get("score", 0), r.gse),
        )[: max(0, limit)]
        rank = len(taken)
        for row in pool:
            rank += 1
            first = load(row.first_assess_json, {})
            selection = first.setdefault("selection", {})
            selection["selected"] = True
            selection["rank"] = rank
            selection["backfill"] = True
            row.first_assess_json = dump(first)
        return [r.gse for r in pool]

    async def step_deep_fetch(self, run: Run) -> None:
        run.stage = "fetching"
        budget = self._budget(run)
        spec = self._spec(run)
        rows = (await self.session.execute(select(RunDataset).where(RunDataset.run_id == run.id))).scalars().all()
        checkpoint = load(run.checkpoint_json, {})
        if "deep_targets" not in checkpoint:
            datasets = (await self.session.execute(select(Dataset).join(RunDataset, RunDataset.gse == Dataset.gse).where(RunDataset.run_id == run.id))).scalars().all()
            summaries = {d.gse: _screen_summary(d) for d in datasets}
            cap = budget.max_deep_verify
            checkpoint["deep_targets"] = select_deep_targets(rows, summaries, deep_target_span(cap))
            for row in rows:
                first = load(row.first_assess_json, {})
                selection = first.setdefault("selection", {})
                selection["selected"] = row.gse in checkpoint["deep_targets"]
                selection["rank"] = checkpoint["deep_targets"].index(row.gse) + 1 if selection["selected"] else None
                first["selection"] = selection
                row.first_assess_json = dump(first)
            run.checkpoint_json = dump(checkpoint)
        by_gse = {r.gse: r for r in rows}
        targets = [by_gse[g] for g in checkpoint["deep_targets"] if g in by_gse]
        payload = load(self.job.payload_json, {})
        index = int(payload.get("index") or 0)
        deep_done = int(load(run.counters_json, {}).get("deep_done") or 0)
        cap = budget.max_deep_verify
        if index >= len(targets) and 0 < cap and deep_done < cap and len(targets) < deep_download_ceiling(cap):
            extra = self._backfill_targets(rows, checkpoint, min(cap - deep_done, deep_download_ceiling(cap) - len(targets)))
            if extra:
                checkpoint["deep_targets"] = checkpoint["deep_targets"] + extra
                run.checkpoint_json = dump(checkpoint)
                targets += [by_gse[g] for g in extra]
                await add_event(self.session, run.id, f"规则闸门占用深核名额，补充 {len(extra)} 条候选")
        if index >= len(targets) or (budget.max_deep_verify > 0 and deep_done >= budget.max_deep_verify):
            unfetched = max(0, len(targets) - index)
            not_selected = max(0, len(rows) - len(targets))
            await bump_counters(self.session, run, deep_skipped=unfetched + not_selected)
            self.job.status = "done"
            await enqueue_job(self.session, run.id, "assess")
            return
        self._guard(run, "soft")
        rd = targets[index]
        try:
            client: GeoFtpClient | None = None
            if settings.ncbi_mode == "mock" or self._demo(run):
                fixture = _soft_fixture(rd.gse)
                data = fixture.read_bytes()
                url = f"mock://soft-fixture/{fixture.name}"
            else:
                client = GeoFtpClient(api_key=(store.get(run.session_id).ncbi_api_key if store.get(run.session_id) else None))
                data, url = await client.fetch_soft(rd.gse)
            doc = parse_soft_bytes(data, max_bytes=settings.max_soft_bytes)
            parsed = series_as_dict(doc)
            write_snapshot(run.id, f"{rd.gse}_soft_meta.json", parsed)
            rd.soft_source = url
            rd.verification_status = "soft_incomplete" if parsed.get("truncated") else "soft_loaded"
            samples = parsed.get("samples") or []
            for sample in samples:
                await upsert_sample(self.session, rd.gse, sample, truncated=bool(parsed.get("truncated")))
            rd.gsm_count = len(samples) if not parsed.get("truncated") else rd.gsm_count
            rd.independent_donors = count_independent_donors(samples)
            rd.biosample_count = count_biosamples(samples)
            if client is not None:
                await self._record_suppl(rd, client)
            rd.donors_per_group_json = dump(
                donors_per_group(
                    samples,
                    spec.required_groups,
                    truncated=bool(parsed.get("truncated")),
                    organisms=spec.organisms,
                    control_type=spec.control_type,
                    spec=spec,
                )
            )
            for rel in parsed.get("relations") or []:
                self.session.add(
                    DatasetRelation(
                        id=new_id(),
                        gse=rd.gse,
                        relation_type="series_relation",
                        target=str(rel)[:80],
                        evidence=str(rel),
                    )
                )
            await add_evidence(
                self.session,
                run_id=run.id,
                gse=rd.gse,
                source_url=url,
                field_path="soft.Series_overall_design",
                text=str(parsed.get("overall_design") or ""),
            )
            for sample in samples:
                record = _sample_evidence_text(sample)
                gsm = str(sample.get("gsm") or "").strip()
                if not gsm or not record.strip():
                    continue
                await add_evidence(
                    self.session,
                    run_id=run.id,
                    gse=rd.gse,
                    source_url=url,
                    field_path=f"soft.sample.{gsm}.record",
                    text=record,
                )
            await add_event(self.session, run.id, f"{rd.gse} SOFT 元数据已解析，样本 {len(samples)}，截断={parsed.get('truncated')}")
            ds = await self.session.get(Dataset, rd.gse)
            study = load(ds.summary_json, {}) if ds else {}
            gate_summary = _gate_summary(study, parsed)
            failed = [] if parsed.get("truncated") else rule_gate_ids(spec, gate_summary, samples)
            if failed:
                evidence = await evidence_bundle(self.session, run.id, rd.gse)
                rules = bind_rule_evidence(rule_judgements(spec, gate_summary, samples), evidence)
                await self._mark_rule_gate(run, rd, rules, failed)
                await bump_counters(self.session, run, deep_gated=1)
            else:
                await bump_counters(self.session, run, deep_done=1)
        except GeoFetchError as exc:
            rd.verification_status = "soft_failed"
            rd.concerns = str(exc)
            rd.reason = f"深核选中但 GEO SOFT 下载失败（{exc}），未完成样本核验，建议稍后重跑。"
            await add_event(self.session, run.id, f"{rd.gse} SOFT 获取失败: {exc}", level="warn")
        self.job.status = "done"
        await enqueue_job(self.session, run.id, "deep_fetch", {"index": index + 1})

    async def _note_network_retries(self, run: Run, gse: str, llm: LLMProvider) -> None:
        count = int(getattr(llm, "network_retries", 0) or 0)
        reported = int(getattr(llm, "_retries_reported", 0) or 0)
        for number in range(reported + 1, count + 1):
            await add_event(self.session, run.id, f"{gse} 模型网络错误，第 {number} 次重试")
        llm._retries_reported = count

    async def _mark_rule_gate(self, run: Run, rd: RunDataset, rules: list[CriterionJudgement], failed: list[str]) -> None:
        prior = load(rd.first_assess_json, {})
        rd.category = "excluded"
        rd.reason = "硬条件失败（样本级规则，未调用模型）: " + ",".join(failed)
        rd.verification_status = "verified"
        rd.model_output_invalid = False
        rd.first_assess_json = dump(
            {
                "selection": prior.get("selection", {}),
                "rules": [item.model_dump() for item in rules],
                "model": None,
                "model_invalid": False,
                "model_incomplete": False,
                "rule_gate": True,
            }
        )
        await _replace_assessments(self.session, run.id, rd.gse, "assess_rules", rules, actor="rule")
        await _replace_assessments(self.session, run.id, rd.gse, "final", rules, actor="rule")
        await add_event(self.session, run.id, f"{rd.gse} 样本级规则已排除，跳过模型调用")

    async def _record_suppl(self, rd: RunDataset, client: GeoFtpClient) -> None:
        try:
            listing = await client.list_suppl(rd.gse)
        except Exception as exc:
            logger.warning("suppl listing failed for %s: %s", rd.gse, exc)
            rd.file_listing_checked = True
            rd.matrix_availability = "unchecked"
            return
        rd.file_listing_checked = True
        if listing.get("status") != "ok":
            rd.matrix_availability = "unchecked"
            return
        classified = classify_suppl_names(list(listing.get("names") or []))
        rd.matrix_availability = classified["matrix_availability"]
        rd.processed_data = classified["processed_data"]
        if classified["raw_data"] != "unknown":
            rd.raw_data = classified["raw_data"]

    async def step_assess(self, run: Run) -> None:
        run.stage = "verifying"
        spec = self._spec(run)
        rows = _review_queue(run, (await self.session.execute(select(RunDataset).where(RunDataset.run_id == run.id))).scalars().all())
        opened = _open_review(rows)
        if opened is None:
            self.job.status = "done"
            await enqueue_job(self.session, run.id, "finalize")
            return
        index, phase, rd = opened
        if phase != "assess":
            self.job.status = "done"
            await enqueue_job(self.session, run.id, phase, {"index": index})
            return
        sample_dicts = await _sample_dicts(self.session, rd.gse, spec=spec)
        ds = await self.session.get(Dataset, rd.gse)
        summary = load(ds.summary_json, {}) if ds else {}
        evidence = await evidence_bundle(self.session, run.id, rd.gse)
        _, coverage = fit_samples(sample_dicts, evidence=evidence, spec=spec, budget=self._sample_budget(run))
        truncated = any(s.get("coverage_incomplete") for s in sample_dicts) or not coverage.get("complete", True)
        rules = bind_rule_evidence(rule_judgements(spec, summary, sample_dicts, truncated=truncated), evidence)
        failed = rule_gate_ids(spec, summary, sample_dicts)
        if failed:
            await self._mark_rule_gate(run, rd, rules, failed)
            self.job.status = "done"
            nxt = _open_review(rows)
            if nxt is None:
                await enqueue_job(self.session, run.id, "finalize")
            else:
                await enqueue_job(self.session, run.id, nxt[1], {"index": nxt[0]})
            return
        checked: CheckedAssessment | None = None
        try:
            if await self._abandon_if_finished(run):
                return
            checked = await self._complete_assessment(
                run,
                prompt_name="assess_dataset",
                spec=spec,
                rd=rd,
                summary=summary,
                evidence=evidence,
                sample_dicts=sample_dicts,
                coverage=coverage,
            )
            if checked.invalid:
                rd.model_output_invalid = True
                await add_event(self.session, run.id, f"{rd.gse} 首次模型核验无效: {checked.error}", level="warn")
            elif checked.incomplete:
                await add_event(self.session, run.id, f"{rd.gse} 首次模型漏答: {checked.error}", level="warn")
        except WaitingForCredentials:
            raise
        except LLMError as exc:
            rd.model_output_invalid = True
            rd.concerns = f"模型请求失败（{exc.kind}）：{exc}"
            await add_event(self.session, run.id, f"{rd.gse} 首次模型核验无效: {exc}", level="warn")
        if await self._abandon_if_finished(run):
            return
        rd.first_assess_json = dump(
            {
                "selection": load(rd.first_assess_json, {}).get("selection", {}),
                "rules": [j.model_dump() for j in rules],
                "model": [j.model_dump() for j in checked.judgements] if checked else None,
                "model_invalid": bool(checked.invalid) if checked else rd.model_output_invalid,
                "model_incomplete": bool(checked.incomplete) if checked else True,
            }
        )
        if rd.verification_status == "soft_loaded":
            rd.verification_status = "assessed"
        await _replace_assessments(self.session, run.id, rd.gse, "assess_rules", rules, actor="rule")
        if checked:
            await _replace_assessments(self.session, run.id, rd.gse, "assess_model", checked.judgements, actor="model")
        self.job.status = "done"
        await enqueue_job(self.session, run.id, "verify", {"index": index})

    async def step_verify(self, run: Run) -> None:
        run.stage = "verifying"
        spec = self._spec(run)
        rows = _review_queue(run, (await self.session.execute(select(RunDataset).where(RunDataset.run_id == run.id))).scalars().all())
        opened = _open_review(rows)
        if opened is None:
            self.job.status = "done"
            await enqueue_job(self.session, run.id, "finalize")
            return
        index, phase, rd = opened
        if phase != "verify":
            self.job.status = "done"
            await enqueue_job(self.session, run.id, phase, {"index": index})
            return
        skip_llm = "model" in load(rd.verify_assess_json, {})
        evidence = await evidence_bundle(self.session, run.id, rd.gse)
        sample_dicts = await _sample_dicts(self.session, rd.gse, spec=spec)
        ds = await self.session.get(Dataset, rd.gse)
        summary = load(ds.summary_json, {}) if ds else {}
        _, coverage = fit_samples(sample_dicts, evidence=evidence, spec=spec, budget=self._sample_budget(run))
        truncated = any(s.get("coverage_incomplete") for s in sample_dicts) or not coverage.get("complete", True)
        verify_checked: CheckedAssessment | None = None
        stored = load(rd.verify_assess_json, {})
        if skip_llm and stored.get("model") is not None:
            verify_checked = CheckedAssessment(
                judgements=[CriterionJudgement.model_validate(x) for x in stored["model"]],
                invalid=bool(stored.get("invalid")),
                incomplete=bool(stored.get("incomplete")),
            )
        else:
            try:
                if await self._abandon_if_finished(run):
                    return
                verify_checked = await self._complete_assessment(
                    run,
                    prompt_name="verify_dataset",
                    spec=spec,
                    rd=rd,
                    summary=summary,
                    evidence=evidence,
                    sample_dicts=sample_dicts,
                    coverage=coverage,
                )
                if verify_checked.invalid:
                    rd.model_output_invalid = True
                    await add_event(self.session, run.id, f"{rd.gse} 复核模型无效: {verify_checked.error}", level="warn")
                elif verify_checked.incomplete:
                    await add_event(self.session, run.id, f"{rd.gse} 复核漏答: {verify_checked.error}", level="warn")
            except WaitingForCredentials:
                raise
            except LLMError as exc:
                rd.model_output_invalid = True
                rd.concerns = f"模型请求失败（{exc.kind}）：{exc}"
                await add_event(self.session, run.id, f"{rd.gse} 复核模型无效: {exc}", level="warn")
        if await self._abandon_if_finished(run):
            return
        if not skip_llm:
            rd.verify_assess_json = dump(
                {
                    "model": [j.model_dump() for j in verify_checked.judgements] if verify_checked else None,
                    "invalid": bool(verify_checked.invalid) if verify_checked else True,
                    "incomplete": bool(verify_checked.incomplete) if verify_checked else True,
                }
            )
        if verify_checked:
            await _replace_assessments(self.session, run.id, rd.gse, "verify_model", verify_checked.judgements, actor="model")
        rules = bind_rule_evidence(rule_judgements(spec, summary, sample_dicts, truncated=truncated), evidence)
        first_blob = load(rd.first_assess_json, {})
        first_checked = None
        if first_blob.get("model"):
            first_checked = CheckedAssessment(
                judgements=[CriterionJudgement.model_validate(x) for x in first_blob["model"]],
                invalid=bool(first_blob.get("model_invalid")),
                incomplete=bool(first_blob.get("model_incomplete")),
            )
        merged, conflicts, review_complete, merge_invalid = merge_final(
            spec, rules, first_checked, verify_checked, samples=sample_dicts, study=summary
        )
        rd.model_output_invalid = rd.model_output_invalid or merge_invalid
        rd.conflict_json = dump(conflicts)
        depth_complete = rd.verification_status in {"soft_loaded", "assessed"} and not any(
            sample.get("coverage_incomplete") for sample in sample_dicts
        )
        verified = depth_complete and review_complete and not conflicts and not rd.model_output_invalid
        category, reason = classify(
            spec,
            merged,
            verified=verified,
            conflict=bool(conflicts),
            model_invalid=rd.model_output_invalid,
            depth_complete=depth_complete,
            review_complete=review_complete,
        )
        kept = (await self._latest_overrides(run.id)).get(rd.gse)
        if kept is not None:
            rd.category = kept.new_category
            rd.reason = kept.reason or reason
        else:
            rd.category, rd.reason = category, reason
        rd.reason = _annotate_reason(
            rd.reason, rd, summary, sample_dicts, spec=spec, merged=merged, rules=rules
        )
        score, coverage_score, _ = soft_score(spec, merged)
        if rd.category == "needs_review" and rd.concerns and rd.concerns.startswith("模型请求失败") and kept is None:
            rd.reason = rd.concerns
        rd.soft_score = score
        rd.soft_coverage = coverage_score
        rd.hard_unknowns = sum(1 for j in merged if j.verdict == "unknown" and _is_hard(spec, j.criterion_id))
        if rd.verification_status in {"soft_loaded", "soft_incomplete", "assessed"}:
            rd.verification_status = "verified" if verified else "needs_review"
        await _replace_assessments(self.session, run.id, rd.gse, "final", merged, actor="merge")
        self.job.status = "done"
        nxt = _open_review(rows)
        if nxt is None:
            await enqueue_job(self.session, run.id, "finalize")
        else:
            await enqueue_job(self.session, run.id, nxt[1], {"index": nxt[0]})

    async def _complete_assessment(
        self,
        run: Run,
        *,
        prompt_name: str,
        spec: ResearchSpec,
        rd: RunDataset,
        summary: dict[str, Any],
        evidence: list[dict[str, Any]],
        sample_dicts: list[dict[str, Any]],
        coverage: dict[str, Any],
    ) -> CheckedAssessment:
        llm = self._llm(run)
        if await self._peer_cancelled(run):
            raise StopForCancel()
        user = json.dumps(
            judge_user_payload(
                spec, rd.gse, summary=summary, evidence=evidence, samples=sample_dicts,
                budget=self._sample_budget(run),
            ),
            ensure_ascii=False,
        )
        system = load_prompt(prompt_name)
        self._guard_review(run, prompt_name, input_tokens=estimate_tokens(system) + estimate_tokens(user))
        try:
            raw, usage = await llm.complete_json(
                prompt_name=prompt_name,
                system=system,
                user=user,
                schema=None,
                max_output_tokens=self._budget(run).max_completion_tokens,
            )
            checked = check_model_assessment(
                spec, raw, evidence, samples=sample_dicts, study=summary, sample_coverage=coverage
            )
            if checked.invalid and not llm.mock:
                await add_event(self.session, run.id, f"{rd.gse} 开始格式修复")
                try:
                    return await self._repair_assessment(
                        run,
                        llm,
                        prompt_name=prompt_name,
                        user=user,
                        previous_raw=raw,
                        spec=spec,
                        evidence=evidence,
                        sample_dicts=sample_dicts,
                        summary=summary,
                        coverage=coverage,
                        gse=rd.gse,
                    )
                except BudgetStop:
                    raise
                except Exception as exc:
                    logger.exception("format repair failed")
                    await add_event(self.session, run.id, f"{rd.gse} 格式修复失败: {exc}", level="warn")
                    return checked
            return checked
        finally:
            await self._note_network_retries(run, rd.gse, llm)
            if getattr(llm, "billing_uncertain", False):
                run.duplicate_billing_risk = True

    async def _repair_assessment(
        self,
        run: Run,
        llm: LLMProvider,
        *,
        prompt_name: str,
        user: str,
        previous_raw: dict[str, Any],
        spec: ResearchSpec,
        evidence: list[dict[str, Any]],
        sample_dicts: list[dict[str, Any]],
        summary: dict[str, Any],
        coverage: dict[str, Any],
        gse: str,
    ) -> CheckedAssessment:
        if await self._peer_cancelled(run):
            raise StopForCancel()
        try:
            self._guard(run, "llm")
        except BudgetStop:
            await add_event(self.session, run.id, f"{gse} 格式修复因预算跳过", level="warn")
            return check_model_assessment(
                spec, previous_raw, evidence, samples=sample_dicts, study=summary, sample_coverage=coverage
            )
        repair_user = json.dumps(
            {
                "instruction": "上一次输出缺字段或不符合 JSON 契约。只补全 judgements，每条必须含 verdict（pass|fail|unknown）。不要编造新的科学结论。",
                "previous_output": previous_raw,
                "original_task": json.loads(user),
            },
            ensure_ascii=False,
        )
        try:
            raw2, usage2 = await llm.complete_json(
                prompt_name=prompt_name,
                system=load_prompt(prompt_name) + "\n\n这是一次受预算限制的格式修复。",
                user=repair_user,
                schema=None,
                max_output_tokens=min(self._budget(run).max_completion_tokens, 2048),
            )
            repaired = check_model_assessment(
                spec, raw2, evidence, samples=sample_dicts, study=summary, sample_coverage=coverage
            )
            if repaired.invalid:
                await add_event(self.session, run.id, f"{gse} 格式修复后仍不符合契约: {repaired.error}", level="warn")
            else:
                await add_event(self.session, run.id, f"{gse} 格式修复成功")
            return repaired
        except LLMError as exc:
            await add_event(self.session, run.id, f"{gse} 格式修复失败: {exc}", level="warn")
            return check_model_assessment(
                spec, previous_raw, evidence, samples=sample_dicts, study=summary, sample_coverage=coverage
            )

    async def step_finalize(self, run: Run) -> None:
        run.stage = "exporting"
        counters = load(run.counters_json, {})
        n = len((await self.session.execute(select(RunDataset).where(RunDataset.run_id == run.id))).scalars().all())
        counters["unique_gse"] = n
        run.counters_json = dump(counters)
        if run.cancel_requested:
            run.status = "cancelled"
        elif run.stop_reason:
            run.status = "partial"
        else:
            run.status = "completed"
            run.stop_reason = run.stop_reason or "正常结束"
        run.finished_at = datetime.now(timezone.utc)
        leftover = (
            await self.session.execute(
                select(Job).where(
                    Job.run_id == run.id,
                    Job.id != self.job.id,
                    Job.status.in_(["queued", "leased", "waiting_credentials"]),
                )
            )
        ).scalars().all()
        for item in leftover:
            item.status = "cancelled"
            item.last_error = "任务已结束"
        self.job.status = "done"
        await add_event(self.session, run.id, f"任务结束：{run.status}，唯一 GSE {n}")

    async def _abandon_if_finished(self, run: Run) -> bool:
        if run.status in TERMINAL:
            self.job.status = "cancelled"
            self.job.last_error = "任务已结束，忽略迟到步骤"
            await add_event(self.session, run.id, f"忽略迟到步骤 {self.job.step}，任务已是 {run.status}")
            return True
        try:
            from app.db.session import SessionLocal

            async with SessionLocal() as peek:
                peer = await peek.get(Run, run.id)
                status = peer.status if peer else None
        except Exception:
            return False
        if status in TERMINAL:
            run.status = status
            self.job.status = "cancelled"
            self.job.last_error = "任务已结束，忽略迟到步骤"
            await add_event(self.session, run.id, f"忽略迟到步骤 {self.job.step}，任务已是 {status}")
            return True
        return False

    async def _peer_cancelled(self, run: Run) -> bool:
        try:
            from app.db.session import SessionLocal

            async with SessionLocal() as peek:
                peer = await peek.get(Run, run.id)
        except Exception:
            return bool(run.cancel_requested)
        if peer is None or not peer.cancel_requested:
            return False
        run.cancel_requested = True
        if run.status not in TERMINAL:
            run.status = "cancelled"
            run.stop_reason = run.stop_reason or "用户取消"
            run.finished_at = datetime.now(timezone.utc)
        return True

    async def _latest_overrides(self, run_id: str) -> dict[str, Override]:
        rows = (
            await self.session.execute(
                select(Override).where(Override.run_id == run_id).order_by(Override.created_at.asc(), Override.id.asc())
            )
        ).scalars().all()
        return {row.gse: row for row in rows}


def _screen_summary(ds: Dataset | None) -> dict[str, Any]:
    summary = load(ds.summary_json, {}) if ds else {}
    if ds is None:
        return summary
    if not summary.get("gdstype"):
        summary["gdstype"] = ds.gdstype or ""
    if not summary.get("taxon"):
        summary["taxon"] = ds.taxon or ""
    if not summary.get("title"):
        summary["title"] = ds.title or ""
    if not summary.get("summary"):
        summary["summary"] = ds.summary or ""
    return summary


async def hydrate_credentials(session_id: str) -> None:
    if not session_id:
        return
    existing = store.get(session_id)
    if existing:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{settings.api_url.rstrip('/')}/internal/credentials/{session_id}",
                headers={"X-Internal-Token": settings.internal_token},
            )
    except httpx.HTTPError:
        return
    if response.status_code == 404:
        # Missing session is empty creds, not a terminal wait. Live LLM still
        # raises WaitingForCredentials from _llm when a Key is actually required.
        return
    if response.status_code >= 400:
        return
    data = response.json()
    store.update(session_id, **{k: v for k, v in data.items() if v is not None})


def _qhash(term: str) -> str:
    return hashlib.sha256(term.encode("utf-8")).hexdigest()[:24]


def _add_tokens(run: Run, usage: dict[str, Any], *, estimate_chars: int = 0) -> None:
    cur = load(run.token_usage_json, {"prompt_tokens": 0, "completion_tokens": 0, "estimated": False})
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if prompt is None:
        prompt = estimate_tokens("x" * estimate_chars) if estimate_chars else 32
        cur["estimated"] = True
    if completion is None:
        completion = 32
        cur["estimated"] = True
    run.token_usage_json = dump(add_usage(cur, {**usage, "prompt_tokens": prompt, "completion_tokens": completion}))


def _llm_targets(rows: list[RunDataset]) -> list[RunDataset]:
    """Deep-fetched GSE only. Keep rows after verify mutates status so index walks stay stable."""
    return [r for r in rows if r.verification_status in LLM_DATASET_STATUSES]


def _review_queue(run: Run, rows: list[RunDataset]) -> list[RunDataset]:
    by_gse = {r.gse: r for r in _llm_targets(rows)}
    targets = load(run.checkpoint_json, {}).get("deep_targets") or []
    ordered = [by_gse[g] for g in targets if g in by_gse]
    seen = {r.gse for r in ordered}
    return ordered + [r for r in _llm_targets(rows) if r.gse not in seen]


def _open_review(rows: list[RunDataset]) -> tuple[int, str, RunDataset] | None:
    for index, rd in enumerate(rows):
        if "model" not in load(rd.first_assess_json, {}):
            return index, "assess", rd
        if rd.verification_status not in {"verified", "needs_review"}:
            return index, "verify", rd
    return None


def _is_hard(spec: ResearchSpec, criterion_id: str) -> bool:
    return any(c.criterion_id == criterion_id and c.priority == "hard" for c in spec.inclusion_criteria)


def _soft_fixture(gse: str) -> Path:
    root = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
    named = root / f"{gse}_metadata.soft"
    if named.exists():
        return named
    return root / "GSE1000_metadata.soft"


async def _sample_dicts(session: AsyncSession, gse: str, *, spec: ResearchSpec | None = None) -> list[dict[str, Any]]:
    samples = (await session.execute(select(Sample).where(Sample.gse == gse))).scalars().all()
    out: list[dict[str, Any]] = []
    for s in samples:
        attrs = load(s.attrs_json, {})
        out.append(
            {
                "gsm": s.gsm,
                "title": s.title,
                "organism": s.organism,
                "source_name": s.source_name,
                "donor_key": s.donor_key,
                "group_label": s.group_label,
                "library_strategy": attrs.get("library_strategy") or s.library_strategy,
                "library_source": attrs.get("library_source") or "",
                "protocol": attrs.get("protocol") or "",
                "protocol_fields": attrs.get("protocol_fields") or {},
                "characteristics": load(s.characteristics_json, []),
                "coverage_incomplete": s.coverage_incomplete,
            }
        )
    if spec is not None:
        for row in out:
            row["group_label"] = infer_group_label(row, spec=spec)
    return out


def _gate_summary(study: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    gdstype = study.get("gdstype") or parsed.get("type") or ""
    return {
        **study,
        "title": study.get("title") or parsed.get("title") or "",
        "summary": study.get("summary") or parsed.get("summary") or "",
        "overall_design": parsed.get("overall_design") or study.get("overall_design") or "",
        "gdstype": gdstype,
        "taxon": study.get("taxon") or "",
    }


def _title_individual_count(samples: list[dict[str, Any]]) -> int | None:
    # One-cell-per-GSM series carry chip/well/index codes in titles, not individuals.
    if len(samples) > 200:
        return None
    noise = re.compile(
        r"utx|lps|il-?1b|st\d+|rep\d+|r\d+$|_\d+h|(?<![A-Za-z0-9])S\d{1,3}(?![A-Za-z0-9])|(?<![A-Za-z])CD\d+[a-z]?",
        re.I,
    )
    token = re.compile(r"[A-Za-z]{1,4}\d{1,3}")
    found: set[str] = set()
    for sample in samples:
        title = noise.sub(" ", str(sample.get("title") or ""))
        found.update(token.findall(title))
    # Donor codes come in series (P1, P2, ...); lone gene/antibody names (OX40, PDL1) do not.
    prefixes = Counter(re.match(r"[A-Za-z]+", item).group().upper() for item in found)
    count = sum(1 for item in found if prefixes[re.match(r"[A-Za-z]+", item).group().upper()] >= 2)
    if count < 2 or not samples or count > len(samples) // 2:
        return None
    return count


_PEDIATRIC_RE = re.compile(
    r"\b(?:fetal|fetus|foetal|embryo\w*|newborn|neonat\w*|infant|toddler|child\w*|juvenile|adolescen\w*|pediatric|paediatric)\b",
    re.I,
)
_PERSONAL_KEY_RE = re.compile(r"\b(?:age|sex|gender|bmi|hba1c|ethnic\w*|race|pmi)\b")
_AGE_KEY_RE = re.compile(r"\bage|\bstage|develop")


def _char_map(sample: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in sample.get("characteristics") or []:
        if isinstance(row, dict) and row.get("key"):
            out[str(row["key"]).strip().lower()] = str(row.get("value") or "").strip()
    return out


def _repeated_sample_note(cohort: list[dict[str, Any]]) -> str:
    """Detect several GSMs per donor that differ only by one prep/condition field."""
    if len(cohort) < 4 or all(s.get("donor_key") for s in cohort):
        return ""
    maps = [_char_map(s) for s in cohort]
    keys = set.intersection(*(set(m) for m in maps))
    if not any(_PERSONAL_KEY_RE.search(k) for k in keys):
        return ""
    for key in sorted(keys):
        if _PERSONAL_KEY_RE.search(key) or len({m[key] for m in maps}) < 2:
            continue
        buckets: dict[tuple, set[str]] = {}
        sizes: dict[tuple, int] = {}
        for m in maps:
            sig = tuple(sorted((k, v) for k, v in m.items() if k != key))
            buckets.setdefault(sig, set()).add(m[key])
            sizes[sig] = sizes.get(sig, 0) + 1
        if len(buckets) * 2 <= len(cohort) and all(len(vals) == sizes[sig] for sig, vals in buckets.items()):
            return f"疑似同一供体的多份样本（按“{key}”区分），估计约 {len(buckets)} 位供体，不应按 GSM 数当独立样本。"
    return ""


def _age_mismatch_note(cohort: list[dict[str, Any]], labels: dict[str, str]) -> str:
    young: dict[str, int] = {}
    total: dict[str, int] = {}
    for sample in cohort:
        label = labels.get(str(sample.get("gsm") or "").upper())
        if not label:
            continue
        total[label] = total.get(label, 0) + 1
        values = " ".join(v for k, v in _char_map(sample).items() if _AGE_KEY_RE.search(k))
        if _PEDIATRIC_RE.search(values):
            young[label] = young.get(label, 0) + 1
    if not young or len(total) < 2 or all(young.get(g, 0) for g in total):
        return ""
    shown = "、".join(f"{g} {young[g]}/{total[g]}" for g in sorted(young))
    return f"年龄段不匹配：{shown} 个 GSM 来自胎儿/儿童/青少年供体，另一组没有。"


_DROPLET_RE = re.compile(r"\b10x\b|chromium|droplet|drop-?seq|indrop|seq-?well|\bbd rhapsody\b", re.I)


def _single_cell_gsm_note(cohort: list[dict[str, Any]], summary: dict[str, Any] | None = None) -> str:
    """One-cell-per-GSM series must not be read as one person per GSM."""
    if len(cohort) < 50 or any(sample.get("donor_key") for sample in cohort):
        return ""
    # Droplet platforms put a whole library (thousands of cells) in one GSM.
    text = " ".join(str((summary or {}).get(key) or "") for key in ("summary", "overall_design"))
    text += " ".join(str(sample.get("protocol") or "") for sample in cohort[:20])
    if _DROPLET_RE.search(text):
        return ""

    single = sum("single" in str(sample.get("library_source") or "").casefold() for sample in cohort)
    # Bulk cohorts also carry one fixed "cell type" (PBMC, CD14 monocytes); per-cell annotation varies.
    cell_types = {
        value.casefold()
        for sample in cohort
        for key, value in _char_map(sample).items()
        if "cell" in key and "type" in key and value
    }
    if single * 2 < len(cohort) and len(cell_types) < 3:
        return ""
    return "一个 GSM 多半是一个细胞而不是一位供体，队列规模不能按 GSM 数理解。"


def _sorted_fraction_note(cohort: list[dict[str, Any]], spec: ResearchSpec) -> str:
    if not cohort:
        return ""
    named = [hit for hit in (sorted_fraction(sample) for sample in cohort) if hit]
    if len(named) * 2 <= len(cohort):
        return ""
    shown = named[0]
    if shown.casefold() in (spec.original_request or "").casefold():
        return ""
    return f"样本是从组织中分选的 {shown}，不是整块组织，请确认是否符合需求。"


def _activity_mix_note(cohort: list[dict[str, Any]], labels: dict[str, str]) -> str:
    active = inactive = False
    for sample in cohort:
        gsm = str(sample.get("gsm") or "").upper()
        if labels.get(gsm) not in {"case", "lesion", "disease"}:
            continue
        for row in sample.get("characteristics") or []:
            if not isinstance(row, dict):
                continue
            value = str(row.get("value") or "").casefold()
            if re.search(r"\binactive\b|缓解", value):
                inactive = True
            elif re.search(r"\bactive\b|活动", value):
                active = True
    if active and inactive:
        return "病例组混有活动期与缓解期样本。"
    return ""


def _case_only_note(
    samples: list[dict[str, Any]],
    spec: ResearchSpec | None,
    merged: list[CriterionJudgement] | None,
) -> str:
    if spec is None or not merged or not samples or "control" not in (spec.required_groups or []):
        return ""
    groups = next((item for item in merged if item.criterion_id == "groups"), None)
    if groups is None or groups.verdict == "pass":
        return ""
    labels = {infer_group_label(sample, spec=spec) for sample in samples}
    if not labels or not labels <= {"case", "lesion", "disease"}:
        return ""
    return "系列只有病例样本、没有对照组：可做病例内部分析，不能直接做病例-对照比较。"


def _mixed_species_note(samples: list[dict[str, Any]], spec: ResearchSpec | None) -> str:
    if spec is None or not spec.organisms or not samples:
        return ""
    other = Counter(
        str(s.get("organism") or "").strip()
        for s in samples
        if _organism_ok(s, spec.organisms) is False
    )
    if not other:
        return ""
    kept = len(samples) - sum(other.values())
    names = "、".join(f"{name} {n}" for name, n in other.most_common())
    return f"系列混有其他物种（{names} 个 GSM），结论只覆盖目标物种的 {kept} 个 GSM。"


_BATCH_KEY = re.compile(
    r"\b(?:batch|run|lane|flowcell|plate)\b|flow cell|sequencing date|library[_ ]prep[_ ]date|processing date",
    re.I,
)
_QC_VALUE = re.compile(r"^(?:dropped|excluded|failed qc|qc fail(?:ed)?|low quality|removed)$", re.I)
_QC_KEY = re.compile(r"qc|pass_qc|in_.*filtered", re.I)
_QC_FAIL = re.compile(r"^(?:false|fail|no)$", re.I)
_RAW_WITHHELD = re.compile(
    r"raw (?:data|files?|reads?|sequenc\w*)\b.{0,80}\b(?:not|were not|was not|are not)\b.{0,40}\b(?:submitted|deposited|available|provided|uploaded)",
    re.I,
)
_CONTROLLED_ACCESS = re.compile(
    r"\b(?:dbgap|ega|egas\d+|phs\d{6}|controlled[- ]access|restricted access|data use agreement)\b",
    re.I,
)


def _ordered_labels(counts: dict[str, int]) -> list[str]:
    return sorted(counts, key=lambda label: (0 if label in {"case", "lesion", "disease"} else 1, label))


def _rule_group_counts(
    samples: list[dict[str, Any]],
    spec: ResearchSpec,
    summary: dict[str, Any],
    rules: list[CriterionJudgement],
) -> dict[str, int] | None:
    groups = next(
        (item for item in rules if item.criterion_id == "groups" and item.verdict == "pass" and item.qualifying_gsms),
        None,
    )
    if groups is None:
        return None
    listed = {str(gsm).upper() for gsm in groups.qualifying_gsms}
    counts: dict[str, int] = {}
    for sample in samples:
        gsm = str(sample.get("gsm") or "").upper()
        if gsm not in listed or not _sample_fits_all_hard(sample, spec, summary, rules):
            continue
        label = infer_group_label(sample, spec=spec)
        if label:
            counts[label] = counts.get(label, 0) + 1
    return counts


def _batch_confound_note(cohort: list[dict[str, Any]], labels: dict[str, str]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for sample in cohort:
        label = labels.get(str(sample.get("gsm") or "").upper())
        if label:
            grouped.setdefault(label, []).append(sample)
    usable = {label: rows for label, rows in grouped.items() if len(rows) >= 3}
    if len(usable) < 2:
        return ""
    seen: list[str] = []
    for sample in cohort:
        for key in _char_map(sample):
            if key not in seen and _BATCH_KEY.search(key):
                seen.append(key)
    chosen = ""
    for key in seen:
        values = {_char_map(sample).get(key, "") for rows in usable.values() for sample in rows}
        values.discard("")
        if len(values) >= 2:
            chosen = key
            break
    if not chosen:
        return ""
    dist = {
        label: Counter(value for sample in rows if (value := _char_map(sample).get(chosen, "")))
        for label, rows in usable.items()
    }
    sets = [set(counts) for counts in dist.values() if counts]
    if len(sets) >= 2 and not set.intersection(*sets):
        return f"批次与分组完全重合（按“{chosen}”）：组间差异无法与批次效应区分。"
    best: tuple[float, str, str] | None = None
    for label, counts in dist.items():
        total = sum(counts.values())
        for value, count in counts.items():
            if not total or count / total < 0.5:
                continue
            for other in dist:
                other_total = sum(dist[other].values())
                if other == label or not other_total:
                    continue
                other_share = dist[other].get(value, 0) / other_total
                if other_share <= 0.1:
                    gap = count / total - other_share
                    if best is None or gap > best[0]:
                        best = (gap, label, value)
    if best:
        return f"批次与分组部分重合（按“{chosen}”）：{best[1]} 多在 {best[2]}，建议把批次纳入模型。"
    return ""


def _qc_dropped_note(samples: list[dict[str, Any]]) -> str:
    dropped = subset = 0
    dropped_example = subset_example = ""
    for sample in samples:
        for row in sample.get("characteristics") or []:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or "")
            value = str(row.get("value") or "").strip()
            if _QC_VALUE.match(value) or (re.search(r"qc", key, re.I) and _QC_FAIL.match(value)):
                dropped += 1
                dropped_example = dropped_example or f"{key}: {value}"
                break
            if _QC_KEY.search(key) and _QC_FAIL.match(value):
                subset += 1
                subset_example = subset_example or f"{key}: {value}"
                break
    notes = []
    if dropped:
        notes.append(f"{dropped}/{len(samples)} 个 GSM 被提交者标为质控剔除（“{dropped_example}”），下载后应按该字段过滤。")
    if subset:
        notes.append(f"{subset}/{len(samples)} 个 GSM 不在提交者的分析子集里（“{subset_example}”），复现原文分析时应按该字段过滤。")
    return " ".join(notes)


def _raw_access_note(summary: dict[str, Any]) -> str:
    text = " ".join(str(summary.get(key) or "") for key in ("title", "summary", "overall_design"))
    if _RAW_WITHHELD.search(text) or _CONTROLLED_ACCESS.search(text):
        return "提交者说明原始测序数据未公开或需受控申请，GEO 上通常只有处理后矩阵。"
    return ""


def _annotate_reason(
    reason: str,
    rd: RunDataset,
    summary: dict[str, Any],
    samples: list[dict[str, Any]],
    *,
    spec: ResearchSpec | None = None,
    merged: list[CriterionJudgement] | None = None,
    rules: list[CriterionJudgement] | None = None,
) -> str:
    extra: list[str] = []
    text = reason or ""
    cohort_samples: list[dict[str, Any]] = []
    note = mixed_omics_note(summary, samples)
    if note and note not in text:
        extra.append(note)
    note = _case_only_note(samples, spec, merged)
    if note and note not in text:
        extra.append(note)
    note = _mixed_species_note(samples, spec)
    if note and note not in text:
        extra.append(note)
    if spec is not None and merged:
        groups = next(
            (item for item in merged if item.criterion_id == "groups" and item.verdict == "pass" and item.qualifying_gsms),
            None,
        )
        if groups is not None:
            by_gsm = {str(sample.get("gsm") or "").upper(): sample for sample in samples}
            counts: dict[str, int] = {}
            donors: dict[str, set[str]] = {}
            labels: dict[str, str] = {}
            for gsm in groups.qualifying_gsms:
                sample = by_gsm.get(str(gsm).upper())
                label = infer_group_label(sample, spec=spec) if sample is not None else None
                if label:
                    counts[label] = counts.get(label, 0) + 1
                    labels[str(gsm).upper()] = label
                    cohort_samples.append(sample)
                    if sample.get("donor_key"):
                        donors.setdefault(label, set()).add(str(sample["donor_key"]))
            if counts:
                ordered = _ordered_labels(counts)
                shown = " / ".join(f"{label} {counts[label]}" for label in ordered)
                cohort = f"适用队列：{shown} 个 GSM。"
                if rules:
                    rule_counts = _rule_group_counts(samples, spec, summary, rules)
                    if rule_counts and any(
                        rule_counts.get(label, 0) > counts.get(label, 0)
                        for label in set(rule_counts) | set(counts)
                    ):
                        rule_shown = " / ".join(
                            f"{label} {rule_counts[label]}" for label in _ordered_labels(rule_counts)
                        )
                        cohort = f"适用队列：{shown} 个 GSM（模型列出）；按样本字段规则为 {rule_shown}，差异样本请人工确认。"
                if cohort not in text:
                    extra.append(cohort)
                if all(sample.get("donor_key") for sample in cohort_samples):
                    donor_text = " / ".join(f"{label} {len(donors.get(label, ()))}" for label in ordered)
                    donor_line = f"独立供体：{donor_text}。"
                    if donor_line not in text:
                        extra.append(donor_line)
                    effective = {label: len(donors.get(label, ())) for label in ordered}
                else:
                    effective = dict(counts)
                    cell_note = _single_cell_gsm_note(cohort_samples, summary)
                    if cell_note and cell_note not in text:
                        extra.append(cell_note)
                for note in (_repeated_sample_note(cohort_samples), _age_mismatch_note(cohort_samples, labels)):
                    if note and note not in text:
                        extra.append(note)
                if any(count < 3 for count in effective.values()):
                    small = "每组样本很少，统计效力有限。"
                    if small not in text:
                        extra.append(small)
                for note in (
                    _sorted_fraction_note(cohort_samples, spec),
                    _activity_mix_note(cohort_samples, labels),
                    _batch_confound_note(cohort_samples, labels),
                ):
                    if note and note not in text:
                        extra.append(note)
    for note in (_qc_dropped_note(samples), _raw_access_note(summary)):
        if note and note not in text:
            extra.append(note)
    if rd.independent_donors is None and rd.biosample_count:
        donor = f"独立供体字段不完整；{rd.biosample_count} 个 BioSample 只是未去重的上限。"
        if donor not in text:
            extra.append(donor)
        individuals = _title_individual_count(cohort_samples or samples)
        if individuals:
            hint = f"样本名提示约 {individuals} 位个体（仅供参考）。"
            if hint not in text:
                extra.append(hint)
    if rd.file_listing_checked and rd.matrix_availability not in {None, "", "unknown", "unchecked"}:
        matrix = f"补充文件检查：{rd.matrix_availability}。"
        if matrix not in text:
            extra.append(matrix)
    if not extra:
        return text
    return (text + " " + " ".join(extra)).strip()


def _sample_evidence_text(sample: dict[str, Any]) -> str:
    chars = sample.get("characteristics") or []
    bits: list[str] = []
    if isinstance(chars, list):
        for row in chars:
            if isinstance(row, dict):
                key = row.get("key") or row.get("tag") or ""
                val = row.get("value") or row.get("raw") or ""
                bits.append(f"{key}: {val}".strip(": "))
            else:
                bits.append(str(row))
    gsm = str(sample.get("gsm") or "")
    return (
        f"{gsm} title={sample.get('title') or ''} organism={sample.get('organism') or ''} "
        f"source_name={sample.get('source_name') or ''} library_strategy={sample.get('library_strategy') or ''} "
        f"library_source={sample.get('library_source') or ''} protocol={sample.get('protocol') or ''} "
        f"donor_key={sample.get('donor_key') or ''} "
        f"group_label={sample.get('group_label') or ''} characteristics={'; '.join(bits)}"
    )[:4000]


async def _replace_assessments(
    session: AsyncSession,
    run_id: str,
    gse: str,
    stage: str,
    judgements: list[CriterionJudgement],
    *,
    actor: str = "",
) -> None:
    existing = (
        await session.execute(
            select(Assessment).where(Assessment.run_id == run_id, Assessment.gse == gse, Assessment.stage == stage)
        )
    ).scalars().all()
    for row in existing:
        await session.delete(row)
    for item in judgements:
        session.add(
            Assessment(
                id=new_id(),
                run_id=run_id,
                gse=gse,
                criterion_id=item.criterion_id,
                verdict=item.verdict,
                stage=stage,
                evidence_ids=dump(item.evidence_ids),
                quote=item.quote or (item.quotes[0] if item.quotes else ""),
                quotes_json=dump(item.quotes),
                reason=item.reason,
                judge_source=item.judge_source or actor,
                actor=actor,
                support_text=item.support_text,
                clue_only=item.clue_only,
                qualifying_gsms_json=dump(item.qualifying_gsms),
            )
        )


async def parse_spec_with_optional_llm(text: str, session_id: str, *, on_usage=None) -> ResearchSpec:
    base = heuristic_parse(text)
    creds = store.get(session_id)
    mock = settings.llm_mode == "mock"
    if not mock and (not creds or not creds.has_llm_key()):
        return base
    llm = LLMProvider(creds or store.get_or_create(session_id), mock=mock, on_usage=on_usage)
    try:
        payload, _usage = await llm.complete_json(
            prompt_name="parse_research_spec",
            system=load_prompt("parse_research_spec"),
            user=text,
            schema=None,
        )
        return merge_model_parse(base, payload)
    except LLMError:
        return base
