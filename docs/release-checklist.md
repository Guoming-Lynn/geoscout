# GEOScout 发布前检查清单

本清单用于 **超级早期公开预览**。勾选通过只代表发布链路和已覆盖行为可复现，不代表科学准确率或召回率已经建立。

## 自动检查

- [ ] `backend`: `python -m pytest -m "not network and not llm_live" -q`
- [ ] `frontend`: `npm ci && npm run build && npm test`
- [ ] `frontend`: `npm run test:e2e:install && npm run test:e2e`
- [ ] 在联网环境执行 `backend`: `python -m pytest -m network -q`

## 人工冒烟

- [ ] 启动页可选择仅 NCBI 检索，不填模型 Key 也能进入工作台。
- [ ] 使用 `GSE1000[Accession]` 创建手工检索任务，看到 GSE1000 且被识别为芯片并排除。
- [ ] 打开数据集详情并导出 Excel，Excel 可重新读取，证据和类别与页面一致。
- [ ] 模型 Key 错误、NCBI 网络失败、任务暂停/恢复/取消都有明确状态和原因。
- [ ] 重启 API 后，未完成任务显示等待凭据并可恢复；Key 不出现在日志、SQLite 或导出文件。

## 发布边界

- [ ] `data/` 中的数据库、缓存、导出、试用目录和 npm 缓存未进入提交（仓库只保留 `data/.gitkeep`）。
- [ ] 没有把内部备忘、本机路径或含 Key 的日志放进公开分支。
- [ ] README、隐私说明和 NCBI 使用限制与当前版本一致。
- [ ] 没有模型 Key 时，发布说明明确写出真实模型链路尚未验证。
