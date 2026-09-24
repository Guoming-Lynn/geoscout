# 第五轮质量升级方案（给执行模型）

来源：2026-09-24 第五轮 DeepSeek Flash 实测，两个新课题（数据在 `data/flash-round5-20260924/`，库文件 `geoscout.db`，汇总 `summary.json`，核验脚本 `verify.py`）。
基线代码：`76586e7`（含 PBMC 去除亚群修复）。
目标：让 GEOScout 在 AD / T2D / RA 以外的课题上也能正确识别原代样本、疾病缩写、组织别名和体外处理，不再把细胞系、类器官、器官芯片或外周血推荐成"组织队列"。
执行顺序按本文 A→H。每个工作包都要先写失败的测试，再改代码，最后跑全量测试。

---

## 0. 背景与证据

两个课题（`data/flash-round5-20260924/run_two.py`）：

- UC colon：`human primary ulcerative colitis colon RNA-seq with disease and control`
- BRCA sc：`human primary breast cancer single-cell RNA-seq with disease and control`

解析结果：两者都是 `sample_source="any"`（应为 `primary`），`tissue_required=True`，`required_groups=["case","control"]`；UC 为 `tissues=["intestine"]`、`rna_seq_generic`，BRCA 为 `tissues=["breast"]`、`scrna_seq`。

运行概况（都是 Medium，都因 ESearch 超过取回上限而 `partial`，属正常截断）：

| 课题 | GSE | 深核 | 规则拦截 | token | 推荐 / 待复核 / 排除 |
|---|---|---|---|---|---|
| UC colon | 250 | 12 | 2 | 198,516 | 3 / 165 / 82 |
| BRCA sc | 250 | 11 | 1 | 106,958 | 0 / 186 / 64 |

没有出现模型输出不符合约定，没有网络失败。

### 0.1 逐条核验结果（`verify.py` 用当前代码重放样本）

| GSE | 当前结果 | 实际情况 | 根因（工作包） |
|---|---|---|---|
| GSE334803 | 推荐 | 结肠 12 份：UC 6 / 健康对照 6。**正确**。但 `source_kind` 为 `None`（`tissue: colon` 不在原代材料词表里） | 若只修 A1 而不修 A2，这个正确推荐会被降级（A2） |
| GSE123141 | 推荐 | 28 份全是从肠道分选的巨噬细胞；UC 10 / Crohn 9 / 正常对照 9。规则分组正确（Crohn 不计入） | 组织请求下，分选单一细胞群被当成整块组织（F）。复核模型说"对照 5 个"是按折叠代表计数，理由里的 9 是对的 |
| GSE277964 | 推荐 | 结肠芯片上的成纤维细胞/上皮，`stimulus: strain / no strain`（机械牵拉）；独立供体 UC 2 / 健康 3 | `strain` 不被识别为体外处理，牵拉样本进了队列（C）；器官芯片不被识别为模型来源（A3）；`sample_source=any` 没挡住（A1） |
| GSE224758 | 待复核 | 结肠活检，`condition: active ulcerative colitis` 16 / `healthy` 6，规则五项硬条件全过 | 复核模型疾病引句核对失败降为 unknown；疾病规则只做文本关键词，不能兜底（D） |
| GSE235236 | 待复核，groups unknown | 结肠活检，`disease: UC` 26 / `CD` 22 / `HC` 8 | `UC` 缩写不被识别为病例（B1） |
| GSE266325 | 待复核，tissue/groups unknown | `tissue: rectal biopsy`；`disease: UC` 5 / `CD` 9 / `non IBD` 9 | `rectal` 不属于 intestine（E1）；`UC`、`non IBD` 不认（B1、B2） |
| GSE222070 | 待复核，groups unknown | `tissue: colon` 35 / `Rectum` 8；`disease: UC` 17 / `CD` 16 / `HC` 10 | `UC` 不认（B1）；`Rectum` 不属于 intestine（E1） |
| GSE193677 | 待复核，tissue/groups unknown | 2490 份活检；`regionre: Rectum/Ileum/Cecum/Sigmoid/...`；`ibd_disease: UC/CD/Control` | 组织字段名 `regionre` 不被读取、别名缺失（E1、E2）；`UC` 不认（B1） |
| GSE276170 | 待复核，groups unknown | 儿童结肠类器官（`cell type: colonoids / spheroids`）；Active UC 16 / Inactive UC 16 / non-IBD control 16 | `colonoid`、`spheroid` 不被识别为类器官（A3）；`Active UC` 不认（B1） |
| GSE102746 | 待复核 | 肠上皮类器官，UC 10 / 对照 10 | 结果合理；修 A1 后应由 sample_source 规则直接排除 |
| GSE300475 | 待复核，tissue **pass** | 全部 `tissue: PBMC`，乳腺癌患者治疗前后外周血 | 材料字段是 PBMC，却因提取步骤写了 "breast cancer patients" 而通过乳腺组织（E3）；乳腺没有冲突组织表（E4） |
| GSE313152 | 待复核，tissue unknown | `tissue: lung`，乳腺癌肺转移 + 正常肺 | 乳腺没有冲突组织表，肺不算冲突（E4） |
| GSE252950 / GSE338456 | 待复核 | MDA-MB-231、BT549 细胞系 | 规则 `source_kind=cell_line` 已识别，但 `sample_source=any` 不起作用（A1、A4） |
| GSE309616 / GSE303201 | 待复核 | PDX 肿瘤 | 同上，`source_kind=xenograft`（A1、A4） |
| GSE298343 | 待复核 | 乳腺癌类器官 | 同上，`source_kind=organoid`（A1、A4） |

