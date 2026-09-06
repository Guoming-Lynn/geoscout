# GEOScout

本地运行的 GEO 数据集发现与核验工具。用户自备模型 Key，系统扩展检索词、访问 NCBI GEO、用证据做二次检查，并导出可复查的 Excel。

**不承诺穷尽全部 GEO、零漏检，或自动证明某数据集可用于特定科研结论。**

## 要求

- Python 3.11+
- Node 20+
- 本机网络可访问 `https://eutils.ncbi.nlm.nih.gov` 与 `https://ftp.ncbi.nlm.nih.gov`

## 本地启动

在仓库根目录：

```bash
cd backend
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端：

```bash
cd backend
python -m app.worker
```

再开终端：

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)

API：[http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

Windows 可用 `powershell -File scripts/dev.ps1`（需已安装依赖）。

## 无需模型 Key 的路径

设置页可稍后填写模型。工作台支持 **手工英文检索**：直接输入 GEO DataSets 检索式（会自动附加 `"gse"[ETYP]`），worker 真实访问 NCBI E-utilities，列出唯一 GSE 并导出 Excel。

## 模型 Key

默认只保存在 API 进程内存，不写入 SQLite、日志、Excel 或浏览器 localStorage。重启后未完成任务会进入「等待凭据」，重新填写后可从检查点继续。取消不能退回已发出的模型费用。

NCBI API Key 与模型 Key 分开，均为可选。NCBI 联系邮箱请填你自己的地址。

## Docker Compose

端口只发布到宿主回环地址：

```bash
docker compose up --build
```

- Web: http://127.0.0.1:5173
- API: http://127.0.0.1:8000

## 测试

```bash
cd backend
python -m pytest -m "not network and not llm_live"
python -m pytest -m network   # 真实 NCBI 冒烟，需联网
```

真实模型测试不在默认 CI 中。未配置 Key 时不得宣称完整流程已验证。

演示模式必须同时设置 `GEOSCOUT_ALLOW_DEMO=true` 与 `GEOSCOUT_DEMO_MODE=true`。真实检索失败不会改用演示数据。

## 许可证

MIT。GEO 数据版权与使用以 NCBI 政策为准；本工具默认不重新分发大型附件。
