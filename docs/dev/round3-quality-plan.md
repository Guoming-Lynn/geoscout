# 第三轮质量升级方案（给执行模型）

来源：2026-09-23 第二轮 DeepSeek Flash 三课题实测（数据在 `data/flash-rerun-20260923/`，库文件 `geoscout.db`，汇总 `summary.json`）。
目标：减少"好数据被压成待核实"和"推荐理由夸大"，同时适度提高 Medium 预算。
执行顺序按本文 A→J。每个工作包都要先写失败的测试，再改代码，最后跑全量测试。

---

## 0. 背景与证据

三个课题（`data/flash-rerun-20260923/run_three.py`）：

- AD brain：`human primary Alzheimer disease brain RNA-seq with disease and control`
- T2D islet：`human primary type 2 diabetes islet RNA-seq with disease and control`
- RA PBMC：`human primary rheumatoid arthritis PBMC RNA-seq with disease and control`

解析结果都是 `assay_types=["rna_seq_generic"]`、`tissue_required=True`、`sample_source="primary"`、`required_groups=["case","control"]`。

第二轮结果中需要修的具体数据集（执行者可直接在库里查到样本）：

| GSE | 当前结果 | 实际情况 | 根因（工作包） |
|---|---|---|---|
| GSE86468 | 待核实，groups unknown | 胰岛 bulk，`disease: Type 2 diabetic` 9 / `disease: Non-diabetic` 15 | 规则分组器不认 `Type 2 diabetic`（A） |
| GSE164416 | 待核实，assay/groups 被截断降级 | 133 例活体胰岛，`diabetes status: T2D` 39 / `ND` 18（另有 IGT/IFG/T3cD） | `diabetes status` 不是分组字段、`ND` 不认；样本超 4 万字符上限（A、D） |
| GSE81608 | 待核实，截断降级 | 1600 个单细胞、18 位供体，`condition: T2D / non-diabetic` | 样本超上限（D） |
| GSE291978 | 待核实，tissue/groups unknown | PBMC，`sample group: rheumatoid arthritis (RA)` 3 / `HCs` 3；`tissue: blood` + `cell type: PBMC` | `HCs` 不认；`cell type` 不参与组织匹配（A、E） |
| GSE189136 | **推荐**，理由写"17 RA vs 2 Healthy" | 未处理的只有 RA 2 / Healthy 2；其余 15 份是 3 位 RA 供体的体外 LPS、IL-1β、ST2825 处理 | 没看 `treatment` 字段（B） |
| GSE309036 | 待核实，模型网络错误 | 全部样本 `miRNA-Seq`，应直接排除 | 规则层 `rna_seq_generic` 从不看样本；网络错误不重试（C、F） |
| GSE163605 | 待核实（正确） | 样本全是健康人；且 CD4+/CD8+/CD14+ 分选细胞被当成 PBMC | 分选亚群误判为 PBMC（E） |
| GSE317746 | 推荐（基本正确） | 16 份全是 10x snRNA-seq，AD 4 / Control 4；标题写蛋白质组 | 提示"系列同时包含 proteomics"不对（G） |

第二轮 token：AD 98,776（含估算）、T2D 110,677、RA 83,923；每个深审数据集约 1.6–1.8 万 token（首评 + 复核两次调用）。

---

## 通用约束

- 只改 `backend/`、`frontend/`（仅 mock 和文档相关）、`docs/`。不要改 `data/` 下已有的运行结果。
- 保持现有保守原则：摘要里出现某词不能判 pass；缺样本证据不能判 fail；混合研究必须列出 GSM 子集。
- 不要放宽"推荐"门槛本身（`classify()` 的 `ready` 逻辑），只修规则识别和截断处理。
- 代码风格照旧：中文 reason 文案、少注释、不写解释改动的注释。
- API Key 只通过环境变量 `DEEPSEEK_API_KEY` 传入，不写进任何文件、测试或提交。
- 测试命令：`cd backend; python -m pytest -q`；前端 `cd frontend; npm test`、`npm run build`。每个工作包结束都跑一次后端全量。

---

## A. 分组识别修复（`backend/app/pipeline/donors.py`）【P0】

### A1. 分组字段名模糊匹配

