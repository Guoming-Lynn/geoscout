# 第九轮质量升级方案（给执行模型）

来源：

- 2026-09-25 对第七轮五课题结果的人工核验（数据 `data/flash-round7-20260924/`，核验脚本 `verify_dump.py`、`verify_cross.py`、`verify_db.py`、`verify_fix.py`）。
- 2026-09-25 第八轮 UC colon / BRCA sc 复跑的评估（数据 `data/flash-round8-20260925/`，评估脚本 `evaluate.py`、`probe.py`、`probe2.py`）。

基线代码：`9f1fa47`，另有一处未提交修改（见 A）。
目标：让推荐理由里的队列人数、批次、质控和数据可得性说明与 GEO 原始记录一致；不改变“推荐”门槛本身。
执行顺序按本文 A→G。每个工作包先写失败的测试，再改代码，最后跑全量测试。

---

## 0. 背景与证据

### 0.1 第八轮运行概况

两个课题都是 Medium，都因 ESearch 命中超过取回上限而 `partial`（属正常截断），没有网络失败，也没有模型输出无效。

| 课题 | GSE | 深核 | 规则拦截 | token | 推荐 / 待复核 / 排除 |
|---|---|---|---|---|---|
| UC colon | 250 | 10 | 1 | 170,327 | 6 / 163 / 81 |
| BRCA sc | 250 | 10 | 26 | 140,521 | 1 / 164 / 85 |

对照第七轮：UC 为 7 / 160 / 83，BRCA 为 1 / 160 / 89。

### 0.2 已在 `9f1fa47` 修好、第八轮实测生效的项

| 问题 | 第七轮表现 | 第八轮表现 |
|---|---|---|
| UC 请求组织被解析为 `intestine`，回肠也算结肠 | `GSE193677` 的回肠活检计入队列 | 规格为 `tissues=["colon"]`；`GSE193677` 只剩 1728 份非回肠样本匹配组织 |
| 混合物种不提示 | `GSE253572` 理由未提大鼠 | 理由写明“系列混有其他物种（Rattus norvegicus 51 个 GSM），结论只覆盖目标物种的 50 个 GSM” |
| 标题个体数把 FACS 标记和抗体名当个体 | `GSE253572` 写“约 2 位个体”（来自 CD10/CD45、OX40/PDL1） | 不再出现 |
| 模型输入被截断时，队列只剩模型看到的样本 | `GSE193677` 写“case 22 / control 22” | 用第七轮存档重放：case 651 / control 335。第八轮该数据集未进深核（见 0.4），未能实测 |

### 0.3 第八轮新发现的问题

| GSE | 当前结果 | 实际情况 | 根因（工作包） |
|---|---|---|---|
| GSE109142 | 待复核，groups unknown | 儿童直肠活检，`diagnosis: Ulcerative Colitis` 206 / `Control` 20 | UC 样本带 `initial treatment: CS-Oral`（确诊时口服激素）。字段名含 treat、值不在药名表里，`_treatment_kind` 兜底返回 `ex_vivo`，206 个病例被踢出分组；模型输入又被截断，规则无法兜底（A，已修未提交） |
| GSE253572 | 推荐，队列 case 23 / control 13 | 人源 IDC 20 + DCIS 17 = 37 份病例，正常乳腺 13 份 | 模型输入未截断，但复核模型只列了 36 个 GSM，漏掉同批患者的 14 个免疫/基质/肌上皮组分（B） |
| GSE123141 | 推荐，队列 case 10 / control 6 | UC 10，正常对照 9 | 复核模型漏列 3 个 `immunosuppression: NA` 的对照；第七轮同一数据集列了 9 个（B） |

### 0.4 第七轮核验遗留、尚未处理的项

| GSE | 实际情况 | 工作包 |
|---|---|---|
| GSE235236 | 对照 8 份中 5 份在 batch 3；UC 26 份中只有 1 份在 batch 3。批次与分组部分重合，理由没有提示 | C |
| GSE154126 | 1263 个单细胞 GSM 中 638 个带 `celltype: dropped`（提交者质控剔除），理由没有提示 | D |
| GSE317746 | overall_design 写明 “Raw files for human/patient samples were not submitted to GEO”，理由没有提示 | E |

