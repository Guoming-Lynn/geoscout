# Security

- 默认监听 `127.0.0.1`。Docker 端口只发布到宿主回环地址。
- 模型 Key 与 NCBI Key 仅存在于进程内存（及用户自己的环境变量）。不要写入数据库、日志、Excel、JSON 审计包或 URL。
- 报告漏洞请用 GitHub Security Advisory 私下提交，不要在公开 issue 里粘贴含 Key 的日志。
- 自定义模型 Base URL 与 GEO 下载入口隔离；GEO 抓取仅允许 NCBI 官方域名。
- 本仓库当前版本是单用户本地工具，不能直接暴露到公网。
