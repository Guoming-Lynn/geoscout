# GEO / NCBI access notes

Verified 2026-09-05 against live NCBI services (not guessed).

## E-utilities

- Base: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`
- GEO DataSets database: `db=gds`
- ESearch: `esearch.fcgi?db=gds&term=...&retmode=json&retstart=&retmax=`
- ESummary: `esummary.fcgi?db=gds&id=...&retmode=json`
- EInfo fields used: `ETYP` (Entry Type), `ORGN` (Organism), `GTYP` (DataSet Type), `ACCN` (GEO Accession)

Live ESearch `GSE1000[Accession]` returned mixed UIDs including `200001000` (GSE), `562` (GDS), `100000096` (GPL). **UID is not an accession.** Filter with ESummary `entrytype == GSE` and `accession` starting with `GSE`.

Live filter that worked:

```
"gse"[ETYP] AND "Homo sapiens"[ORGN] AND atherosclerosis AND "Expression profiling by high throughput sequencing"[GTYP]
```

`querytranslation` is stored when NCBI returns it.

Identity parameters: `tool`, `email` (user-supplied, not hardcoded), optional `api_key`.

Rate limits (NCBI Insights / E-utilities help): 3 r/s without key, 10 r/s with key. Limiter is process-wide.

## Files

Official GEO FTP layout (geo_paccess.html): last three digits of the accession become `nnn`.

HTTPS used by this project:

`https://ftp.ncbi.nlm.nih.gov/geo/series/{bucket}/{GSE}/soft/{GSE}_family.soft.gz`

ESummary `ftplink` values such as `ftp://ftp.ncbi.nlm.nih.gov/geo/series/GSE333nnn/GSE333565/` are converted to HTTPS and must remain on `ftp.ncbi.nlm.nih.gov`.

SOFT is parsed as line-oriented `^SERIES/^SAMPLE` and `!Series_*/!Sample_*` attributes. Expression tables between `*_table_begin` and `*_table_end` are skipped. Truncation is recorded; the parser does not silently treat the first N samples as the whole study.
