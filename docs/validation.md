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

Requires frontend + API. `cd frontend && npx playwright test`

Desktop and Pixel 5 viewports check the workbench heading and settings target host.

## Known limits

Keyword grids are not an exhaustive scan of GEO. Soft-score is not accuracy or probability. Independent donor counts stay empty when characteristics lack a donor key.
