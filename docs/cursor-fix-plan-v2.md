# GEOScout v0.1 第二轮修复建议

请 Cursor 阅读并执行本文件。只修改 `geoscout` 项目，不读取或使用相邻项目的 API Key。

## P1：修复重复深度获取的唯一键冲突

现象：同一个 GSE 重复运行或任务恢复时，`backend/app/pipeline/engine.py` 深度获取阶段会重复插入相同 `(gse, gsm)`，触发：

```text
sqlite3.IntegrityError: UNIQUE constraint failed: samples.gse, samples.gsm
```

修复要求：

- 按 `(gse, gsm)` 对 `Sample` 做 upsert；已有记录应更新元数据，不重复插入。
- 同一 GSE 在两个不同任务中使用时，不能破坏已有任务的结果和证据。
- 任务重试、worker 重启和重复深度获取都必须幂等。
- 数据库已有重复风险时，提供迁移或启动检查；不得删除用户数据。

回归测试：同一 GSE 连续执行两次深度获取，第二次成功；样本总数不重复；两个 run 都能引用样本和证据。

## P1：修复否定分组误判

已复现：

```text
no disease       -> lesion
non-diseased     -> lesion
```

原因是 `backend/app/pipeline/donors.py` 的简单子串匹配会让 `disease` 命中否定表达。

修复要求：

- 归一化前优先识别否定表达，至少覆盖 `no disease`、`non-diseased`、`non-disease`、`without disease`、`disease-free`。
- 否定疾病、健康、正常和未处理的表达不能归入 `lesion`。
- 保留 `healthy control`、`normal adjacent tissue` 等明确对照表达。
- 处理大小写、连字符和多余空白。
- 无法确定的描述返回 `None`，进入待核实，不强行分组。

回归测试：否定疾病词不会被识别为 lesion；明确健康/正常表达识别为 control；模糊表达返回未知。

## P1：校验 qualifying_gsms

当前模型判断如果提供不存在的 GSM，仍可能凭有效 evidence 进入推荐。

修复要求：

- `qualifying_gsms` 中的每个 GSM 必须属于当前 GSE 已获取的样本集合。
- GSM 必须与相应物种、技术和分组条件一致；不能只检查字符串格式。
- 不存在、属于其他 GSE 或没有完成样本获取的 GSM，应使该判断无效或进入 `needs_review`。
- 证据引用、`qualifying_gsms` 和最终条件判断必须一起保存。

回归测试：虚构 GSM、其他 GSE 的 GSM、真实 GSM 分别验证；虚构 GSM 不能推荐。

## P2：重新验证环境与交付报告

使用交付报告指定的解释器和独立测试目录运行：

```powershell
cd geoscout/backend
D:\miniforge\python.exe -m pytest -m "not network and not llm_live" -p no:cacheprovider
D:\miniforge\python.exe -m pytest -m network -p no:cacheprovider

cd ../frontend
npm run build
npm run test
npx playwright install chromium
npm run test:e2e
```

Playwright 仍缺 Chromium 时，记录安装失败原因，不能写成 E2E 通过。下载一次真实 Excel 并用 `openpyxl` 重读，确认 Candidates、Evidence、Queries 和 Run_info 一致。

## 完成标准

- 重复检索、重试和恢复不再触发 Sample 唯一键冲突。
- 否定疾病描述不会污染 lesion 供体计数。
- 虚构或不属于当前 GSE 的 qualifying GSM 不能进入推荐。
- 后端回归测试、真实 NCBI 冒烟、前端构建和前端单测通过。
- E2E 若未执行，交付报告明确标为环境阻塞。
- 更新 `docs/delivery.md`，写明实际命令、解释器、日期、通过项和剩余限制。

## 给 Cursor 的启动指令

请阅读 `docs/cursor-fix-plan-v2.md`，先为三个 P1 问题补回归测试，再实施修复。保持 GEO-only v0.1 范围，不重写无关模块。完成后运行全部可用测试和真实 NCBI 小规模试用，重读 Excel，并更新 `docs/delivery.md`。不要把上一轮报告中的历史结果当作本轮已验证结果。