`parse_sample_traits()` 里多处用 `key in GROUP_KEYS` 判断（第 124、133 行）。新增函数：

```python
_GROUP_KEY_PARTS = ("status", "diagnos", "group", "condition", "disease", "phenotype", "cohort", "state")

def _is_group_key(key: str) -> bool:
    k = key.strip().lower()
    return k in GROUP_KEYS or any(part in k for part in _GROUP_KEY_PARTS)
```

把第 124、133 行的 `key in GROUP_KEYS` 换成 `_is_group_key(key)`。`genotype`、`treatment` 继续按原集合处理，不受模糊匹配影响（第 121 行的特殊逻辑保持不变）。

### A2. 疾病别名补全

`DISEASE_LABELS` 改为：

```python
DISEASE_LABELS = {
    "alzheimer disease": ["AD", "sAD", "LOAD", "EOAD", "SAD", "MAD", "Alzheimer's", "Alzheimers"],
    "type 2 diabetes": ["T2D", "T2DM", "type 2 diabetic", "T2 diabetic", "diabetic"],
    "rheumatoid arthritis": ["RA", "Rheumatiod arthritis", "rhematoid arthritis"],
    "COVID-19": ["COVID", "COVID19", "SARS-CoV-2"],
}
```

注意：`diabetic` 只有 8 个字符，会走 `len(_fold(a)) >= 5` 分支而在任何字段生效。`Non-diabetic` 折叠后是 `non diabetic`，第 126 行的否定正则会把它判为 `absent`，这是期望行为。必须加测试确认 `Non-diabetic` 得到 control、`Type 2 diabetic` 得到 case。

### A3. 疾病专属对照标签

新增映射，只在 `_is_group_key(key)` 为真且 spec 疾病匹配时生效，**精确匹配折叠后的整个值**：

```python
DISEASE_CONTROL_LABELS = {
    "type 2 diabetes": ["nd", "non diabetic", "nondiabetic", "non t2d", "ngt", "normoglycemic", "normal glucose tolerance"],
}
```

命中时 `piece.update(control_token=True, disease_state="absent")`。`IGT`、`IFG`、`T1D`、`T3cD` 不映射，保持 None（这些样本不进入 case/control 队列，是正确的）。确认 `T3cD` 不会被 `T2D` 别名命中。

### A4. 通用对照 token

第 133 行集合扩为：

```python
{"hc", "hcs", "ctrl", "ctrls", "con", "control", "controls", "healthy control", "healthy controls",
 "hv", "healthy volunteer", "healthy volunteers", "normal control", "normal controls",
 "non diabetic", "uninfected"}
```

### A 的测试（新文件 `backend/tests/test_round3_groups.py`）

用 spec = `heuristic_parse(<对应课题原文>)`，断言 `infer_group_label(sample, spec=spec)`：

- `{"key":"disease","value":"Type 2 diabetic"}` → `"case"`；`Non-diabetic` → `"control"`
- `{"key":"diabetes status","value":"T2D"}` → `"case"`；`ND` → `"control"`；`IGT`、`T3cD`、`IFG` → `None`
- `{"key":"sample group","value":"HCs"}` → `"control"`；`rheumatoid arthritis (RA)` → `"case"`
- `{"key":"condition","value":"non-diabetic"}` 仍为 `"control"`（GSE81608，回归）
- `_groups()` 规则（通过 `rule_judgements`）在 GSE86468、GSE164416、GSE291978 的真实样本上给出 `pass`，且 `qualifying_gsms` 数量分别为 24、57、6（真实样本见 J）

---

## B. 体外处理样本不能算基线病例/对照【P0】

### B1. 规则层识别体外处理（`donors.py`）

在 `parse_sample_traits()` 中，对 key 属于 `{"treatment", "stimulation", "stimulus", "agent", "compound", "drug", "exposure", "culture condition"}`（或 key 包含 `treat`/`stimul`）的字段：