结论：

1. UC 的 3 个推荐里只有 GSE334803 是合格的结肠活检队列；真正更好的 GSE224758、GSE222070、GSE235236 被压在待复核。
2. BRCA 的 0 推荐是对的，但 10 个深核名额里没有一个是原代乳腺肿瘤 vs 正常乳腺的单细胞队列，细胞系、PDX、类器官、外周血、肺转移占满了名额。
3. 这些问题在 AD / T2D / RA 上被掩盖了：那三个请求里 `primary` 后紧跟 brain / islet / PBMC，恰好命中 `_PRIMARY_MATERIAL`；疾病缩写 AD / T2D / RA 也已经手工加过。

---

## 通用约束

- 只改 `backend/`、`docs/`、`frontend/e2e/mockApi.ts`（仅在预算或 mock 需要同步时）。不要改 `data/` 下已有的运行结果。
- 保持现有保守原则：摘要里出现某词不能判 pass；缺样本证据不能判 fail；混合研究必须列出 GSM 子集。
- 不要放宽"推荐"门槛本身（`classify()` 的 ready 逻辑）。
- 新增词表一律用整词匹配（参考 `donors._has_word`、`source._blob_has_tissue`），不要用子串 `in`。
- 所有回归测试放在新文件 `backend/tests/test_round5_regressions.py`，夹具放 `backend/tests/fixtures/flash_round5_samples.json`（见 H1）。
- 每个工作包完成后跑 `python -m pytest -q`（在 `backend/` 下），当前基线 318 passed / 1 skipped。

---

## A. 原代来源（P0，先做）

### A1. `primary` 解析不依赖紧跟的组织词

位置：`backend/app/pipeline/spec_parse.py` 第 92–102 行 `_PRIMARY_MATERIAL` / `_ASKS_PRIMARY`。

现状：`\bprimary\b.{0,48}(tissue|samples?|biops…|pbmc|…|brain|cortex|hippocampus)`。`colon`、`breast`、`lung`、`liver`、`kidney`、`synovium`、`tumor` 等都不在里面，所以 UC、BRCA 两个请求解析成 `sample_source="any"`。

改法：

1. `_PRIMARY_MATERIAL` 改为由 `TISSUE_SYNONYMS` 所有键和值（英文部分）动态拼出，再加上 `tumou?rs?|resections?|surgical|patients?|donors?|cohort`。用 `re.escape` 并按长度降序拼接。
2. 保留现有中文分支和否定逻辑 `_SOURCE_NEGATION`。
3. 注意 "primary breast cancer" 在临床上指原发灶。按本项目语义它同样意味着患者来源材料，解析为 `primary` 是正确的，不需要特判。