### 0.5 不是缺陷、无需修改的现象

- `GSE193677` 第八轮排名从第 7 掉到第 38。第七轮它的 40 分 `target_tissue_sample_evidence` 来自 intestine 词表里的 `bowel` 匹配到了病名 “inflammatory **bowel** disease”；标题里并没有组织词。现在不再误加分，是正确结果。
- BRCA 26 个数据集被规则层拦截（细胞系、PDX、外周血、肺转移），补位机制把 10 个模型名额用满。其中 6 个是只有癌组织、没有正常对照的研究，理由已写明“没有对照组”。

---

## 通用约束

- 只改 `backend/` 和 `docs/`。不要改 `data/` 下已有的运行结果。
- 保持现有保守原则：摘要里出现某词不能判 pass；缺样本证据不能判 fail；混合研究必须列出 GSM 子集。
- 不要放宽“推荐”门槛本身（`classify()` 的 ready 逻辑）。C、D、E 都只追加理由说明，不改变类别。
- 新增正则一律用整词或明确边界，不用子串 `in`。
- 回归测试追加到 `backend/tests/test_round7_regressions.py`（该文件已含第七、八轮的用例）。
- 每个工作包完成后在 `backend/` 下跑 `python -m pytest -q`。当前基线（含 A 的未提交修改）为 338 passed / 1 skipped。

---

## A. 患者临床用药不算体外处理（P0，代码已写好，待提交）

位置：`backend/app/pipeline/donors.py`

- 第 137–150 行：`_CLINICAL_DRUG` 增加 `5-ASA`、`corticosteroid`、`CS-Oral / CS-IV`、`anti-TNF`、`biologic`、`immunomodulator`；新增 `_CLINICAL_TREATMENT_KEY`（`initial|induction|maintenance|current|prior|previous|history|baseline|at diagnosis|clinical|medication|therapy`）。
- 第 254–258 行调用处：`_treatment_kind` 返回 `ex_vivo`，但字段名命中 `_CLINICAL_TREATMENT_KEY` 且值不命中 `_EXVIVO_RE`（LPS、细胞因子、抑制剂、浓度等）时，改为 `None`，只记入“患者治疗字段”备注。

已有测试：`test_patient_therapy_field_is_not_an_ex_vivo_treatment`，覆盖 `CS-Oral`、`5ASA`、对照 `NA`，以及 `treatment: LPS 100 ng/ml` 仍判体外处理。

重放结果：`GSE109142` 的规则分组从 unknown 变为在全部 226 个样本上 pass（case 206 / control 20）。

A2（可选，同一提交）：`_treatment_kind` 末尾对任何未识别的值都兜底返回 `ex_vivo`（第 401–402 行）。这条太激进，但放宽会影响 RA、T2D 已通过的体外刺激识别。本轮只加日志，不改行为：在兜底分支记一条 `logger.debug("treatment fallback ex_vivo: %s", value)`，下一轮运行后统计误判比例再决定。

提交信息建议：`Treat patient therapy fields as clinical history, not dish treatment.`

---

## B. 模型漏列合格样本时的队列人数（P1，需要先定方案）

### 现状

`merge_final`（`assessment.py` 第 962 行起）在规则和模型都判 pass 时采用模型的 `qualifying_gsms`。`9f1fa47` 加的 `_extend_to_unseen`（第 1099 行）只在模型输入被截断时，把模型**没看到**的 GSM 从规则补回；模型看到了却没列的 GSM 一律不补，用来保留模型主动排除样本的能力。

第八轮两例都是模型看到了却没列，且原始记录里这些样本完全符合条件，所以队列人数偏小。推荐结论本身不受影响。

### 方案 B-1（推荐）：只改展示，不改判定

