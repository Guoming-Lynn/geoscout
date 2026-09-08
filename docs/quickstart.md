# GEOScout 人工试用 Quickstart

本地工具：用你的课题去 GEO 找候选 GSE，用证据做初筛和（可选）模型核验，导出可复查的 Excel。

**不承诺穷尽 GEO、零漏检，或自动证明某数据集能直接用于论文结论。**  
多数行会落在「待核实」。没有推荐，不等于程序坏了。

本机只监听 `127.0.0.1`，不要把端口映射到公网。

---

## 1. 环境

- Python 3.11+
- Node 20+
- 能访问 `eutils.ncbi.nlm.nih.gov` 和 `ftp.ncbi.nlm.nih.gov`
- 若要用模型：自备 API Key。Key 只进启动页/设置页密码框，**不要**写进代码、`.env`、聊天或 Excel

建议把数据目录固定到仓库的 `data\`，避免又在 `backend\data` 里长出第二份库：

```powershell
$env:GEOSCOUT_DATA_DIR = "$PWD\data"
$env:GEOSCOUT_NCBI_MODE = "live"
$env:GEOSCOUT_LLM_MODE = "live"
$env:GEOSCOUT_HOST = "127.0.0.1"
```

---

## 2. 启动

**试用（一个窗口）**

仓库根目录双击 `GEOScout.bat`（需已 `pip install -e ".[dev]"`，且 `frontend` 能 `npm run build`）。  
浏览器打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。关掉黑窗口即停止。不要再开第二个 worker。

若 8000 被占用，先关掉旧的 API / Vite / GEOScout 窗口。

**开发（三个进程）**

三个窗口都不要关。

**窗口 1 — API**

```powershell
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**窗口 2 — Worker**（真正跑检索和模型的是它）

```powershell
cd backend
$env:GEOSCOUT_DATA_DIR = "$PWD\..\data"
$env:GEOSCOUT_NCBI_MODE = "live"
$env:GEOSCOUT_LLM_MODE = "live"
$env:GEOSCOUT_API_URL = "http://127.0.0.1:8000"
python -m app.worker
```

**窗口 3 — 界面**

```powershell
cd frontend
npm install
npm run dev
```

开发界面：[http://127.0.0.1:5173](http://127.0.0.1:5173)。启动器界面：[http://127.0.0.1:8000](http://127.0.0.1:8000)。  
先看到连接页：可填模型 Key 并测试，或点 **仅 NCBI 检索进入**。进入后顶栏应显示 `NCBI：live　模型：live　本机监听 127.0.0.1`。  
健康检查：[http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

依赖已经装过时，也可用 `powershell -File scripts\dev.ps1 -SkipInstall`，但仍请在启动前设好上面的 `GEOSCOUT_DATA_DIR`。

---

## 3. 启动后的连接页（要用模型时先做）

打开界面后先进入连接页，不是直接进工作台。

| 项 | 试用建议 |
| --- | --- |
| 模型 Base URL | 按服务商文档填写。DeepSeek 官方填 `https://api.deepseek.com`（**不要**加 `/v1`，程序会自己拼 `/chat/completions`） |
| 模型名 | 例如 `deepseek-v4-flash`，或点 **Fetch models** |
| 模型 API Key | 粘贴后点 **测试连接并开始**。成功即可进入工作台；连接成功不等于整条筛选流水线已验证 |
| NCBI 联系邮箱 | 填你自己的邮箱（NCBI 要求） |
| NCBI API Key | 可选；有则限速从 3 次/秒升到 10 次/秒 |

只想先试 NCBI、不填模型：点 **仅 NCBI 检索进入**。

Key 只在 API 进程内存里。重启 API 后要重新填写，否则任务会变成「等待凭据」。工作台左侧 **设置** 仍可改连接或重测。

---

## 4. 第一次：只试 NCBI（可以不填模型）

1. 课题框随意写一句（例如「人类肺 scRNA-seq」），点 **创建课题**。
2. 「手工英文检索」改成：

   ```text
   GSE1000[Accession]
   ```

3. 点 **真实/当前 NCBI 模式检索**。
4. 等状态变成完成或部分完成。列表里应出现 **GSE1000**（骨肉瘤芯片，不是 scRNA）。
5. 点 **导出 Excel**，用 Excel 打开核对标题、链接、类别。

这条路径**不会**做 SOFT 深核、也不会打模型。适合确认本机 NCBI 通不通。

---

## 5. 第二次：带模型的小课题

1. 确认连接页或设置里 Key 已测通，顶栏仍是 `live`。
2. 写一句明确课题，例如：

   ```text
   人类肺 scRNA-seq，要疾病和对照
   ```

3. **创建课题**。核对物种 / 技术 / 疾病是否被启发式填对。  
   表单里改的条件会在点运行时写回课题。若要用模型重解析，再点 **解析条件**（会花一点 token）。
4. 点 **一键初筛（省 token）**。  
   后端会套便宜档：约 8 条检索、150 个唯一 GSE、**0 次 SOFT**、约 5 万 token。只看 NCBI 摘要和规则初筛，几乎不会出现「推荐」。  
   若确认课题值得花钱，再点 **深入核验（费 token）**：约 24 条检索、500 个 GSE、80 次 SOFT、最高约 100 万 token。不要一上来就点深入。
5. 看运行区：阶段、唯一 GSE、token。觉得够了就 **暂停** 或 **取消**（已发出的模型请求费用退不回）。
6. 三个页签：**推荐 / 待核实 / 排除**。点一行看详情、证据和 GSM。
7. 结束后 **导出 Excel**。初筛后推荐表空着、待核实很多，是正常的；深入档才会做 SOFT 和模型核验。

---

## 6. 你在看什么

| 类别 | 含义 |
| --- | --- |
| 推荐 | 硬条件有直接证据，且深核与复核完成、无未决冲突。只表示通过本工具检查，不是论文可用证明 |
| 待核实 | 信息不够、模型输出不合契约、或还没深核完。这是默认落点 |
| 排除 | 硬条件失败（例如要 RNA-seq 却是芯片），且有可引用证据 |

独立供体数常为空：GEO 样本表不一定有 donor 字段。同一 GSE 被不同课题再次遇到时，内容可复用，但每个任务各自判断。

Excel 在 `data/exports/<任务ID>/`。库文件是 `data/geoscout.db`。不要把 Key 贴进覆盖理由或聊天记录。

取消或暂停不能收回已经发给模型服务商的费用。

---

## 7. 试用时常见现象

- **部分完成 +「达到唯一 GSE 初筛预算」**：命中太多，触到上限。不是崩溃。
- **等待凭据**：API 重启后内存里没有 Key。回连接页或设置里重填，再点恢复。
- **Worker 不干活**：启动器已经内嵌 worker，不要再开第二个。开发模式下确认 worker 窗口还在，且和 API 用同一份 `GEOSCOUT_DATA_DIR`。
- **GEO 网页打不开 / recaptcha**：用详情里的官方链接或本机 SOFT 快照，不要只凭浏览器页判断。
- 芯片 vs 单细胞：要 scRNA 时，`Expression profiling by array` 应在初筛被排除，不应再打模型。

---

## 8. 不要用这次试用证明的事

- 没有「推荐」≠ 工具失败。
- 连接测试通过 ≠ 某家模型的全流程已发布为稳定版。
- 关键词检索不是全库扫描；软条件分数不是准确率。
