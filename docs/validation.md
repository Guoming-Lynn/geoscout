# Validation

## Automated (no real model key)

`cd backend && python -m pytest -m "not network and not llm_live"`

Covers ResearchSpec hard/soft split, query dedup, UID≠accession, SOFT table skip, donor dedup, mixed organism trap, clinical-unknown ≠ fail, species fail, Excel injection, redaction, mock pipeline + export.

## NCBI smoke

`python -m pytest -m network`

Hits live ESearch/ESummary for `GSE1000[Accession]`. Records that UIDs mix GSE/GDS/GPL.

## Model live

Not run unless a key is present. Default CI must not claim a full LLM-backed screening path is verified.

## Playwright

Requires the built frontend. `cd frontend && npm run build && npx playwright test` starts Vite preview on `127.0.0.1:5173` and, unless `GEOSCOUT_E2E_BASE_URL` is set, an isolated FastAPI process with `GEOSCOUT_NCBI_MODE=mock` and `GEOSCOUT_LLM_MODE=mock`. Topic-switch tests still intercept `/api` in the browser. The search→detail→Excel case does not: it drives the real mock NCBI client, worker, and Excel writer, and checks that the download is a ZIP/xlsx (not a placeholder string). That is still not live GEO or a paid model.

Live NCBI/model browser checks are separate: set `GEOSCOUT_E2E_LIVE=1` and run a real API on port 8000. For an already running bundled API/UI, set `GEOSCOUT_E2E_BASE_URL=http://127.0.0.1:8000`. Do not treat a skipped live test as a pass.

The 2026-09-07 screening fixes passed 151 offline backend tests, frontend build and 5 unit tests, plus 6 desktop/mobile browser tests against an isolated mock backend. Offline replay of 33 retained live records protected 12 unsupported mixed-study exclusions and retained GSE305454. This was not a repeat live-model benchmark. See [screening fixes](screening-fixes-20260907.md).

## Known limits

The source-constraint/deep-limit update passed 189 offline backend tests, 5 frontend unit tests, frontend build and 4 desktop/mobile startup/workbench browser tests. A final focused rerun passed 15 source/budget tests. The browser checks exercise source selection, hard tissue toggle, deep count input and horizontal overflow. This update has not received a new paid-model trial; source inference deliberately leaves ambiguous patient-derived or cultured samples unknown.

The subsequent paid source trial ran three Medium topics with **eight** deep targets (not the default 6) and hard primary/tissue constraints: 50 model calls and 392254 reported tokens. It exposed overly narrow primary-material recognition and an incorrect intersection between case-only disease evidence and the full case/control cohort. Six later prompt calls on three retained GEO records used stored evidence, not a full pipeline rerun; replay through a later gate is not a complete paid retest of the final code. See `data/source-live-medium8-20260907/review.md` and [gold examples](gold-examples.md). This is not an accuracy or recall benchmark.

Low remains 0 SOFT targets: it discovers candidates from summaries. The four intensity tiers are budget presets, not accuracy grades.

The final group-evidence follow-up passed 176 offline backend tests (1 live test deselected), frontend build and 5 unit tests, plus 4 desktop/mobile startup/workbench tests. Backend tests run from the backend directory to resolve this checkout. Ten paid Low/Medium runs finished with 30 deep downloads and 10 checked exports (435111 reported tokens). Final gate replay demoted one ATAC/RNA mixed-study false recommendation; the other 9 recommendations remained. Four prompt-candidate calls and six final targeted calls added 93287 tokens. Final targeted calls use stored GEO evidence, not a full pipeline rerun. Reports are under data/group-evidence-live-v2-20260907/review.md; none of this establishes blinded accuracy or exhaustive recall.

Keyword grids are not an exhaustive scan of GEO. Soft-score is not accuracy or probability. Independent donor counts stay empty when characteristics lack a donor key.