在 `engine._annotate_reason` 生成“适用队列”时，同时计算规则层的分组人数：

1. 取 merged 里 `groups` 的 GSM（现有逻辑）得到 `model_counts`。
2. 取规则层 `groups` 判 pass 时的 `qualifying_gsms`，与其余硬条件的规则层 GSM 取交集（复用 `_sample_fits_all_hard`，传规则层判断），得到 `rule_counts`。
3. 两者一致时照旧输出。规则层某组人数多于模型层时输出：
   `适用队列：case 23 / control 13 个 GSM（模型列出）；按样本字段规则为 case 37 / control 13，差异样本请人工确认。`
4. 规则层 `groups` 不是 pass 时，不输出第二段。

需要把规则层判断传进 `_annotate_reason`：在 `engine.py` 调用 `_annotate_reason` 的两处（深核完成、导出前刷新）把 `rules` 一并传入，新增关键字参数 `rules: list[CriterionJudgement] | None = None`。

优点：不削弱模型的排除能力；用户能看到差异。缺点：理由变长。

### 方案 B-2：规则补回模型看到但未列的样本

在 `_extend_to_unseen` 里去掉“只补未看到的”限制，改为：规则层该条件 pass、非 clue_only，且补回的 GSM 同时满足所有硬条件的规则判断，就补回。

风险：模型基于摘要或 protocol 主动排除的样本（例如分选亚群、同一供体重复样本、处理组）会被规则重新拉回。RA 的 `GSE189136` 就依赖模型排除 LPS/ST2825 处理组，规则层这些样本的 `treatment` 是 `ex_vivo`，不会被补回；但其他数据集未必有这么干净的字段。

**执行模型不要自行选择。** 默认按 B-1 实现；如需 B-2，等用户确认。

### B-1 测试

- 用 `GSE253572` 真实样本构造：模型 `groups` 列 36 个 GSM，规则 `groups` pass 列 50 个人源 GSM → 理由含“模型列出”和“case 37 / control 13”。
- 模型与规则人数一致时，理由与现在逐字相同（防止所有推荐理由都变长）。
- 规则 `groups` 为 unknown 时不输出第二段。

---

## C. 批次与分组重合提示（P1）

位置：`backend/app/pipeline/engine.py`，与 `_repeated_sample_note`（第 1223 行）、`_activity_mix_note`（第 1292 行）并列，新增 `_batch_confound_note(cohort, labels)`，在 `_annotate_reason` 生成队列说明后调用。

规则：

1. 批次字段：characteristics 键名（小写）整词命中 `batch|run|lane|flowcell|flow cell|sequencing date|library[_ ]prep[_ ]date|processing date|plate`。取第一个在队列内有 ≥2 个取值的键。
2. 只看队列样本（`cohort_samples` + `labels`），每组至少 3 个 GSM 才判断。
3. 完全混杂：各组样本落在互不相交的批次集合里 → `批次与分组完全重合（按“<键名>”）：组间差异无法与批次效应区分。`
4. 部分重合：存在某个批次取值，在一组中占比 ≥ 50%，在另一组中占比 ≤ 10% → `批次与分组部分重合（按“<键名>”）：<组> 多在 <批次>，建议把批次纳入模型。`
5. 其余情况不输出。

测试：

- `GSE235236`（第七轮快照，队列 UC 26 / HC 8）→ 部分重合，指向 `batch 3`。
- 构造完全混杂：case 全在 batch A、control 全在 batch B → 完全重合文本。
- `GSE164416`（`library_prep_date` 多个取值，分布分散）→ 不输出。先用快照跑一遍确认；若触发部分重合，按实际分布确认阈值是否合理，而不是改测试。
- 批次字段只有一个取值 → 不输出。

---

## D. 提交者标注的质控剔除样本（P2）

位置：`engine.py` 新增 `_qc_dropped_note(samples)`，在 `_annotate_reason` 中调用。

规则：

