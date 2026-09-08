# GEOScout

<div align="center">

**GEO dataset discovery, with evidence you can review.**


[![CI](https://github.com/Guoming-Lynn/geoscout/actions/workflows/ci.yml/badge.svg)](https://github.com/Guoming-Lynn/geoscout/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-10b981)](LICENSE) ![Status: Research preview](https://img.shields.io/badge/Status-Research%20preview-0891b2)

</div>

![GEOScout product poster](docs/assets/geoscout-github-poster-light-v2.png)

GEOScout is a local tool for finding and screening datasets in NCBI GEO. Turn a research question into structured criteria, retrieve candidate studies, inspect sample-level evidence, and export a workbook for human review. Use your own model provider, or start with manual NCBI search without a model key.

**Research question → Structured criteria → GEO search → Evidence review → Excel export**

| Step | What you can do |
| --- | --- |
| Define | Inspect disease, organism, tissue, assay and sample-source constraints. |
| Discover | Search GEO with topic terms and optional model-assisted query expansion. |
| Review | Inspect sample-level evidence and recommendation reasons. |
| Control | Choose Low, Medium, High or Ultra intensity; pause, resume or cancel. |
| Export | Keep decisions, evidence and applicable GSMs in a reviewable workbook. |

For the full Chinese walkthrough, see [README.zh-CN.md](README.zh-CN.md).

**GEOScout does not promise exhaustive GEO coverage, zero false negatives, or proof that a dataset supports a specific scientific conclusion.**

> **Current release: very early research preview.**
> Local execution, criteria parsing, sample-level hard-condition screening, run controls and Excel export have been exercised. Accuracy, recall and systematic scientific reliability have not been established. Review every recommendation manually.

## Requirements

- Python 3.11+
- Node 20+
- Network access to `https://eutils.ncbi.nlm.nih.gov` and `https://ftp.ncbi.nlm.nih.gov`

## Start locally (recommended trial)

Install dependencies once:

```bash
cd backend && python -m pip install -e ".[dev]"
cd ../frontend && npm install && npm run build
```

Then double-click `GEOScout.bat` in the repository root. It starts the API, worker and UI on `127.0.0.1:8000` and opens a browser. **Close that terminal to stop GEOScout.** Do not start another worker.

If port 8000 is occupied, stop the previous GEOScout, uvicorn or Vite process first.



The first screen is the connection page. Test a model key, or enter using NCBI-only search.

API：[http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)


## Without a model key


## Model keys

Keys stay in API-process memory by default and are not written to SQLite, logs, Excel or browser localStorage. Restarting may require credentials to resume. Cancellation cannot refund sent requests.

NCBI and model keys are separate and optional. Use your own NCBI contact email.

## Docker Compose

Ports are published to host loopback only:

```bash
docker compose up --build
```

- Web: http://127.0.0.1:5173
- API: http://127.0.0.1:8000

## Testing

```bash
cd backend
python -m pytest -m "not network and not llm_live"
```

Frontend:

```bash
cd frontend
npm ci
npm run build
npm test
npm run test:e2e
```


## Documentation


## Author

[Guoming Lin](https://github.com/Guoming-Lynn)

## License

MIT. GEO records and associated data remain subject to NCBI policies and applicable data terms; large attachments are not redistributed by default.