测试：

- `heuristic_parse(UC).sample_source == "primary"`，`heuristic_parse(BR).sample_source == "primary"`。
- 原三个课题仍为 `primary`。
- `human breast cancer cell line RNA-seq`、`primary cells cultured from ...not patient tissue` 这类不能变成 `primary`（后者靠否定词）。
- `human colon cancer organoid RNA-seq`（无 primary）保持 `any`。

### A2. 组织材料本身就是原代证据（与 A1 同一个提交）

位置：`backend/app/pipeline/source.py` 第 35–42 行 `_PRIMARY`，第 122–140 行 `source_kind`。

现状：`_PRIMARY` 只认 biopsy / postmortem / blood / islet / brain 区域 / synovial。`tissue: colon`、`tissue: breast tumor`、`source_name: lung` 都返回 `None`。
风险：A1 生效后 `sample_source` 变成硬条件，GSE334803 这种正确推荐会因为 `sample_source unknown` 被降为待复核。**A1 和 A2 必须一起提交。**

改法：

1. 在 `source_kind` 中，`_PRIMARY` 未命中时补一条：材料字段（`source_name` + tissue 类 characteristics，复用 `_tissue_values(sample, include_extract=False)`）命中任一 `TISSUE_SYNONYMS` 词，或命中 `tumou?r|resection|surgical specimen|mucosa`，且材料和生长类 protocol 里都没有 `_CULTURE`、`_model_kinds` 信号 → 返回 `"primary"`。
2. 顺序不变：模型来源 > 培养 > 原代。已有的"模型词 + 原代词同时出现返回 None"保持不变。

测试（用夹具真实样本）：

- GSE334803、GSE224758、GSE222070 全部样本 `source_kind == "primary"`。
- GSE313152（`tissue: lung`）为 `primary`（它会在 E4 里因组织冲突被排除，不是在来源上）。
- GSE298343（`Organoid generated from a breast cancer tissue`）仍为 `organoid`。
- GSE309616（`PDX mammary tumor`）仍为 `xenograft`。

### A3. 补全模型来源词

位置：`backend/app/pipeline/source.py` 第 18–25 行。

改法：

- `_ORGANOID` 增加 `colonoids?|enteroids?|tumou?roids?|spheroids?|assembloids?|organ[- ]on[- ]a?[- ]?chips?|(?:colon|gut|intestine|lung|liver|kidney)[- ]chips?`，统一返回 `organoid`（器官芯片归为类器官一类，避免新增来源类型牵动前端）。
- `_CULTURE` 增加 `\bpassage\s*\d+|\bp\d{1,2}\b(?=.*passage)`（只在同一字段里同时出现 passage 时生效，避免 `p53` 之类误伤；如果实现复杂，只加 `\bpassage\s*\d+` 即可）。

测试：

- GSE276170 全部为 `organoid`。
- `source_name: Colon chip epithelium` → `organoid`。
- `characteristics: p53 status: mutant` 不被判为培养。

### A4. `sample_source` 规则能给出 fail 并进入规则门

位置：`backend/app/pipeline/screening.py` 第 542–550 行 `_sample_source`；第 389 行 `_GATE_FIELDS` 已含 `sample_source`。

现状：`_sample_source` 只返回 pass 或 unknown，所以细胞系、PDX、类器官永远不会被规则门拦截，只能靠模型，还占深核名额。

改法：

1. `spec.sample_source == "primary"` 时：若全部样本 `source_kind` 都是非 `None` 的模型来源（`cell_line` / `xenograft` / `organoid`），返回 `fail`，`support_text` 写第一条样本的 `source_name`，`qualifying_gsms` 留空，`reason="全部样本来自{kind}，不是原代材料。"`。
2. 部分样本是模型来源、部分是原代：保持现有 pass（qualifying 只列原代 GSM）。
3. 有样本 `source_kind is None`（无法判断）且没有原代样本：保持 unknown，不能 fail。
4. 请求本身要模型来源（`cell_line` 等）时逻辑对称：全部样本 `primary` 才 fail。

同时检查 `rule_gate_ids` 第 402 行的条件 `judgement.qualifying_gsms or judgement.support_text`：fail 分支必须带 `support_text`，否则不会被门控。

