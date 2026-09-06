# 贡献

1. 不要把真实 API Key 写入仓库、issue 或导出样例。
2. NCBI 字段名、端点和查询语法以官方文档及真实请求为准，不要从记忆编造。
3. 演示/mock 数据必须显式标记；禁止把演示结果当作 live 失败的回退。
4. 新增判断必须带 evidence_id；模型不得生成 accession。
5. 提交前运行 `python -m pytest -m "not network and not llm_live"`。
