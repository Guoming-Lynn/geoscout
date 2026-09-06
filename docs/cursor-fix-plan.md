# GEOScout v0.1 审核修复任务书

日期：2026-09-05。目标读者：接手修复的 Cursor。

## 执行目标

在现有 GEOScout 上修复筛选可靠性和交付可复现性。v0.1 只接入 GEO，不扩展其他数据库，不重做 UI，不改动项目外的科研数据。先读仓库 AGENTS.md、README 和本文件，再直接实施。保留已有用户数据；数据库结构变化必须提供迁移。

本轮审核只新增本文件，未修复应用代码。以下区分已确认缺陷、环境限制和待补查项，不应把所有项目都视为已经复现的运行错误。

## 1. 已完成的审核与实际试用

- 正在运行的 API `/api/health` 返回正常，NCBI 和 LLM 模式均为 live。
- `npm run build` 通过。
- 创建审核任务 `review-smoke`，真实检索 `GSE1000[Accession]`，返回唯一 GSE1000，标题为 Osteosarcoma TE85 cell tissue culture study，10 个 GSM，技术为芯片。
- 任务 ID：`33fe5fc965124eb3b86570237e266191`，状态 completed。
- 导出接口成功生成 `GEOScout_review-smoke_20260905T092755Z.xlsx`。本次尚未下载重读工作簿及检查其布局，不能将接口成功当成 Excel 内容已经验证。
- 当前默认 Python 为 `D:\python\python.exe`，执行 pytest 报缺少模块；这说明当前解释器不能复现测试，不证明原报告的测试结果虚假。
- Playwright 的桌面和手机测试因缺少对应 Chromium 可执行文件而未启动，不是已确认的页面功能错误。
- 没有使用真实模型 Key，没有验证真实模型端到端流程，也没有完成浏览器交互试用。

## 2. P1：按组核验独立供体数

位置：`backend/app/pipeline/spec_parse.py` 的 donors_per_group 条件、`backend/app/pipeline/screening.py` 的 `_donors`，以及 SOFT 样本解析和供体关系存储。

已确认：条件描述为“每组最少独立供体”，但 `_donors` 使用所有样本的 `len(set(keys))` 与阈值比较，没有按组计算。

修复要求：

- 根据明确证据建立 GSM、供体和实验组的关系，按用户要求的每个组分别去重。
- 同一供体的重复文库不增加供体数。配对设计下同一供体可分别属于两个组，不得把它当两个全局独立供体。
- 分组或供体 ID 不完整时返回 unknown，并说明缺什么信息。仅凭总人数足够不能通过每组人数条件。
- 完整证据证明某组不足时才能 fail；部分获取的样本不足不能证明整个研究不足。
- 混合物种/技术/组织研究的计数必须限定到同一个适用子集。

验收：病例 6、对照 0 不能满足每组 3；病例 3、对照 3 可通过；一个供体三份文库只计一人；分组缺失、供体缺失和截断分别返回未知；配对样本按各组正确计数。

## 3. P1：阻止无证据或漏答条件进入推荐

位置：`backend/app/pipeline/engine.py` 的 `_checked_assessment`、`step_verify`；`backend/app/pipeline/screening.py` 的 `classify`；`backend/app/schemas/spec.py`。

已确认：

- `_checked_assessment` 只遍历已提供的 evidence_ids；pass/fail 的 evidence_ids 为空时仍可通过。
- 没有对照 ResearchSpec 检查未知条件 ID、重复 ID 和缺失条件。
- `step_verify` 仅在两次模型都返回条件时比较，否则继续沿用规则判断。
- 无硬条件分支只要 judgements 非空就推荐，即使全部 unknown，也未证明主题相关。

修复要求：

- 校验器接收本次 ResearchSpec，拒绝未知或重复的 criterion_id。漏答条件补为 unknown，并记录未完成核验。
- pass/fail 必须有有效来源支持；unknown 可无证据。支持引句与证据逐项关联，不能让多个来源共用一句引文并要求每个来源都包含它。
- 模型没有输出、输出无效或漏答，不自动继承弱关键词规则的 pass。确定性规则可独立支持结论，但必须列出有限的规则范围、证据及判定理由。
- 规则也区分直接证据和线索。例如“标题有 control”不能证明目标子集中存在符合要求的对照。
- 推荐必须满足：全部硬条件有有效证据、所需深度核验完整、要求的复核完成且无未决冲突。
- 无硬条件时仍需主题直接证据；全部 unknown 必须待核实。
- 修正 verification_status 与 category 的一致性，模型输出无效时不能仍显示 verified。

验收：空引用 pass、虚构引用、引句不符、未知 ID、重复 ID、漏答硬条件、两次判断冲突均不能导致推荐；有效证据的正确判断可以通过。mock 模型测试必须包含完整成功路径，不能仅测试固定 unknown。

## 4. P1：保存并导出最终证据链

位置：`backend/app/pipeline/engine.py` 的 step_assess/step_verify、Assessment 表、详情 API、`backend/app/exporters/`。

已确认：合并判断创建 `CriterionJudgement(... reason=rule.reason, evidence_ids=[])`，丢弃模型引用，理由仍沿用规则文本；当前流程没有将这些最终合并判断按最终阶段完整保存为 Assessment。

修复要求：

