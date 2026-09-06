# DeepSeek 官方 API 实机验证

日期：2026-09-05（周六，官方 off-peak）  
模型：`deepseek-v4-flash`  
Base URL：`https://api.deepseek.com`（GEOScout 会再拼 `/chat/completions`，未加 `/v1`）  
NCBI：live GEO；LLM：live  
解释器：`D:\miniforge\python.exe`  
Key：仅会话内存 / 设置页密码框，未写入代码、日志或本报告。

**连接成功 ≠ 完整流程通过。** 下面按课题记录任务 ID、结果与未验证项。

## 官方参数（核对当日文档）

| 项 | 取值 |
| --- | --- |
| JSON Output | `response_format: {type: json_object}`；提示词须含 “json” |
| json_schema | 不支持（连接测试首次 400） |
| Thinking | 默认开启；JSON 任务会耗尽 `max_tokens` 并返回空 `content` |
| 计价（Flash off-peak，cache-miss） | 输入 $0.22 / 1M tokens；输出 $0.66 / 1M tokens |
| 用量来源 | 提供商 `usage`（`source: provider`），未区分 cache hit/miss，费用按 cache-miss 上界估算 |

## 连接测试

设置页填写后 `POST /api/connections/test`：

- 结果：连接成功。使用官方 `json_object`，并关闭 thinking。不支持 `json_schema`。
- 解析到 `{"ok": true, "echo": "geoscout"}`。
- 此前一次测试（json_schema 400 后回退）用量约 prompt 102 + completion 48。

## 本轮为跑通 DeepSeek 做的代码修复

实机失败后才改代码，不是事先宣称通过。

1. **JSON 客户端**（`backend/app/connectors/llm.py`）：DeepSeek 走 `json_object` + `thinking: disabled`；空 `content` 则换参数重试；去掉 markdown 围栏。
2. **核验 JSON 解包**：模型常把 `judgements` 包在 `assessments` / `assess_dataset` / `assess_result` 里，或把 `quote` 写成 `null`。本地解开并强制字符串，不放宽 pass/fail。
3. **引句对不上原文**：该条条件改为 `unknown`，不再把整份模型输出判无效。
4. **检索规划**（`query_planner.py`）：空 disease 时不再用课题英文碎片（如 `bulk`/`RNA-seq`）当疾病词；有组织时 round 1 必须带上 tissue。课题 2 第一次 27763 命中、前 20 条与肝脏无关，复现后已修。

## 预算（三课题共用）

`max_queries=5`，`max_unique_gse=20`，`max_deep_verify=3`，`max_runtime_s=900`，`max_tokens=80000`，`max_completion_tokens=4096`，`esearch_page_size=20`。  
任务状态多为 `partial`，停止原因「达到唯一 GSE 初筛预算」：这是 20 条 GSE 上限，不是崩溃。Excel `complete=false` 与此一致。

## 课题 1：人类动脉粥样硬化 scRNA-seq，病变与对照

| 项 | 值 |
| --- | --- |
| 课题 ID | `942ebe60864f48aa85b83602e2a2702d`（`ds-live-athero-scrna`） |
| 确认条件 | human / `scrna_seq` / atherosclerosis / groups=`lesion`,`control`（丢掉 LLM 多出来的 `disease/lesion`） |
| 中断任务 | `19d7db840ce044d2bab9584fe1545368`：进程被杀后卡在 `verifying`；重启后因 `started_at` 过旧触发运行时间预算，作废 |
| JSON 形状失败任务 | `a0a8d28cc0f845bf9fae0848b2c6ce87`：全程跑完但 verify 根对象无 `judgements`，20/20 `needs_review`（「输出无效」） |
| **采用任务** | `9aebbdf6d8b542f78b38f14e086a6fff` |
| 起止 | 2026-09-05T16:11:23Z → 16:14:35Z（约 192 s） |
| 检索 | round 1 命中 62，取 20 个 GSE；其余 round 因预算跳过（截断=yes） |
| 深核 | 3（GSE218166、GSE275308、GSE278420 SOFT） |
| Token | prompt 56965，completion 15681（provider） |
| 分类 | recommended 0 / needs_review 20 / excluded 0 |
| Excel（当时） | `data/exports/9aebbdf6d8b542f78b38f14e086a6fff/GEOScout_ds-live-athero-scrna_20260905T161611Z.xlsx`；SHA-256 `d61335f247bfada9cb6e59a6281391be4bca60b0cd1c7526b39a4a19a4fab116`；Recommended 0 行 |
| Excel（2026-09-06 重导） | `GEOScout_ds-live-athero-scrna_20260906T032450Z.xlsx`；SHA-256 `c5a4cfe7db3132f0813e87db7072b82635a8c0566972511d7df105fda7229b6d`；分类与库一致 |