1. 任一 characteristic 的值（整词、忽略大小写）为 `dropped|excluded|failed qc|qc fail(?:ed)?|low quality|removed`，或键名含 `qc`/`pass_qc`/`in_.*filtered` 且值为 `false|fail|no`，计为被剔除。
2. 被剔除数 ≥ 1 时输出：`<n>/<总数> 个 GSM 被提交者标为质控剔除（“<键>: <值>”），下载后应按该字段过滤。`
3. 同一 GSM 只计一次。

测试：

- `GSE154126`（第七轮快照）→ `638/1263`，键 `celltype`。
- `GSE164416` 的 `in_ins_filtered_data_subset: FALSE`（41 个）→ 输出 `41/133`。这是提交者给出的分析子集标记，提示同样有用。
- 普通样本不输出。

---

## E. 原始数据未公开或受控访问（P2）

位置：`engine.py` 新增 `_raw_access_note(summary)`，在 `_annotate_reason` 中调用；需要 `summary` 里带 `overall_design`（检查 `series_as_dict` 是否已包含，没有就补）。

规则：在 `summary`、`overall_design` 中匹配

- `raw (?:data|files?|reads?|sequenc\w*)\b.{0,60}\b(?:not|were not|was not|are not)\b.{0,20}\b(?:submitted|deposited|available|provided|uploaded)`
- `\b(?:dbgap|ega|egas\d+|phs\d{6}|controlled[- ]access|restricted access|data use agreement)\b`

命中时输出：`提交者说明原始测序数据未公开或需受控申请，GEO 上通常只有处理后矩阵。`

测试：

- `GSE317746`（第七轮快照）→ 输出。
- 摘要只写 “raw data are available at GEO” → 不输出。
- 摘要含 `phs001234` → 输出。

---

## F. 文档与提交（P0，与各工作包同步）

- 每个工作包单独提交，提交信息说明“为什么”。
- `README.md` 如有“推荐理由会提示哪些风险”的列表，同步补上批次、质控剔除、原始数据受控三项；没有就不新增章节。

---

## G. 验证运行（全部工作包完成后）

1. 新建 `data/flash-round9-20260925/`，复制 `data/flash-round7-20260924/run_five.py`，端口改为 8020。五个课题全部重跑，同一个 DeepSeek key，只放在进程环境变量里。
2. 跑完后用 `data/flash-round8-20260925/evaluate.py` 的同类脚本导出深核结果，逐条核对下表。

| 检查项 | 期望 |
|---|---|
| UC `GSE109142` | 若进入深核：推荐，队列 case 206 / control 20（或按 B-1 显示两段人数）。若未进深核：规则层 groups 为 pass |
| BRCA `GSE253572` | 推荐；理由含混合物种说明；B-1 下含“按样本字段规则为 case 37 / control 13” |
| UC `GSE235236` | 推荐；理由含批次部分重合提示 |
| T2D `GSE154126` | 理由含 `638/1263` 质控剔除提示 |
| T2D `GSE164416` | 理由含 `41/133` 分析子集提示；不含批次提示 |
| AD `GSE317746` | 理由含原始数据受控提示 |
| RA `GSE189136` | 仍只取未处理的 2 例 RA / 2 例健康，LPS、ST2825 处理组不进队列 |
| 全部推荐 | 没有“约 N 位个体”由基因名、表面标记、抗体名产生 |
| 运行状态 | 五个课题都到终态；没有因排队或租约过期耗尽运行时间预算 |

3. 发现与期望不符时，先用快照重放定位是规则、合并还是模型波动，再决定是否修改；模型波动（同一数据集两轮列出的 GSM 不同）只记录，不为此改规则。

---

## 验收标准

- `python -m pytest -q` 全部通过，新增用例覆盖 A–E 每条规则的正反两面。
- 第九轮五课题运行满足 G 表中所有期望，或对不满足的项给出快照重放证据和原因。
- 推荐 / 待复核 / 排除的数量变化只来自 A（`GSE109142` 类数据集可能从待复核升为推荐）；C、D、E 不应改变任何数据集的类别。
