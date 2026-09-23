# Validation

Offline checks do not establish accuracy or recall.

```bash
cd backend
python -m pytest -m "not network and not llm_live"
python -m pytest -m network
```

```bash
cd frontend
npm ci
npm run build
npm test
npm run test:e2e
```

Playwright starts Vite preview and, unless `GEOSCOUT_E2E_BASE_URL` is set, an isolated API with mock NCBI and mock LLM. Topic-switch tests intercept `/api` in the browser. The search, detail, and Excel test drives that mock API and checks that the download is an xlsx file. Set `GEOSCOUT_E2E_LIVE=1` only for a separate live NCBI or model check. A skipped live test is not a pass.

Low discovers candidates from summaries and does not download SOFT. The four intensity tiers are budget presets, not accuracy grades. Keyword search is not an exhaustive scan of GEO. A soft score is not a probability. Independent donor counts stay empty when sample characteristics have no donor key.

Older trial notes are in [archive](archive/). They describe earlier code and must not be read as a result for the current release.