未宣称推荐成功。硬条件缺证据时保持待核实。

### 抽查（对照本机 SOFT 快照，GEO HTML 被 recaptcha 挡住）

| GSE | GEO/SOFT 事实 | GEOScout | 是否放宽 |
| --- | --- | --- | --- |
| GSE218166 | 人冠状动脉 scRNA-seq；2 个 GSM；设计写 different atherosclerotic stages；特征只有 tissue，无年龄/性别、无对照 GSM | `verified` + needs_review；assay/organism pass；groups/disease 等 unknown | 否 |
| GSE275308 | 斑马鱼胚胎 + 人主动脉内皮；混合物种；分组是 flow / ldlr 而非病变–对照 | needs_review；organism 因混合物种 unknown | 否 |
| GSE278420 | CAD 患者乳内动脉 **snRNA**；槲皮素 vs 安慰剂，不是斑块病变 vs 对照 | needs_review；assay 缺 scRNA 直接描述 | 否 |

## 课题 2：小鼠肝脏 bulk RNA-seq，需要明确实验分组

| 项 | 值 |
| --- | --- |
| 课题 ID | `5979a055b9c04edb81c1892a09608630` |
| 确认条件 | `Mus musculus` / `bulk_rna_seq` / tissue=`liver`（硬）/ required_metadata=`group`（硬，不臆造处理–对照标签） |
| 规划失败任务 | `e4533c9a2339452ebfa1edd8228e3c8e`：round 1 把 `(bulk OR RNA-seq)` 当疾病，27763 命中，前 20 条为人图谱/小胶质/白血病等 |
| **采用任务** | `08d9301284eb4d19aab25de805349757` |
| 起止 | 2026-09-05T16:23:27Z → 16:26:01Z（约 154 s） |
| 检索 | `liver AND (RNA-seq OR …) AND "Mus musculus"[ORGN] AND GTYP AND gse`，命中 9960，取 20 |
| Token | prompt 57100，completion 11756 |
| 分类 | recommended 0 / needs_review 20 / excluded 0 |
| Excel（当时） | `data/exports/08d9301284eb4d19aab25de805349757/GEOScout_ds-live-mouse-liver-bulk_20260905T163154Z.xlsx`；SHA-256 `3672a5cba64e7b456c8438d444432f8fc6b882ad4083bde52798a6a446001792`；Recommended 0 行 |
| Excel（2026-09-06 重导） | `GEOScout_ds-live-mouse-liver-bulk_20260906T032450Z.xlsx`；SHA-256 `77ae60f9d7095326ce325c30ae7eacd4c0b93cbbc861ad2d4230bfad46f6d1c5` |

前 20 条多为小鼠且标题含 liver / hepatocyte / MASLD（如 GSE305809 hepatocytes bulk、GSE309725 MASLD）。深核 3 条仍为 needs_review（硬条件 unknown 或核验未完成），**没有**为了出推荐而改判。

## 课题 3：人类动脉粥样硬化 scRNA-seq，每组 ≥3 独立供体，必须有年龄和性别