- 值折叠后属于基线集合 → `treatment="untreated"`。基线集合：`untreated, none, no treatment, baseline, unstimulated, unstim, utx, mock untreated, n a, na, control medium`。
- 值命中体外干预词 → `treatment="ex_vivo"`。干预词正则（大小写不敏感）：`\blps\b|il[\s\-]?\d+|tnf|ifn|pma|ionomycin|anti[\s\-]?cd3|cd3/cd28|cpg|poly\s*\(?i:c|stimulat|inhibitor|agonist|antagonist|sirna|shrna|knock ?down|dmso|vehicle|\d+\s*(ng|ug|µg|μg)/ml|\d+\s*(nm|um|µm|μm|mm)\b|\bst\d{3,}\b`。
- 其它值（如 `methotrexate`、`DMARD`、`anti-TNF therapy` 这类患者用药）→ 不设置 `treatment`，只在 `notes` 里记一条 `患者治疗字段：<值>`，不影响分组。

`_traits_from_text` 里已有的 `treated/untreated` 词识别保留。

### B2. 分组映射（`map_traits_to_group`）

当 `required_groups` 是疾病对照（含 `case`/`lesion`/`disease` 且含 `control`/`healthy`），并且 spec 里没有要求处理组（`spec.required_groups` 不含 `treated`/`untreated`）时：

- `traits.treatment == "ex_vivo"` → 返回 `None`（不进入 case，也不进入 control）。
- `untreated` 或未设置 → 按原逻辑。

`TREATMENT_GROUP_NAMES` 分支（第 147–152 行）保持不变，`ex_vivo` 在该分支中视为 `treated`。

### B3. 提示词（`backend/app/prompts/v1/reviewer.txt`、`assess_dataset.txt`、`verify_dataset.txt` 中的分组规则段）

加一条：

> 疾病与对照比较时，接受过体外刺激、药物、抑制剂、敲低等处理的样本不是基线病例或对照，不得列入 groups 的 qualifying_gsms；同一供体的多个处理样本只算一个供体。患者的临床用药不属于体外处理。

改提示词后需同步 prompt 版本号（查 `prompt_versions` 的来源，若有 hash 会自动变化就不用手改）。

### B4. 推荐理由里写出实际队列规模（`engine.py::_annotate_reason`）

给 `_annotate_reason` 增加参数 `merged: list[CriterionJudgement]`、`spec`。取最终 `groups` 判断的 `qualifying_gsms`，按 `infer_group_label(sample, spec=spec)` 计数，追加：

```
适用队列：case 2 / control 2 个 GSM。
```

当任一组 GSM 数 < 3 时再追加 `每组样本很少，统计效力有限。`。调用点在第 761 行，需要把 `merged` 和 `spec` 传进去。

### B 的测试

- GSE189136 真实样本：规则 `groups` 的 `qualifying_gsms` 只含 4 个 GSM（`PBMC_CS1_UTx`、`PBMC_CS4_UTx`、`PBMC_RA3_UTx`、`PBMC_RA4_UTx` 对应的 GSM）。
- 模拟模型输出把 19 个 GSM 都列进 groups：经 `check_model_assessment` 后 groups 只保留 4 个，且理由含"已移除分组对不上的 GSM"。
- `treatment: methotrexate` 的 RA 样本仍为 `case`。
- `_annotate_reason` 输出包含 `适用队列：case 2 / control 2 个 GSM`。

---

## C. 规则层按样本判定技术 + 模型前闸门 + 深审补位【P0】

### C1. `screening.py::_assay` 先看样本

在函数开头（第 196 行之后）加样本级判定，对所有 `wanted` 生效：

```python
if samples:
    ok, bad = [], []
    for s in samples:
        rel = assay_relation(wanted, infer_sample_assay(s, summary))
        gsm = str(s.get("gsm") or "")
        if rel == "ok" and gsm:
            ok.append(gsm)
        elif rel == "contradict" and gsm:
            bad.append(gsm)
    total = len([s for s in samples if s.get("gsm")])
    if ok:
        strategies = sorted({str(s.get("library_strategy") or "") for s in samples if str(s.get("gsm") or "") in ok} - {""})
        return CriterionJudgement(criterion_id=..., verdict="pass", judge_source="rule",
            reason=f"{len(ok)}/{total} 条样本的技术与要求一致。",
            support_text=", ".join(strategies) or ",".join(wanted),
            qualifying_gsms=ok, clue_only=bool(bad))
    if bad and len(bad) == total:
        shown = sorted({infer_sample_assay(s, summary).kind or "other" for s in samples})
        return CriterionJudgement(criterion_id=..., verdict="fail", judge_source="rule",
            reason=f"全部 {total} 条样本技术为 {'、'.join(shown)}，与要求 {','.join(wanted)} 冲突。",
            support_text=str(samples[0].get("library_strategy") or ""))
```