测试：

- BRCA spec（修 A1 后）下，GSE252950、GSE338456、GSE309616、GSE303201 的 `rule_gate_ids` 含 `sample_source`。
- GSE298343（5 份 organoid + 1 份 None）不 fail，保持 unknown。
- UC spec 下 GSE102746、GSE276170 被门控。
- GSE271307（6 份 primary + 3 份 None）不 fail。

---

## B. 疾病缩写与对照词（P0）

### B1. 补 IBD 家族和乳腺癌的病例标签

位置：`backend/app/pipeline/donors.py` 第 50–55 行 `DISEASE_LABELS`。

现状：只有 AD / T2D / RA / COVID-19。`disease: UC`、`diagnosis: Active UC`、`ibd_disease: UC` 全部识别为 `None`，这是 UC 课题待复核堆积的最大单一原因。

改法：

```python
"ulcerative colitis": ["UC", "active UC", "inactive UC", "UC active", "UC inactive", "ulcerative colitis"],
"Crohn's disease": ["CD", "Crohn", "Crohns", "Crohn's"],
"inflammatory bowel disease": ["IBD"],
"breast cancer": ["BC", "BRCA", "TNBC", "IDC", "ILC", "HR+", "HER2+", "ER+", "DCIS", "tumor", "tumour"],
```

注意：

- `CD` 与 CD4/CD8 等表面标志冲突。只能在分组类字段（`_is_group_key` 为真）上做整值匹配，不能在标题或 cell type 字段里匹配。沿用现有 `DISEASE_LABELS` 的匹配路径即可，确认它只在分组字段生效；如果不是，这一条必须先改成只看分组字段。
- UC 请求下 `CD` 必须**不是** case（它属于其他疾病）。检查 `parse_sample_traits` 的"其他疾病"分支：当值命中另一个疾病的标签时应标为 `other_disease` 或 `None`，而不是 `lesion`。GSE123141 当前 Crohn → `None` 是对的，靠的是全称；改完后缩写 `CD` 也要得到 `None`。
- IBD 请求（`inflammatory bowel disease`）下 UC 和 CD 都应是 case。实现方式：在 `DISEASE_LABELS` 查找时，把 `inflammatory bowel disease` 视为 UC 和 CD 的父类（新增一个小字典 `DISEASE_CHILDREN = {"inflammatory bowel disease": ["ulcerative colitis", "Crohn's disease"]}`）。
- `Inactive UC` 计为 case，但在 `_annotate_reason` 里若队列同时含 active 与 inactive，追加一句"病例组混有活动期与缓解期样本"（放到 G2 一起做也可以）。

测试：

- UC spec：GSE235236 → case 26 / control 8；GSE222070 → case 17 / control 10；GSE266325 → case 5 / control 9（依赖 B2）；GSE193677 → case 129（前 300 条中）/ control 94（依赖 B2 的 `Control` 已在 `_CONTROL_EXACT`）；GSE123141 仍为 case 10 / control 9，Crohn 9 份为 `None`。
- IBD spec：GSE123141 case 19。
- `cell type: CD4+ T cells` 不会被当成 Crohn 病例。

### B2. 疾病专属对照词

位置：`donors.py` 第 57–67 行 `DISEASE_CONTROL_LABELS`。

改法：

```python
"ulcerative colitis": ["non ibd", "non-ibd", "nonibd", "non ibd control", "non-ibd control", "hc", "healthy"],
"Crohn's disease": [同上],
"inflammatory bowel disease": [同上],
"breast cancer": ["normal", "normal breast", "normal tissue", "adjacent normal", "tumor adjacent normal", "reduction mammoplasty", "mammoplasty", "healthy breast"],
```

注意 `_fold` 会把 `-` 变成空格，列表里只需写折叠后的形式；上面重复写法只是说明，实际去重。

测试：GSE266325 `disease: non IBD` → control；GSE276170 `non-IBD control` 仍为 control。

---

## C. 体外处理识别泛化（P0）

位置：`donors.py` 第 97–116 行 `_BASELINE_TREATMENT`、`_EXVIVO_RE`，第 346–354 行 `_treatment_kind`。

