# Hand-checked examples (not an accuracy study)

These are qualitative fixtures for source, grouping and cohort behaviour. They are not a recall or accuracy estimate. Do not cite pass counts from this list as product metrics.

| Example | Expected source | Expected groups | Eligible GSM subset | Category intent |
| --- | --- | --- | --- | --- |
| HEK293T maintained in DMEM + 10% FBS | `cell_line`, never `primary` | n/a | none for a primary request | cannot recommend as primary |
| PBMC, protocol “No cell lines were used” | `primary` | n/a | keep PBMC | must not become `cell_line` |
| Cultured primary tissue as `source_name` | unknown | n/a | none | stay unknown |
| T2D RNA-seq, disease GSMs = cases only, groups = cases+controls | n/a | case + control | cases **and** controls | API/Excel cohort must include controls |
| Mixed human RNA-seq case + mouse case | n/a | incomplete after filter | human only | must not recommend the mixed union |
| Age hard on cases only, controls lack age | n/a | not covered | not a full comparison queue | groups become unknown |
| Brain biopsy Alzheimer vs whole-blood Alzheimer | n/a | n/a | ranking only | brain biopsy outranks blood/heart background mentions |

Low intensity still uses **0 SOFT downloads**. It is a discovery/screening budget, not a more accurate tier.

Paid Medium runs with eight deep targets on 2026-09-07 used stored GEO evidence for later gate replay. Those six targeted prompt calls are not a full pipeline rerun of the final code, and must not be described as such.
