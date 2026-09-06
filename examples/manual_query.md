# Manual query example (no model key)

In the workbench, create a project then run:

```
atherosclerosis AND "Homo sapiens"[ORGN] AND "Expression profiling by high throughput sequencing"[GTYP]
```

GEOScout appends `"gse"[ETYP]` if missing. This path uses NCBI E-utilities only.
