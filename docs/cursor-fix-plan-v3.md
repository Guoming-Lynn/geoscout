# GEOScout v0.1 第三轮修复任务书

日期：2026-09-05。请 Cursor 在现有实现上修复，不重写项目。v0.1 仍只处理 GEO；不使用相邻科研项目的 API Key，不删除用户数据。

## 本轮审核依据

- 使用 `D:\miniforge\python.exe` 和独立数据目录运行后端测试：64 passed、1 deselected。
- 真实 NCBI 冒烟测试：1 passed。
- 前端构建通过，Vitest：1 passed。
- 样本重复插入、原先的 no disease 误判及虚构 GSM 用例已有修复和测试。
- 浏览器 E2E 在审核环境中因缺少对应 Chromium 可执行文件而未启动。不能据此断言页面失败，也不能声称审核已复现 4 passed。
- 真实模型未测试。

以下三个 P1 问题已通过代码检查和定向调用复现。先补失败测试，再修复。

## P1-1：跨任务证据关联丢失

位置：`backend/app/evidence/store.py` 的 `evidence_id_for`、`add_evidence` 和 `evidence_bundle`。

证据 ID 由 GSE、字段和内容生成，不含 run_id。第二个任务取得相同证据时，`add_evidence` 直接返回第一个任务的记录，而 `evidence_bundle` 又按 run_id 过滤。因此第二个任务拿不到这些证据。

实际复现：向两个已经存在的 run 添加同一 GSE、同一字段、同一文本的证据，然后分别获取证据包。第一个任务返回 1 条匹配证据，第二个返回 0 条。

修复要求：

- 在以下方案中选择符合现有架构的最小改动：任务内独立证据记录，或全局证据内容加 run-evidence 关联表。
- 相同证据可跨任务复用，但每个任务必须有明确关联；不能把旧证据的 run_id 改成新任务。
- 保留来源 URL、字段路径、获取时间和内容哈希。来源不同的相同文本也不能丢失来源关系。
- 旧 Assessment 引用和历史导出仍可解释，迁移不能破坏历史证据 ID。
- 详情、模型输入和 Excel 都使用本次任务关联的证据，不随其他任务刷新而无声变化。
- 对历史上缺失关联的任务，能可靠重建则重建；无法重建则标明需重新核验，不能伪造历史来源。

验收测试：

1. 两个任务加入相同证据，都能读取到；第一个任务的来源和内容不变。
2. 同一任务重复加入证据不产生重复条目。
3. 第二次完整运行同一 GSE 时，模型证据包和 Excel Evidence 非空且正确关联。
4. 同一 GSE 更新元数据后，旧任务仍能解释旧判断，新任务引用新内容。

## P1-2：分组规则仍会把病变判为对照

位置：`backend/app/pipeline/donors.py` 的 `_has_word`、`_normalize_group` 和 `infer_group_label`。

实际复现：

```text
abnormal             -> control
uncontrolled disease -> control
untreated tumor      -> control
no disease           -> control
```

前两项是子串匹配错误；第三项暴露出疾病状态与处理状态混淆。未治疗肿瘤样本仍是肿瘤样本；是否可作为某实验的对照取决于用户要求。

修复要求：

- 英文词使用词边界或明确短语匹配，normal 不能命中 abnormal，control 不能命中 uncontrolled。
- 对否定、疾病、处理、基因型等属性分别解析，禁止仅按哪个关键词先匹配决定组别。
- 使用字段语义和 ResearchSpec 确认对照类型；健康对照、邻近组织、未处理组、野生型不能无条件互换。
- 扫描多个有关特征字段，不因第一个字段含有弱线索而忽略明确的疾病信息。
- 冲突或无法确定时返回 unknown，并保留原始字段和冲突说明。
- 避免仅针对这三个例子增加特殊分支。让分组规则能解释为何某样本满足本次课题要求。
- 保留上轮对 no disease、non-diseased 等否定表达的正确处理。

验收测试：