判定不出来时落回原有的研究级逻辑。注意：

- 有部分样本矛盾时 `clue_only=True`（混合研究，必须靠 GSM 子集过关），全部一致时 `clue_only=False`。
- `support_text` 必须非空，否则 `_rule_standalone()` 不会采用（第 939 行）。
- 删除/替换第 257–259 行的"RNA-seq 亚型不限"硬 unknown：有样本时已被上面覆盖，无样本时保留这条 unknown。

### C2. 模型前闸门（`engine.py::step_assess`）

在第 619 行算完 `rules` 之后、调用模型之前：若存在硬条件 `fail`，且 `clue_only=False`、`field in {"organism","assay","assay_method","tissue","sample_source"}`、并且判断基于样本（`qualifying_gsms` 或样本级 reason；实现时给 C1 的 fail 加 `support_text`，并只在 `sample_dicts` 非空时生效），则：

- 不调用模型；`rd.category="excluded"`、`rd.reason="硬条件失败（样本级规则，未调用模型）: <criterion_ids>"`、`rd.verification_status="verified"`；
- 写入 `assess_rules` 与 `final` 两份 assessment（`final` 就用 rules）；
- `rd.first_assess_json` 写 `{"model": None, "rule_gate": True, ...}`，并确保 `_open_review()` 不会再把它当作待 assess/verify（`_open_review` 看的是 `"model" in first_assess_json` 与 `verification_status`，两者都要满足跳过条件）；
- 加事件 `"{gse} 样本级规则已排除，跳过模型调用"`。

### C3. 深审补位

目的：被 C2 闸门排除的目标不占用深审名额，后面的候选补上来。

- `select_deep_targets(rows, summaries, limit)` 调用处（`engine.py` 第 488 行）改为 `limit + reserve`，`reserve = max(2, budget.max_deep_verify // 2)`；checkpoint 保存完整列表。
- `step_deep_fetch`：SOFT 解析完成后立刻跑一次 `rule_judgements`（与 C2 同一套闸门判断函数，抽成 `_rule_gate(spec, summary, samples) -> list[str]`，返回失败条件 id）。命中闸门的数据集：按 C2 标记为 excluded，**不** `bump_counters(deep_done=1)`，改为 `bump_counters(deep_gated=1)`。
- 循环终止条件：`deep_done >= budget.max_deep_verify` 或 `index >= len(targets)` 时进入 assess，不要用 `_guard(run, "deep")` 抛 `BudgetStop`（那会把正常结束记成预算停止）。未抓取的补位目标计入 `deep_skipped`。
- 前端和导出若展示 counters，`deep_gated` 作为新键即可，不强制加 UI。

### C 的测试

- GSE309036 真实样本 + AD spec：规则 `assay` 为 `fail`、非 clue；`_rule_gate` 返回 `["assay"]`。
- GSE317746 真实样本：规则 `assay` 为 `pass`，`qualifying_gsms` 16 个，`clue_only=False`。
- 用 `test_pipeline_mock.py` 的模式造一个 3 目标的 run，其中 1 个样本全是 `miRNA-Seq`：断言该数据集没有产生模型调用（mock usage 次数），最终 `excluded`，且补位目标被抓取（`deep_done == max_deep_verify`）。

---

## D. 大系列样本截断【P0】

现状：`fit_samples()` 只放得下 40,000 字符；放不下时 `coverage.complete=False`，然后 `_demote_incomplete_sample_coverage()` 把 assay/groups 的 pass 全降成 unknown，`step_verify` 里 `depth_complete` 也要求 coverage 完整（第 744 行），所以大系列永远不能推荐。

### D1. 同质样本折叠（`assessment.py::fit_samples`）

在装箱前按签名分组：

```python
signature = (
    label,                                   # infer_group_label
    row.get("donor_key") or "",
    str(row.get("organism") or ""),
    str(row.get("library_strategy") or ""),
    str(row.get("library_source") or ""),
    str(row.get("source_name") or ""),
    re.sub(r"\d+", "#", str(row.get("title") or "")),
    tuple(sorted(str(c.get("raw") or "") for c in row.get("characteristics") or [] if isinstance(c, dict))),
    protocol_ref_or_text,
)
```