现状：只有命中刺激剂正则才算 `ex_vivo`。GSE277964 的 `stimulus: strain` 和 `stimulus: no strain` 都得到 `treatment=None`，牵拉样本进入 case 22 / control 32。

改法：

1. 在 `_treatment_kind` 里，处理字段（调用方已通过 `_is_treatment_key` 保证）上：
   - 值以 `no |without |un|non[- ]` 开头，或属于 `_BASELINE_TREATMENT` → `untreated`。
   - 值命中 `therap|dmard|medication|clinical|prior|history` → `None`（临床用药，保持不变）。
   - 其他任何非空值 → `ex_vivo`。
2. 保留 `_EXVIVO_RE`，但只用于非处理字段（如 title、description）里的兜底识别。
3. `_BASELINE_TREATMENT` 补 `no strain|unstrained|static|sham|mock|control`。`control` 只在处理字段上视为未处理。

风险：有的数据集把分组写进 `treatment` 字段（例如 `treatment: healthy`）。在第 1 步之前先判断：值若能被 `infer_group_label` 的疾病/对照逻辑识别（命中 `DISEASE_LABELS`、`_CONTROL_EXACT`、`healthy`、`normal`），不当作处理。

测试：

- GSE277964：`no strain` → untreated，`strain` → ex_vivo；基线队列变为 case 11 / control 16（只含 no strain；执行者以实际计算为准并写进断言）。
- GSE189136（第二轮夹具）结果不变：基线 RA 2 / Healthy 2。
- `treatment: methotrexate`（患者用药）仍为 `None`。
- `treatment: healthy` 不被当成处理。

---

## D. 样本级疾病规则兜底引句失败（P1）

位置：`backend/app/pipeline/screening.py` 第 68–69 行（disease 走 `_keyword`）；`backend/app/pipeline/assessment.py` 第 409–414 行 `_demote_unverified_quote`、第 1076 行 `_rule_covers_truncated_model`。

现状：GSE224758 规则五项全过，分组 case 16 / control 6，唯一问题是复核模型的疾病引句在证据原文里对不上而降为 unknown；疾病规则只是"文本出现相关词"，不能兜底。

改法：

1. 新增 `_disease_from_samples(criterion, spec, samples)`：当存在 `infer_group_label(s, spec=spec)` 为病例的样本时，返回 `pass`，`qualifying_gsms` 为这些病例 GSM，`support_text` 为第一条病例样本的分组字段原值，`clue_only=False`。没有样本或没有病例时回落到原 `_keyword`。
2. 在 merge 中新增 `_rule_covers_unverified_quote`，与 `_rule_covers_truncated_model` 并列：仅当字段是 `disease`，且模型判断的 reason 以 "引句无法在证据" 开头（至少一次模型调用是这种降级，另一次是 pass 或同样降级），且规则是非 clue 的样本级 pass 时，采用规则结果。
3. 不对 tissue / groups 做这种兜底（这两项的模型意见更重要）。

测试：GSE224758 在 UC spec 下，模拟一次引句降级 + 一次 pass，merge 后 disease 为 pass，整体可进入推荐。另写一个反例：规则只有 `_keyword` 文本命中时，不能兜底。

---

## E. 组织别名、字段与冲突（P0 / P1）

### E1. 肠道别名（P0）

位置：`backend/app/pipeline/lexicon.py` 第 45–59 行 `intestine`、`colon`。

补：`rectum, rectal, sigmoid, sigmoid colon, cecum, caecum, cecal, ascending colon, descending colon, transverse colon, right colon, left colon, rightcolon, leftcolon, colorectal, mucosal biopsy, 直肠, 结肠, 乙状结肠, 回肠, 盲肠`。`colon` 条目只补结肠段（不含 ileum）。同步 `spec_parse.py` 第 83 行 intestine 正则加 `rect(?:um|al)|colorectal`。

### E2. 组织字段名（P0）

位置：`source.py` 第 143–153 行 `_tissue_values`。

现状：只认 `tissue / organ / tissue type` 和 cell type 类。GSE193677 用 `regionre`，其他常见写法有 `region`、`location`、`anatomic site`、`biopsy site`、`sampling site`、`body site`、`site`。