| 项 | 值 |
| --- | --- |
| 课题 ID | `17158bdf9aa3468eb3e9dcb1116b5838` |
| 确认条件 | 与课题 1 相同的病变/对照，另加 **hard** `donors_per_group=3`、`age`、`sex`（启发式把年龄性别当成 soft，确认时改为 hard） |
| **采用任务** | `9d672ba6cafb4955bbb7a8dc9250db01` |
| 起止 | 2026-09-05T16:26:49Z → 16:31:13Z（约 264 s） |
| Token | prompt 60762，completion 18089 |
| 分类 | recommended 0 / needs_review 19 / excluded 1（GSE253320 硬失败 groups） |
| Excel（当时） | `data/exports/9d672ba6cafb4955bbb7a8dc9250db01/GEOScout_ds-live-athero-scrna-strict_20260905T163155Z.xlsx`；SHA-256 `48ab00d6746ce565935622097c867c7c14c8e6eb5f6132caf7616a18c6529d47`；Recommended 0 行，Excluded 仅 `GSE253320` |
| Excel（2026-09-06 重导） | `GEOScout_ds-live-athero-scrna-strict_20260906T032451Z.xlsx`；SHA-256 `07af993f032aa30f57c8661d3bfb104cb89e462519817d12f3962f4c83b29671` |

年龄/性别在 GEO 特征里缺失时为 **unknown，不是 fail**，因此不能 recommended。GSE218166 仅 2 个 GSM、无 age/sex 字段，深核后仍 needs_review。符合「缺证据不得推荐」。

## 费用估算（Flash off-peak cache-miss 上界）

计入提供商 usage 的任务（含课题 1 JSON 失败那次、课题 2 规划失败那次）：

| 任务 | prompt | completion |
| --- | ---: | ---: |
| 课题 1 JSON 失败 `a0a8d28c…` | 55685 | 13345 |
| 课题 1 采用 `9aebbdf6…` | 56965 | 15681 |
| 课题 2 规划失败 `e4533c9a…` | 55764 | 15377 |
| 课题 2 采用 `08d93012…` | 57100 | 11756 |
| 课题 3 采用 `9d672ba6…` | 60762 | 18089 |
| **合计** | **286276** | **74248** |

估算：`286276 × 0.22e-6 + 74248 × 0.66e-6 ≈ $0.063 + $0.049 = $0.11`。  
未计入：连接测试、课题解析（parse 在 run 之外）、中断任务 `19d7db84`（token_usage 空）。若存在 cache hit，实际会更低。

## 完整路径对照

| 步骤 | 课题 1 | 课题 2 | 课题 3 |
| --- | --- | --- | --- |
| 解析 | 是（LLM 污染分组，已人工确认） | 是（补 liver + group） | 是（年龄性别改为 hard） |
| 用户确认 spec | 是 | 是 | 是 |
| 扩词 | 是 | 是（第一次有病，已修后重跑） | 是 |
| 真实 GEO 检索 | 是 | 是 | 是 |
| 首次判断 + 独立复核 | 是 | 是 | 是 |
| 候选详情 | 是 | 是 | 是 |
| Excel + openpyxl 重读 | 是 | 是 | 是 |

## 2026-09-06 复核：契约、样本证据、推荐数

当日复测**没有**重跑 DeepSeek。历史任务分类保持原样；下面三项已改代码，需另一次真实模型复测后才能当作正式 v0.1。

### 1. 非法 `verdict` 保持「模型输出无效」

选择严格校验：`{"verdict": "maybe"}` 不得归一成看起来正常的 `unknown`。`PASS`→`pass` 仍允许。  
`test_invalid_model_json` 与 `check_model_assessment` 会把整份输出标 `invalid`。  
后端 `-m "not network and not llm_live"`：**98 passed, 1 deselected**。

### 2. 样本级证据进入 assess/verify；摘要缺词不能 fail