同签名 ≥ 3 条时合成一条折叠记录：代表样本的完整 compact 字段 + `"member_gsms": [...]`（成员全部列出；成员 > 200 时用连续编号区间字符串，如 `"GSM2157899-GSM2158012"`，并附 `"member_count"`）+ `"titles_vary": true/false`。装箱按折叠后的记录计算字符数。`coverage` 增加：

- `"represented"`：被单独或折叠记录覆盖的样本数
- `"complete"`：`represented == total` 且无 `coverage_incomplete`
- `"members"`：`{代表GSM: [全部成员GSM]}`（只在服务端使用，`judge_user_payload` 发给模型前要 pop 掉，避免重复占 token）

`judge_user_payload` 的 `sample_coverage` 说明加一句：`折叠记录代表 member_gsms 中的全部样本，字段完全相同；qualifying_gsms 可直接写代表 GSM。`

### D2. 绑定时展开代表 GSM（`_bind_qualifying_gsms`）

新增参数 `members: dict[str, list[str]] | None`。模型列出的 GSM 若是代表 GSM，先展开为全部成员再做逐条校验。`check_model_assessment` 从 `sample_coverage.get("members")` 取值传入。GSM 区间字符串如被模型原样写回，也要能展开（写一个 `_expand_gsm_token`）。

### D3. 规则全覆盖可以兜住截断降级（`merge_final`）

1. 在 `assessment.py` 定义常量 `COVERAGE_DEMOTION_REASON = "样本记录未完整纳入模型输入，不能据此推荐。"`，`_demote_incomplete_sample_coverage` 使用它。
2. `merge_final` 中，对 `field in {"assay", "groups"}`：若两次模型该条都是 `unknown` 且 reason 等于 `COVERAGE_DEMOTION_REASON`（或以它开头），而规则判断是 `pass`、`clue_only=False`、有 `qualifying_gsms` 与 `support_text`，则采用规则判断，`judge_source="rule_full_coverage"`，reason 追加 `模型只看到部分样本；规则已在全部 {n} 条样本上核对。`
3. groups 的规则 pass 还必须满足：规则 `qualifying_gsms` 里 case 和 control 两组都有，并且没有任何被 B1 标成 `ex_vivo` 的样本。

### D4. `depth_complete` 只看 SOFT 截断

`engine.py` 第 744 行改为：

```python
soft_truncated = any(s.get("coverage_incomplete") for s in sample_dicts)
depth_complete = rd.verification_status in {"soft_loaded", "assessed"} and not soft_truncated
```

字符预算造成的不完整交给 D3 处理：D3 没能兜住的条件仍然是 unknown，`classify()` 会给出"硬条件缺少有效直接证据"，不会误推荐。

### D5. 样本字符预算随强度变化

`Budget` 增加字段 `sample_char_budget: int = 40_000`，preset 中 low 40,000 / medium 60,000 / high 100,000 / ultra 160,000。`engine.py` 所有 `fit_samples(...)` 与 `judge_user_payload(...)` 调用传入 `budget=self._budget(run).sample_char_budget`（`judge_user_payload` 需要新增同名参数并透传）。`docs/intensity.md` 第 7 行"40,000-character cap at all tiers"同步改写。

### D 的测试

- GSE81608 片段（见 J）：120 条样本折叠后记录数 ≤ 6，`coverage.complete == True`。
- 模型输出 groups 只写两个代表 GSM：绑定后 `qualifying_gsms` 展开为全部成员。
- 一组标题只差数字、但 `diabetes status` 不同的样本不会被折叠到一起。
- GSE164416 真实样本，`sample_char_budget=40_000`：coverage 不完整；模拟模型对 assay/groups 给 pass → 被降级；再经 `merge_final` + 规则（A 修好后规则 groups pass、C 修好后规则 assay pass）→ 最终 assay、groups 都是 pass 且 `judge_source=="rule_full_coverage"`。
- `test_intensity.py` 的单调性测试加入 `sample_char_budget`。

---

## E. 组织匹配修正（`backend/app/pipeline/source.py`）【P1】