改法：键名（casefold）包含 `region|location|site|anatom|biopsy` 任一片段时也纳入。`site` 用整词，避免 `composite` 之类。

测试：GSE193677 前 300 条中，`regionre: Rectum/Sigmoid/Cecum/RightColon/LeftColon` 匹配 intestine；`regionre: Ileum` 匹配 intestine、不匹配 colon。GSE266325 `rectal biopsy` 匹配 intestine。

### E3. 材料字段点名其他组织时，不许用提取步骤兜底（P0）

位置：`source.py` 第 196–204 行 `tissue_matches`。

现状：`_material_has_tissue` 失败 → `_material_conflicts` 只查冲突表 → 冲突表里没有就用 `include_extract=True` 再匹配一次。GSE300475 材料字段是 PBMC，提取步骤写着 "breast cancer patients"，于是通过了乳腺。

改法：在调用提取步骤兜底之前，若材料字段命中任一 `TISSUE_SYNONYMS` 词（不论是不是目标组织的冲突词），直接返回 False。只有材料字段完全没有组织词（空、`sample`、`biopsy` 之类泛称）时才用提取步骤。

测试：GSE300475 所有样本 `tissue_matches(..., ["breast"]) is False`；第二轮、第三轮夹具中原来靠提取步骤通过的样本（执行者先跑一遍列出）结果不变。

### E4. 乳腺冲突表 + 通用兜底（P0 乳腺 / P1 通用）

位置：`source.py` 第 207–221 行 `_OFF_TISSUE`；`ranking.py` 第 11–23 行 `_OFF_TARGET`。

1. 两处都加 `"breast": ["blood", "pbmc", "lung", "liver", "brain", "bone", "bone marrow", "lymph node", "pleural effusion", "ascites", "skin", "ovary", "colon"]`。
2. 通用兜底：`_material_conflicts` 在目标组织没有冲突表时，用 `TISSUE_SYNONYMS` 中**其他**键的词作为冲突词，但要排除包含关系（intestine↔colon、blood↔pbmc、brain↔cortex/hippocampus 同族）。包含关系写成一个小字典 `TISSUE_FAMILY`。

测试：GSE313152（`tissue: lung`）在 BRCA spec 下 tissue 规则为 fail，且进入 `rule_gate_ids`；GSE300475 同样 fail（依赖 E3）。`tissue: breast tumor, lymph node negative` 不因 "lymph node" 冲突（材料字段先命中目标组织，`_material_has_tissue` 优先返回 True，无需改动，但要写测试确认）。

---

## F. 组织请求下的分选细胞群提示（P1）

位置：`backend/app/pipeline/engine.py` `_annotate_reason`；判定函数放 `source.py`。

现状：GSE123141 全部是从肠道分选的巨噬细胞，组织条件通过，推荐理由没有任何提示。PBMC 分支已有 `_pbmc_subset` 直接排除，但对实体组织直接排除太激进（用户可能就想要纯化细胞）。

改法：

1. 新增 `sorted_fraction(sample) -> str | None`：`cell type` 类字段或 `source_name` 命中 `_PBMC_SUBSET_RE`（复用，去掉 depleted 片段）或 `epithelial|fibroblasts?|endothelial|stromal|immune cells|leukocytes|cd45\+` 时返回该值。
2. `_annotate_reason`：适用队列中超过一半样本是分选细胞群，且 spec 的原始请求里没有出现该细胞类型词时，追加"样本是从组织中分选的 {值}，不是整块组织，请确认是否符合需求。"
3. 不改分类，不改规则判定。

测试：GSE123141 理由包含"分选的 intestinal macrophages"；GSE334803 不包含。

---

## G. 深核名额与理由（P1 / P2）

### G1. 规则门后的补位加大（P1）

位置：`engine.py` 第 493 行 `extra = 0 if cap <= 0 else max(2, cap // 2)`。

现状：Medium `cap=10`，最多预选 15 个。A4 生效后，BRCA 这类课题预计 10 个里有 6–7 个会被规则门拦截，5 个补位不够，模型实际只审 3–4 个。SOFT 下载不花 token。