- 模型输入改为 `judge_user_payload`：`samples[]`、`sample_records_available`、压缩后的 summary，以及原 evidence。
- 深核 SOFT 后为每条 GSM 写入 `soft.sample.{GSM}.record`。
- 供体/分组/技术/年龄/性别的 **fail** 必须引用 sample/GSM 证据，否则降为 unknown（线索）。
- 尚未深核时，仅凭这些字段的模型 fail **不能排除**（`classify` → needs_review）。物种/gdstype 等规则 fail 仍可在初筛排除。

**GSE253320（课题 3，未改库）：** `verification_status=summary_screened`，无 GSM。规则把 `groups` 判 **unknown**。模型引用 `esummary.summary`（体外芯片/oxLDL）判 groups **fail**，final 采纳 fail，于是 excluded。这是「摘要未写 lesion/control 组织」被当成明确不满足，不是样本级否定。修复后同类输入应为 needs_review / unknown，等有 SOFT 样本再判。  
**GSE218166（课题 3）：** 首次模型把 `donors_per_group` 写成 fail（「样本数仅 2」）。规则与 final 是 unknown。2 个 GSM 已在库中，但当时 verify 输入没有 `samples[]`。修复后必须看 GSM 的 donor_key，不能用 GSM 条数当供体数。

### 3. Recommended 数量：库 / 详情 API / Excel 一致

采用任务里 **Recommended 都是 0 行**。报告「仅表头」指 `Recommended` sheet 无 GSE 数据行。README 里有一行列名「推荐」，那是类别定义，不是命中数据集。`data/exports` 里另一份带 Recommended 数据行的文件是 mock 流水线 `GSE333565`，不是这三次 DeepSeek 任务。

| 任务 | run ID | DB | `GET /api/runs/{id}/datasets` | 当时 Excel | 2026-09-06 重导 |
| --- | --- | --- | --- | --- | --- |
| 1 | `9aebbdf6…` | rec 0 / review 20 / excl 0 | 同左 | rec 0 / review 20 / excl 0 | 同左 |
| 2 | `08d93012…` | rec 0 / review 20 / excl 0 | 同左 | rec 0 / review 20 / excl 0 | 同左 |
| 3 | `9d672ba6…` | rec 0 / review 19 / excl 1（GSE253320） | 同左；详情 API `excluded` / `硬条件失败: groups` | 同左 | 同左 |

文件哈希不同只因为重导生成了新文件；**分类计数未变**（未重跑模型）。

## 2026-09-06 DeepSeek 复测（修复后）

重启 API/worker 以加载样本级输入与严格 verdict。Key 仍只在会话内存。沿用上次已确认 spec，不重新 LLM 解析。GEO 最新 20 条与 9 月 5 日不同，不能逐条对照旧 GSE 列表。

| 课题 | run ID | 预算 | 状态 | DB / Excel | 模型输出无效 | tokens (p/c) | Excel SHA-256 |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| 1 `ds-retest-athero-scrna` | `5b9fa514645f45149a55128ad0a307f7` | 与上次相同，含 `max_tokens=80000` | partial：先卡在旧排队任务，清理后跑完；**verify 中途达到 token 预算** | rec 0 / review 20 / excl 0 | 8（均为复核缺 `verdict`） | 70603 / 10198 | `7a24e03fdbbc644ed536270811abd5629eaa6531fcdb1679e81b246a65d449c0` |
| 2 `ds-retest-mouse-liver-bulk` | `9f233ae98eca4f708136c230fcf72976` | `max_tokens=200000`（否则样本输入会再次截断） | partial：唯一 GSE 上限 | rec 0 / review 20 / excl 0 | **20/20 复核无效** | 182803 / 11796 | `7c5254abe79ee4e2474e90b31f678498d4ac40c191bf074a5e0a13dc4dd01a7a` |
| 3 `ds-retest-athero-scrna-strict` | `9a7330a8638440478f8cd88e021a9713` | `max_tokens=200000` | partial：唯一 GSE 上限 | rec 0 / review 19 / excl 1（GSE316714 disease） | 13（复核缺 `verdict`） | 87600 / 18321 | `aa127e6fc75891c4109127c7dfb7da4bb5902ba90b195a5708888a121bd9bac7` |