1. `_tissue_values()` 第 146 行的 key 集合改为：key 等于 `tissue/organ/tissue type/tissue_type`，或 key 包含 `cell type`、`cell_type`、`celltype`、`cell population`、`sample type`。
2. `_OFF_TISSUE["pbmc"]` 追加分选亚群和非 PBMC 血液成分：`"cd4", "cd8", "cd14", "cd16", "cd19", "cd56", "monocytes", "neutrophils", "whole blood", "plasma", "serum", "platelets"`。注意 `_material_conflicts` 只在 `_material_has_tissue` 为假时才判断冲突，所以 `tissue: blood; cell type: PBMC` 不会被 `whole blood` 误伤（但要写测试）。
3. `_OFF_TISSUE["brain"]` 追加 `"olfactory epithelium", "nasal", "olfactory mucosa"`。
4. 当前 `tissue_matches` 在材料字段为空时会退回 extract protocol（第 168 行）。保持不变，但确认 GSE163605 的 `CD4+_Tcells` 样本现在因冲突返回 False。

测试：

- GSE291978：6 条都 `tissue_matches(s, ["pbmc"])` 为 True。
- GSE163605：只有 `source_name == "PBMCs"` 的 29 条为 True，CD4+/CD8+/CD14+ 为 False。
- `{"source_name": "Olfactory Epithelium"}` 对 `["brain"]` 为冲突。
- 回归：`test_source_constraints.py`、`test_flash_followups.py` 全绿。

---

## F. 模型网络错误重试（`backend/app/connectors/llm.py`）【P1】

1. `_post()` 第 250–253 行拆分异常：
   - `httpx.ConnectError`、`httpx.ConnectTimeout`：请求未发出，`LLMError(kind="network", retryable=True)`，新增属性 `maybe_billed=False`。
   - `httpx.ReadTimeout`、`httpx.RemoteProtocolError`、`httpx.ReadError`、`httpx.WriteError`：可能已被计费，`maybe_billed=True`。
   - 报错文本改为 `f"模型网络错误: {type(exc).__name__}: {exc}"`，避免出现空消息。
2. `complete_json()` 第 95 行：`kind == "network"` 时不要立刻 raise。对同一个 body 最多重试 2 次（间隔 2 秒、6 秒，用 `asyncio.sleep`）；每次重试前再调用一次 `self.before_request(body)`，让预算闸门生效。`maybe_billed=True` 的错误只重试 1 次。重试全失败才 raise。
3. 在 `LLMProvider` 上加 `billing_uncertain: bool = False`，任何 `maybe_billed=True` 的失败都置 True。`engine.py` 在 `_complete_assessment` 结束（无论成功失败）后：`if llm.billing_uncertain: run.duplicate_billing_risk = True`。
4. `add_event` 记录每次重试：`"{gse} 模型网络错误，第 {n} 次重试"`。事件需要从 engine 侧记，connector 只需通过回调或返回 `retries` 次数；最简单是在 `LLMError`/返回的 usage 里带 `retries` 字段，engine 读取后写事件。

测试（`test_llm_deepseek.py` 或新文件，用 `httpx.MockTransport` / monkeypatch `_post`）：

- 第一次 `ConnectError`、第二次成功 → 返回结果，调用 2 次。
- 连续 `ReadTimeout` → 只调用 2 次后 raise，`billing_uncertain is True`。
- 报错消息包含异常类名。

---

## G. 混合组学提示改为样本优先（`backend/app/pipeline/assay.py::mixed_omics_note`）【P2】

- 有样本时只用样本级 kind 判断是否混合（`infer_sample_assay(s, None)`），不再合并研究级文本 kind。
- 研究级文本提到了样本里没有的组学时，改为提示：`标题/摘要提到 {kinds}，但 GEO 样本中只有 {sample_kinds}。`
- 无样本时保持现有逻辑。

测试：GSE317746 样本 → 不再输出"系列同时包含 snrna_seq、proteomics"，而是"标题/摘要提到 proteomics，但 GEO 样本中只有 snrna_seq。"

---

## H. 提高 Medium 预算【P1】

`backend/app/schemas/spec.py` 第 124–129 行改为（元组顺序：queries, unique_gse, deep, runtime_s, tokens, output, sample_chars；`preset()` 同步解包新字段）：