- 分别保存规则判断、第一次模型判断、独立复核和最终判断，不只保存规则行或一段难以追溯的 JSON。
- 最终结果保留真实采用的 evidence_id、来源、引文、判断者及简短理由；不能用与结论不一致的规则理由代替模型理由。
- 冲突保留两侧证据；人工覆盖保留原结论、新结论、理由和时间。
- 详情 API、页面和 Excel 使用同一最终结果快照，避免不同入口展示不同结论。

验收：至少构造一条有证据的推荐记录、一条冲突记录、一条人工覆盖记录，逐条件从 Excel/详情追到原始证据。重新读入 xlsx 比对状态、理由和 evidence_id，确认与数据库一致。

## 5. P1：修正会过度判断的规则

位置：`backend/app/pipeline/screening.py`。

已确认的风险实现：

- 处理后矩阵规则根据 h5/csv/txt 等文件名或后缀返回 pass，尽管理由承认尚未验证格式。
- bulk RNA-seq 规则由高通量表达谱且没有单细胞表述推断 pass；发现单细胞表述则可能排除含 bulk 子集的混合研究。
- 年龄字段直接做子串匹配，`age` 可命中无关单词。
- 物种和技术等各自从整项研究匹配，缺少样本子集一致性约束。

修复要求：文件名只产生 probable 线索；必要矩阵条件在没有足够证明时 unknown。临床字段按解析后的字段名及有限同义词匹配。bulk/sc/sn 技术分别判断，缺少描述不视为证明。混合研究必须指出同一组符合条件的 GSM，否则待核实。

验收覆盖：只有 txt 文件、无明确技术描述、混合 bulk/sc、无年龄但包含 macrophage、不同物种子集分别满足不同条件等反例，不得误推荐或过早排除。

## 6. P1：核实预算和不完整检索的真实行为

这是补查并修复任务：已有 max_tokens/max_runtime_s 配置字段，但上轮阅读尚未确认有效的执行检查。不要只检查字段存在。

- 全局搜索预算字段的所有引用，证明运行时实际限制时间、token、查询数、唯一 GSE 和深核条目数。
- 检查 ESearch 在命中数超过上限时是否记录截断。目前分页逻辑受 max_unique_gse 限制，但还需确保不把未取完的查询标为完整正常结束。
- 检查多查询新增条目时全局上限是否超出，重复命中是否浪费全部名额。
- 必须在调度下一次外部请求前检查预算；token 用量未知时显式标记估算，不当作零消耗。配置合理的输出限制；阐明在途调用导致的有界超额。
- 预算停止进入 partial，保存停止原因和未完成范围，已有结果允许导出。

验收：小预算 + mock 大结果集，确认请求次数、记录数和状态；token/时间达到阈值后不再安排新调用。重启恢复仍保留已用预算。

## 7. P2：恢复测试环境并扩展真实工作流验证

不要根据缺少 pytest 就覆盖全局 Python 环境。优先确认交付时使用的解释器或虚拟环境；必要时在项目中创建独立环境，按锁定依赖安装。

执行：

```text
backend:  <项目Python> -m pytest -m "not network and not llm_live"
backend:  <项目Python> -m pytest -m network
frontend: npm run build
frontend: npm run test
frontend: npx playwright install chromium
frontend: npm run test:e2e
```

网络不可用或安装失败时记录真实原因，不把未运行测试写成通过。

现有 E2E 只覆盖标题和设置标签，需增加：创建手工检索任务、运行状态、候选详情、Excel 下载、无结果、连接错误；使用确定性 mock 验证暂停/恢复/取消，另做低请求量真实 GEO 冒烟。

浏览器验证桌面和手机尺寸，截图检查表格、详情、设置和错误状态。真实模型测试仅在用户配置凭据后运行；不得从相邻科研项目搜集或复用 Key。

## 8. P2：确认凭据丢失的恢复路径

代码补查：`Engine.run` 在主 try 之前调用 hydrate_credentials，而 hydrate_credentials 收到 404 会抛 WaitingForCredentials。确认此异常是否绕过预期的 waiting_for_credentials 状态处理。

若复现，统一处理异常并保存检查点；无模型 Key 的手工检索不应因此永久等待。验收覆盖 API 重启、worker 重启、会话不存在、重新输入凭据后恢复，且日志和导出没有 Key。

## 9. 交付顺序与要求

1. 先为第 2 至 5 节的错误补最小回归用例，观察旧实现失败，再实施修复。
2. 完成第 6、8 节补查，修复可复现问题并记录证据。
3. 运行后端、前端、真实 GEO 和浏览器验证；下载 Excel 并重读内容。
4. 更新 `docs/delivery.md`，区分代码完成、mock 通过、真实 GEO 通过、真实模型未测及环境阻塞。写明解释器、命令、日期和结果。
5. 提供变更清单、测试结果、剩余限制和可访问地址；不得把“构建成功”写成“所有功能已验证”。

完成标准：手工 GEO 链路仍可用；每组供体计数正确；无证据和漏答不能推荐；最终证据可在页面与 Excel 追溯；预算截断如实展示；新增回归测试通过。没有真实模型测试时，可以交付经 mock 验证的实现，但必须保留该验证限制。

## 10. 给 Cursor 的启动指令

请阅读 `docs/cursor-fix-plan.md`，在现有 GEOScout 上按优先级实施修复。v0.1 只处理 GEO。先验证已有代码，再为已确认问题编写回归测试并修复；对标记为补查的项目先复现。不要只修改交付文案，不要重写整个项目，不要读取或使用相邻项目中的 API Key。完成后运行测试、真实 GEO 小规模试用、浏览器流程和 Excel 重读检查，更新 delivery.md，并报告实际通过及未执行的验证。