费用上界（Flash off-peak cache-miss）：`(341006×0.22 + 40315×0.66)/1e6 ≈ $0.10`。未计入连接测试。详情 API 与 Excel 分类与库一致；Recommended 仍为 0 行。

### 复测对上的修复

- **GSE253320（课题 3）**：本次在最新 20 条中。`summary_screened`、无 GSM。规则与模型都把 groups / donors_per_group 判 **unknown**（「样本记录不可用」），类别 **needs_review**，不再因摘要未写 lesion/control 而 excluded。旧任务 `9d672ba6…` 未改库，仍是 excluded。
- 深核 SOFT 后写入了 `soft.sample.{GSM}.record`（课题 1 该 run 有 52 条样本证据）。
- 非法/缺失 `verdict` 仍标模型输出无效，没有降成正常 unknown。

### 复测新问题（所以仍不能当稳定 v0.1）

1. **样本输入显著加大 prompt**。课题 1 在旧的 80k token 预算下 verify 未跑完。课题 2 肝脏 GSM 多，prompt 到 18 万。
2. **复核 JSON 常缺 `verdict` 字段**（`Field required`）。首次 assess 无此条；课题 2 复核 20/20 无效。严格契约生效了，但复核质量这次没有真正测到。
3. **GSE316714 被排除，理由 disease**，证据是 `esummary.summary`（murine disease model 时间序列）。NCBI taxon 仍是 `Homo sapiens`。这与旧的「摘要推断」同类，疾病字段尚未纳入「无样本不能 fail」门闩，需人工看。
4. 重启后 worker 被库里遗留的 pytest/`waiting_for_credentials` 任务占满，复测脚本曾把课题 1 误判超时。已用取消接口清掉这些残留任务。

## 2026-09-06 固定三件套（live NCBI + DeepSeek）

同一检索式，不扩大自然语言检索：

`GSE333565[Accession] OR GSE325203[Accession] OR GSE1000[Accession]`

课题仍是 human / `scrna_seq` / atherosclerosis / groups=`lesion`,`control`（启发式，未再 LLM 解析）。预算：`max_queries=1`，`max_unique_gse=3`，`max_deep_verify=3`，`max_tokens=200000`。模式：`full` + 该 `manual_query`（否则不会深核 SOFT）。

**GSE333565 真实 SOFT 是 bulk RNA-seq（TEBV / HGPS），不能当 scRNA 阳性对照。未为了出 recommended 而放宽条件。**

### 第一次（`3c6f525953d447ef8f6dab16983bb74b`）——未当作通过

约 34 s 正常结束。导出当时 DB/API/Excel 为 rec 0 / review 2 / excl 1。随后迟到的 verify 把三类都写成 `needs_review`，Excel 仍是 GSE1000 excluded。

| 问题 | 现象 |
| --- | --- |
| `inclusion_criteria_eval` | DeepSeek 根对象无 `judgements`，schema `Field required`；**格式修复事件 = 0** |
| array 初筛 | GSE1000 `gdstype=Expression profiling by array`，初筛却是「技术类型证据不足」，仍走了两轮 LLM |
| 完成态 | 旧 worker 未杀掉；finalize 后仍执行已租约的 verify，库与 Excel 分叉 |

Excel：`GEOScout_ds-live-fixed-trio_20260906T043826Z.xlsx`；SHA-256 `0ea46139576f57ede5950a980a456b8fd5ca717103559157463fe5853fdd1054`。

### 第二次（`11d27f6e17b948ae9da371e0864e95af`）——本轮按报告修完后重跑