| 档 | queries | unique GSE | deep | runtime | tokens | output | sample chars |
|---|---:|---:|---:|---:|---:|---:|---:|
| low | 4 | 80 | 0 | 600 | 20,000 | 2,048 | 40,000 |
| medium | **10** | **250** | **10** | **3,600** | **400,000** | 4,096 | **60,000** |
| high | 16 | 400 | 20 | 5,400 | **1,000,000** | 8,192 | 100,000 |
| ultra | 40 | 1,500 | 100 | 21,600 | 4,000,000 | 16,384 | 160,000 |

依据：第二轮每个深审数据集约 1.6–1.8 万 token；深审 10 个、样本上限提到 6 万字符后，预计 20–30 万；40 万给格式修复和网络重试留余量。第二轮 AD、RA 都是"ESearch 命中超过取回上限"截断，唯一 GSE 从 150 提到 250。high 的 token 同步提到 100 万，保证单个深审目标的 token 余量不低于 medium（原 60 万 / 20 个 = 3 万，低于新 medium 的 4 万）。

需要同步的地方：

- `docs/intensity.md` 表格与第 7 行。
- `frontend/e2e/mockApi.ts` 第 76 行 medium（和 high）的 mock 值。
- `backend/tests/test_intensity.py` 单调性测试会自动覆盖，跑通即可。
- `docs/quickstart.md` 若提到具体数值一并更新（目前没有数值，只需检查）。

---

## I. 其它小项【P2】

1. `_annotate_reason` 里的"独立供体字段不完整；N 个 BioSample 只是未去重的上限"：当 `rd.independent_donors` 为空但样本标题能提取出重复的个体编号时（例如 `PBMC_RA3_LPS`、`PBMC_RA3_UTx`），追加 `样本名提示约 {k} 位个体（仅供参考）`。提取规则：去掉标题中的处理/时间/重复词（`utx|lps|il-?1b|st\d+|rep\d+|r\d+$|_\d+h`），剩余 token 中形如 `[A-Za-z]{1,4}\d{1,3}` 的计数。这只是提示，不写入 `independent_donors`，不参与判定。
2. `ranking.py`：研究级 gdstype 只有 `Non-coding RNA profiling by high throughput sequencing`（没有 `Expression profiling by high throughput sequencing`）且标题含 `miRNA|microRNA|small RNA` 时，`_assay_mismatch_penalty` 扣 30 分，原因 `off_assay_small_rna_hint`。不要直接排除（lncRNA/circRNA 系列同样用这个 gdstype，可能是可用的 total RNA-seq）。

---

## J. 用第二轮真实样本做离线夹具【先做，供 A–G 使用】

写一次性脚本 `backend/scripts/export_round2_fixtures.py`（脚本本身可提交，生成的夹具也提交；脚本不能包含密钥），从 `data/flash-rerun-20260923/geoscout.db` 导出到 `backend/tests/fixtures/flash_round2_samples.json`：

```json
{
  "GSE86468": {"summary": {...}, "samples": [...]},
  ...
}
```

- 样本字段与 `engine.py::_sample_dicts()` 输出一致：`gsm,title,organism,source_name,donor_key,library_strategy,library_source,protocol,protocol_fields,characteristics,coverage_incomplete`（`library_source`、`protocol`、`protocol_fields` 在 `attrs_json` 里）。
- summary 取 `datasets.summary_json`，只保留 `title,summary,overall_design,gdstype,taxon,n_samples`。
- 导出：GSE86468、GSE164416（全部 133 条）、GSE291978、GSE189136、GSE309036、GSE163605、GSE317746、GSE153855、GSE266852 全部样本；GSE81608 只取按 gsm 排序的前 60 + 后 60 条（覆盖 non-diabetic 与 T2D 两种 condition）。
- protocol 文本超过 1,500 字符的截断到 1,500，控制夹具体积（< 1.5 MB）。

新增测试文件 `backend/tests/test_round3_regressions.py`，加载该夹具，放 A–G 中依赖真实样本的断言。另外加一条"黄金用例"：对下表每个数据集，用对应课题 spec 跑 `rule_judgements`，断言关键条件：

