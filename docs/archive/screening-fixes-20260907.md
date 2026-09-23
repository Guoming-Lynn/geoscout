# Screening and usage fixes

The Low/Medium trial exposed unsupported exclusions of mixed studies, unstable query execution, low-value deep selections, and lost usage on empty model responses.

## Changes

- Array plus sequencing studies remain pending subset review. Mixed-species/model failures cannot exclude a study that may contain a matching subset. Explicit mixed-study passes require named GSM subsets and the existing common-subset checks.
- Query order and per-query allocation are persisted and migrated for existing databases. Cross-query UID deduplication allows later queries to use their allocation on new hits. Search retries keep the failed query pending.
- Deep selection uses inspectable relevance reasons and title diversity, not the largest unknown count. The shortlist is checkpointed before fetching. These are discovery heuristics, never grounds for eligibility.
- Usage is recorded on every model attempt before output validation, including empty responses and failed fallbacks. Missing usage is marked and conservatively estimated. Each fallback rechecks budget; DeepSeek fallbacks retain disabled thinking. Explicit parsing has a separate persisted project usage total. The UI shows input plus output and labels estimates.
- Event streaming uses a fresh short-lived database session per poll and returns the connection before yielding, so completion is observed without holding stale state. Network failures retain their actual cause.

## Evidence and scope

Offline replay against 33 retained records from the five-disease trial changed all 12 previously identified mixed-species/assay exclusions to needs_review and retained the supported GSE305454 recommendation. This rechecks the recorded evidence and model judgements; it is not a new live-model benchmark. Production scientific logic was not changed during the original trial.

The old reports and raw trials are retained in the ignored data directory. Regression tests cover mixed-study exclusions, pure wrong-species exclusions, incomplete evidence, quota ordering/deduplication, legacy schema migration, relevance/diversity, failed-response usage, parse usage, retry budgets and event-stream lifecycle.

Remaining limits: finite retrieval can omit suitable studies; relevance scores need broader calibration; patient tissue/model source is not yet a dedicated structured criterion; the model sees a bounded sample payload; processed matrices are not opened to prove usability; token estimates are not currency caps. Existing completed runs retain their historical results. Start a new run to apply the new rules.

## Subsequent paid retest

### Group evidence follow-up

Generic disease/control requests now use case/control, while explicit lesion requests retain their meaning. Group inference uses the current research specification and raw sample labels, recognizes scoped disease abbreviations, and ignores stale cached group labels. Patient alone, another disease, WT and untreated do not establish the requested disease/control groups.

The sample payload cap is 40,000 characters with compact raw characteristics and balanced group/species/assay ordering. All 30 previously downloaded deep targets fit during offline replay. GSE248417 now includes all 98 samples (49 case and 49 control), instead of a prefix containing only disease samples. Any actual omission still marks coverage incomplete.

Reviewer prompts now require original sample quotes and named GSM subsets for group passes, distinguish generic case from anatomical lesion, and require concrete unknown reasons. Query expansion has bounded term counts. These prompt requirements supplement existing deterministic evidence gates; they do not establish model accuracy.

Cancellation now rolls back and retries SQLite lock conflicts, avoids duplicate cancellation events, and returns a retryable 503 if contention persists. Long worker write transactions remain a concurrency limitation; this is bounded error handling, not a redesign of transaction lifetimes.

The paid follow-up exposed GSE200044 as a false recommendation using ATAC samples to satisfy an RNA-seq group criterion. Explicit non-RNA library strategies now prevent study-level RNA inheritance, and even a single claimed subset is checked against the remaining hard conditions. Eight regression tests cover non-RNA strategies, the single-subset gap and a valid RNA subset in a mixed study. Replay of all 30 deep targets demoted that recommendation while retaining the other 9. Final paid targeted tests kept this case unresolved. Citation instructions were also tightened after two exact-quote mismatches; both records passed final targeted citation checks. Historical exports remain unchanged and must not be treated as regenerated final-version results.

A subsequent five-disease Low/Medium live retest exposed an unbounded SOFT download on a genome-tiling methylation array study. Downloads now enforce the byte limit while streaming and a total timeout, and the array rule recognizes that metadata variant. The backend suite passes 154 tests. A fresh ten-run retest completed with provider usage matching recorded usage throughout. It also exposed remaining case/control-to-lesion mapping and sample truncation problems; successful requests do not establish scientific accuracy.