1. abnormal 不判为健康对照；信息不足时 unknown。
2. uncontrolled disease 不因 control 子串而进入对照。
3. 要求健康与肿瘤分组时，untreated tumor 不能计入健康组。
4. 要求治疗与未治疗肿瘤分组时，依据处理状态正确分组，保留共同肿瘤属性。
5. disease=tumor 且 treatment=untreated 的多字段样本与前述结论一致。
6. 健康、邻近组织、未处理、WT 的对照类型分别测试，不能错误互换。
7. 重新测试每组供体数，确保分组错误不再影响 pass/fail。

## P1-3：qualifying_gsms 技术一致性检查不充分

位置：`backend/app/pipeline/assessment.py` 的 `_bind_qualifying_gsms`，以及最终条件合并逻辑。

当前已能拒绝虚构或不属于输入样本集合的 GSM，但文库策略检查基本只验证是否含 rna。bulk、scRNA-seq、snRNA-seq 都可能使用 RNA-Seq，不能据此证明细分技术。

实际复现：用户要求 scRNA-seq，输入一个标题明确为 bulk RNA-seq、library_strategy=RNA-Seq 的 GSM，模型把它列为 assay 条件的合格 GSM；`check_model_assessment` 返回 invalid=False。

修复要求：

- 为样本技术判定保留来源证据，结合样本协议、特征、来源与研究中的明确子集对应关系。
- RNA-Seq 仅证明宽泛技术，不能单独证明 bulk/sc/sn。
- 有明确矛盾时拒绝模型的 pass；证据不足时降为 unknown 或待核实，不应宣称输出有效且满足条件。
- 如果研究级协议可以明确映射到一组 GSM，可据此判定，但保存这种映射的证据。
- 核验不同硬条件引用的是同一个可用样本子集，避免物种来自 A 子集、技术来自 B 子集、分组来自 C 子集。
- 组别检查不仅验证每个 GSM 的标签属于允许集合，还要检查要求的各组是否覆盖；供体阈值按适用子集重新计算。
- Excel 和详情展示所采用的子集、证据及仍未知的条件。

验收测试：

1. 明确 bulk 的样本不能满足 scRNA-seq 条件。
2. 只有 RNA-Seq 而无细分技术证据时不得自动通过 sc/sn。
3. 明确 sc 和 sn 协议分别通过对应条件。
4. 混合研究中仅列出真正满足要求的子集，并在该子集内判断分组与供体数。
5. 不同条件各自找到样本，但不存在共同可用子集时不得推荐。
6. 保留原有虚构 GSM、外 GSE GSM 和错误物种回归测试。

## 测试与交付

先执行新增回归，再运行全部后端测试。使用独立测试数据库，且增加复用同一数据库连续运行两次的验证，不能通过每次清空数据库掩盖重复运行问题。

执行后端 mock、真实 NCBI 小规模冒烟、前端 build 和 Vitest。下载 Excel 并用 openpyxl 重读，核对两个任务的证据关联和最终结果。

浏览器方面核实实际使用的 Playwright 版本、浏览器版本和 `PLAYWRIGHT_BROWSERS_PATH`。安装成功后记录可复现的启动环境；若受环境限制未运行，交付报告明确说明。不要把历史测试结果复制成本轮结果。

真实模型测试只在用户配置凭据后运行。缺少 Key 时以 mock 验证工作流，但保留真实模型未验证的说明。

完成后更新 `docs/delivery.md`：列出本轮修改、测试命令、解释器、结果、迁移方式及剩余限制。不得声称没有经过测量的筛选准确率。

## 给 Cursor 的启动指令

请阅读 `docs/cursor-fix-plan-v3.md`，优先修复跨任务证据关联、分组语义和 qualifying GSM 技术与子集一致性三个 P1 问题。先补可复现的失败测试，再实施修复；保留历史数据及证据引用。完成后验证同一数据库重复运行、Excel 证据链和全部可用测试，更新 delivery.md。保持 GEO-only v0.1，不做无关重构。