代码：解开 `inclusion_criteria_eval`；array 初筛把 `criterion.value` 收成字符串列表，并读 `gdstype`/`type`；完成态不再入队/执行迟到步骤；格式修复前写「开始格式修复」。重启时杀掉了 API **和** `app.worker`（含残留 pid 24572）。Key 只在内存迁移，未写入文件或本报告。

| 项 | 值 |
| --- | --- |
| 课题 | `ds-live-fixed-trio`（`f8c5ba640f3a4f1ca2f5a8bf0e3ee11b`） |
| 起止 | 2026-09-06T04:59:51Z → 05:00:16Z（约 25 s） |
| 状态 | `completed` / 正常结束；结束后无 queued/leased 任务 |
| Token | prompt 24820，completion 1735（GSE1000 不再打模型） |
| 分类 | DB = 详情 API = Excel：**GSE1000 excluded，GSE325203 needs_review，GSE333565 excluded** |
| GSE1000 | `rule_excluded`；assay fail「GEO 技术类型为微阵列…」；无 SOFT、无 `assess_model`/`verify_model` |
| GSE325203 | 深核 + 两轮模型；理由「硬条件缺少有效直接证据」，**不是**复核失败 |
| GSE333565 | 深核 + 两轮模型；模型 JSON 有效后 disease fail（HGPS 体外模型），硬条件失败排除。assay 仍 unknown，未当成 scRNA 推荐 |
| 格式修复 | 本跑 **0 次**：首次输出已通过 schema（`model_output_invalid=0`，无「核验无效」事件）。路径由 `test_assessment_format_repair_runs_once` 覆盖（非法 spec 形状 → 「开始格式修复」→ 成功） |
| 任务链 | plan/search/summaries/screen + 3 deep_fetch（2 条 GSE + 收尾）+ 3 assess + 3 verify + 1 finalize，无重复 finalize |
| Excel | `data/exports/11d27f6e17b948ae9da371e0864e95af/GEOScout_ds-live-fixed-trio_20260906T050022Z.xlsx` |
| SHA-256 | `4dfd0e89a7a87b27658e390e8d09fcb516230d369b19ff757eb19efd6971c9ba` |
| Key 泄漏 | 0 |

费用上界（Flash off-peak cache-miss）：`(24820×0.22 + 1735×0.66)/1e6 ≈ $0.007`。未计入连接测试。

本轮证明：固定三件套上 **excluded / needs_review 在库、详情 API、Excel 一致且结束后不再被改写**；array 在初筛排除；模型别名 `inclusion_criteria_eval` 能进契约。  
**仍不能宣布 DeepSeek 真实模型流程通过，也不能当稳定 v0.1 发布。** 未做自然语言课题检索。

## 未验证 / 已知限制

- GEO 网页抽查被 NCBI recaptcha 挡住；课题 1 深核对照的是本机 SOFT 快照，不是浏览器里的 Series 页。
- 提供商 usage 未拆 cache hit/miss；费用是上界。
- 20 GSE / 3 深核是刻意小预算，不是穷尽检索。课题 2 即使修好 round 1，命中仍约 1 万，只看最新 20 条。
- 多数 `summary_screened` 行仍报「核验未完成」：非深核样本上模型漏答 soft 的 `processed_matrix` 会把整次复核标 incomplete。未为了推荐而关闭该门闩。
- 连接测试、解析、扩词、核验都打到了 `api.deepseek.com`；**没有**出现 `recommended` 数据集。本报告不把「流程跑通」写成「找到了合格队列」。
- 复核阶段 DeepSeek 经常省略 `verdict`，严格校验会整份作废；样本级 prompt 体积还没有做截断。

## 结论

GEOScout v0.1 的软件基础可以继续试用，DeepSeek 接入也已基本打通。  
**还不能正式宣布 DeepSeek 真实模型流程通过，也不建议马上把它作为稳定 v0.1 发布。**  
分组「无样本则 unknown」在 GSE253320 上已经对上；但 token 预算、复核 JSON 缺字段、以及疾病条件仍可凭摘要 fail，都还要再修再测。
