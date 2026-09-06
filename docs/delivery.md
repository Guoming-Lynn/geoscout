# GEOScout 交付报告

日期：2026-09-05（本轮对照 `docs/cursor-fix-plan-v3.md`）

## 访问地址

- 工作台：http://127.0.0.1:5173
- API 健康检查：http://127.0.0.1:8000/api/health
- 启动：仓库根目录 `powershell -File scripts/dev.ps1`，或按 README 分三个终端启动 API / worker / Vite

本轮验证前已用 `D:\miniforge\python.exe` 重启 API 与 worker（NCBI=live，LLM=live，无模型 Key），以加载本轮代码。Vite 仍监听 127.0.0.1:5173。

## 本轮修复

代码已完成。v0.1 仍只接 GEO。没有把上一轮交付数字当作本轮已验证。

| 项 | 代码 | mock 测试 | 真实 GEO | 真实模型 |
| --- | --- | --- | --- | --- |
| 跨任务证据关联（内容复用 + `run_evidence` 关联，不改旧 `run_id`） | 完成 | 通过（两任务可读同一内容；同任务去重；元数据更新后旧任务仍保留旧文本；不同来源 URL 分任务保存） | 两任务手工检索 GSE1000，详情各 4 条证据，Excel Evidence 均非空 | 未测 |
| 分组按属性解析（词边界；否定/疾病/处理/基因型分开；对照类型不互换） | 完成 | 通过（abnormal / uncontrolled disease / untreated tumor；healthy vs adjacent vs untreated vs WT） | 未用真实 SOFT 金标准复测 | 未测 |
| qualifying GSM 的 bulk/sc/sn 细分与共同子集 | 完成 | 通过（明确 bulk 不能当 sc；仅 RNA-Seq 不能自动过 sc/sn；sc/sn 各过对应条件；混合研究只留匹配子集；无共同子集不得推荐；虚构/外 GSE/错物种回归保留） | 手工检索不做模型 GSM 列表 | 未测 |

迁移：新建 `run_evidence`（Alembic `004`）。历史 `evidence.id` 不变。启动时从 `evidence.run_id` 和 `assessments.evidence_ids` 重建关联；引用已不存在的证据 ID 不伪造来源，导出时在疑点中标明需重新核验。不删用户数据。

课题解析不再把笼统的 `rna-seq` 写成 `bulk_rna_seq`；已标明 sc/sn 时不加 bulk。

## 测试范围（2026-09-05，解释器 `D:\miniforge\python.exe`）

独立测试目录 `backend/tests/_tmpdata`，并加 `-p no:cacheprovider`。同一 SQLite 上连续两次手工检索的 mock 用例已覆盖，不是每次清空库。

```text
backend: D:\miniforge\python.exe -m pytest -m "not network and not llm_live" -p no:cacheprovider
          83 passed, 1 deselected
backend: D:\miniforge\python.exe -m pytest -m network -p no:cacheprovider
          1 passed（真实 NCBI ESearch/ESummary）
frontend: npm run build          通过
frontend: npm run test           1 passed
frontend: npm run test:e2e       4 passed（desktop + Pixel 5）
```

### Playwright 环境（本轮实测，不是复制历史）

- `@playwright/test` / CLI：1.63.0
- Chromium：Chrome for Testing 153.0.8010.12（playwright chromium v1243）
- `PLAYWRIGHT_BROWSERS_PATH`：`C:\Users\13305\AppData\Local\Temp\cursor-sandbox-cache\b121b58dc1f1adc6f51e59221f932ccc\playwright`
- 本机该路径下已有 `chromium-1243`，`npm run test:e2e` 实际启动并 4 passed

审核机若未设置同一 `PLAYWRIGHT_BROWSERS_PATH` 或缺少该 Chromium 目录，E2E 可能无法启动；不能用其他机器的历史 4 passed 代替审核环境结果。

Playwright 覆盖：工作台标题与设置「请求将发往」；创建课题、手工检索、运行状态、GSE1000 详情、导出 Excel、设置测试连接（无 Key 时告警）。暂停/恢复/取消由后端 mock 覆盖。

## 真实 GEO 冒烟与 Excel 重读

同一生产库连续两个任务，均为手工检索 `GSE1000[Accession]`（应用附加 `"gse"[ETYP]`）。本轮重启后新跑，不是复用上一轮 xlsx。

| 任务 | 状态 | 详情证据 | 导出 |
| --- | --- | --- | --- |
| `97c12f57a1ce441bae4036f9cc6a1a18` | completed / 正常结束 | 4 条（title/summary/taxon/gdstype） | `data/fix-plan-v3-live-97c12f57.xlsx` |
| `3efac73dd69847498d833a1ec0ea8373` | completed / 正常结束 | 4 条，字段相同，关联在本任务 | `data/fix-plan-v3-live-3efac73d.xlsx` |

两份工作簿均用 openpyxl 重读：

- Candidates：GSE1000，标题 Osteosarcoma TE85 cell tissue culture study，官方链接，最终类别 needs_review，核验完成状态 summary_screened（手工检索不做深度核验，预期如此）
- Evidence：含 rule_screen；处理后矩阵 unknown；表头含合格GSM、判断者、支持文本
- Queries：命中 1、新增唯一 GSE 1、截断=no
- Run_info：manual_query / completed / 正常结束
- 工作簿未出现 API Key

副本：`data/fix-plan-v3-live.xlsx`（第一份任务）

## 真实模型

**未执行。** 未配置模型 API Key，也未从相邻科研项目读取 Key。assay 细分与共同子集由 mock 模型输出与规则校验覆盖，不得写成真实模型核验已验证。未测量筛选准确率。

## 未完成 / 已知限制

- 没有 50–100 条人工金标准评估集，也没有准确率数字
- 深度 SOFT 对超大系列有字节上限；截断不能用来证明每组供体不足
- 关键词网格不是 GEO 全库穷尽
- 公开云部署仍被规格禁止
- 在途 NCBI/LLM 请求可能造成有界超额
- token 缺失按估算累计并标记 `estimated`
- 否定分组与对照类型由单测覆盖，未用真实 SOFT 金标准复测
- 历史上 Assessment 引用了已删除证据 ID 时只能标明需重新核验，不能恢复原文