改法：`extra = 0 if cap <= 0 else cap`（最多预选 2×cap）。确认 `step_deep_fetch` 在 `deep_done` 达到 `cap` 后停止继续下载剩余目标；如果当前实现会把全部预选都下载完，加上这个停止条件。同步 `docs/intensity.md` 说明。

测试：构造 20 个候选、前 12 个被规则门拦截，`cap=10` 时模型实际评估 8 个（受 2×cap 限制）；前 5 个被拦截时模型评估 10 个且只下载 15 个 SOFT。

### G2. 理由补充（P2）

- 病例组混有活动期与缓解期（B1 附带）。
- `GSE123141` 这种复核模型按折叠代表数错数的情况：在 `reviewer.txt` 加一句"member_gsms 中的全部样本都计入该组人数，不要只数代表样本"。不需要代码改动。

---

## H. 测试夹具与第六轮实测

### H1. 导出夹具

新建 `backend/scripts/export_round5_fixtures.py`（照抄 `export_round3_fixtures.py`），从 `data/flash-round5-20260924/geoscout.db` 导出以下 GSE 的 `summary` 和 `samples`：

`GSE334803 GSE123141 GSE277964 GSE224758 GSE235236 GSE266325 GSE222070 GSE276170 GSE102746 GSE300475 GSE313152 GSE252950 GSE338456 GSE309616 GSE303201 GSE298343 GSE271307`

GSE193677 有 2490 条，只导出前 300 条，并在夹具里记 `"truncated_fixture": true`。输出 `backend/tests/fixtures/flash_round5_samples.json`。

### H2. 预期修复后的结果（执行者用来自查，不是硬性断言）

| GSE | 预期 |
|---|---|
| GSE334803 | 推荐 |
| GSE224758 | 推荐（依赖 D） |
| GSE222070 | 推荐或待复核（依赖模型；规则层 case 17 / control 10、组织通过） |
| GSE235236 | 推荐或待复核（标题提到 spatial，已有 mixed-omics 提示） |
| GSE123141 | 推荐，理由带分选细胞群提示 |
| GSE277964 | 不推荐（sample_source 非原代或 unknown） |
| GSE102746、GSE276170 | 规则门排除（organoid） |
| GSE300475、GSE313152 | 规则门排除（tissue） |
| GSE252950、GSE338456、GSE309616、GSE303201 | 规则门排除（sample_source） |
| GSE298343 | 待复核或排除（5/6 organoid） |

### H3. 第六轮实测

1. 全量测试通过后提交并推送。
2. 新数据目录 `data/flash-round6-YYYYMMDD/`，端口避开 8011–8015，用 `run_three.py` 的模板跑 5 个课题：原三个（AD brain、T2D islet、RA PBMC）+ 本轮两个（UC colon、BRCA sc）。
3. 核对清单：
   - 原三个课题推荐数不低于第四轮（2 / 6 / 3），GSE318560、GSE164416、GSE153855、GSE189136 仍在推荐里。
   - UC 推荐中不再出现器官芯片或类器官；GSE224758 进入推荐。
   - BRCA 深核名额中细胞系、PDX、类器官、外周血、肺转移都被规则门拦截，`deep_gated` 明显上升，模型审的是原代乳腺样本。
   - 5 个课题 token 都在 Medium 40 万以内；没有模型输出不符合约定。

---

## 优先级汇总

| 优先级 | 工作包 | 预计影响 |
|---|---|---|
| P0 | A1+A2（同一提交）、A3、A4 | 细胞系 / PDX / 类器官 / 器官芯片被规则门拦截，释放深核名额 |
| P0 | B1、B2 | UC 课题 4 个以上好数据从待复核回到可推荐 |
| P0 | C | 器官芯片牵拉这类体外处理不再进入基线队列 |
| P0 | E1、E2、E3、E4（乳腺） | 直肠/乙状结肠活检能匹配；外周血、肺不再冒充乳腺 |
| P1 | D、E4 通用兜底、F、G1 | 引句误降级兜底；新组织自动有冲突表；分选细胞群提示；补位加大 |
| P2 | G2 | 理由细节 |