| GSE | 课题 | 断言 |
|---|---|---|
| GSE86468 | T2D | assay pass、tissue pass、groups pass |
| GSE164416 | T2D | assay pass、groups pass（case 39 / control 18） |
| GSE291978 | RA | tissue pass、groups pass |
| GSE189136 | RA | groups pass 且 qualifying_gsms 仅 4 个 |
| GSE309036 | AD | assay fail（非 clue） |
| GSE163605 | RA | groups 非 pass（样本无 RA） |
| GSE153855 | T2D | 与当前结果一致（回归保护） |
| GSE266852 | RA | groups pass，case 3 / control 4 |

---

## K. 验证与交付

### K1. 离线

1. `cd backend; python -m pytest -q` 全绿（现有测试不得删改断言来"适配"，除非断言本身依赖旧预算数值）。
2. `cd frontend; npm test; npm run build` 通过。
3. 若改动了 e2e mock，跑 `npx playwright test`（需要本机已装浏览器）。

### K2. 在线复跑（需要用户提供 key，通过环境变量）

新数据目录，不覆盖旧结果：

```powershell
New-Item -ItemType Directory "D:\vesscular data\geoscout-bio\data\flash-round3-<日期>"
Copy-Item "D:\vesscular data\geoscout-bio\data\flash-rerun-20260923\run_three.py" "D:\vesscular data\geoscout-bio\data\flash-round3-<日期>\"
# 终端 1：启动隔离 API（working dir = backend）
$env:GEOSCOUT_DATA_DIR = "D:\vesscular data\geoscout-bio\data\flash-round3-<日期>"
$env:GEOSCOUT_NCBI_MODE = "live"; $env:GEOSCOUT_LLM_MODE = "live"; $env:GEOSCOUT_EMBED_WORKER = "true"
$env:GEOSCOUT_HOST = "127.0.0.1"; $env:GEOSCOUT_PORT = "8013"
$env:GEOSCOUT_OPEN_BROWSER = "false"; $env:GEOSCOUT_SERVE_WEB = "false"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8013
# 终端 2
$env:GEOSCOUT_BASE = "http://127.0.0.1:8013"; $env:DEEPSEEK_API_KEY = "<由用户提供>"
python "D:\vesscular data\geoscout-bio\data\flash-round3-<日期>\run_three.py"
```

`run_three.py` 默认 tier 为 medium，改完 H 后会自动用新预算。跑完关闭服务。

### K3. 验收标准

必须满足：

- 三个课题"模型输出不符合约定"均为 0；网络错误若出现，事件日志里能看到重试。
- 每个课题 token ≤ 400,000。
- GSE189136 若被深审：要么待核实，要么推荐理由里写明 `适用队列：case 2 / control 2 个 GSM`，不能再出现"17 例 RA"作为分组依据。
- GSE309036 若被选中：`excluded`，且没有对应的模型调用（事件日志有"样本级规则已排除，跳过模型调用"）。
- 已推荐过的 GSE153855、GSE266852 若被深审，仍为推荐。
- 任何被深审的数据集，最终 reason 不再出现"样本记录未完整纳入模型输入"而规则已在全部样本上 pass 的情况。

期望（非硬性，因为检索与选题每次会变）：

- GSE86468、GSE291978 若被深审，应为推荐。
- 推荐总数高于第二轮的 4 条，且每条推荐都能在样本字段里找到病例、对照两组的未处理样本。

### K4. 交付内容

- 代码与测试改动（按工作包分提交，提交信息说明原因）。
- 复跑报告：在复跑数据目录写 `summary.json`（脚本自动生成），并在回复中给出与第二轮的对比：推荐/待核实/排除数、token、每条推荐的队列规模、被闸门跳过的数据集、仍被压在待核实的高价值数据集及原因。

---

## 不要做

- 不要为了提高推荐数放宽 `classify()` 的推荐条件，或让模型的 pass 在规则没有样本证据时直接生效。
- 不要把 `biosample_count` 或标题推断的个体数当成 `independent_donors`。
- 不要用疾病名子串匹配代替 A2/A3 的分组字段逻辑（例如把所有含 `diabetes` 的字段都当病例）。
- 不要在 C2 闸门里用研究级（摘要/标题）证据排除数据集；闸门只认样本级规则 fail。
- 不要删除 `data/` 里的历史运行结果。
