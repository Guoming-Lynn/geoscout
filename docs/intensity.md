# Review intensity

The workbench can override the deep-review count while preserving the selected tier's token, runtime and retrieval limits. The API field is deep_limit (0 to the tier's candidate cap); an explicit budget still takes precedence. Increasing this number does not raise the token cap or guarantee all targets finish. Dataset detail shows persisted selection factors and selected order. These are ranking heuristics, not eligibility evidence.

Sample source is an optional hard constraint (direct primary samples, cell line/iPSC, organoid, xenograft). Tissue matching can separately be required. Defaults preserve old topics. Unknown provenance remains unknown; human/patient-derived alone does not prove primary collection. Primary includes directly collected control samples as well as patient samples; disease/control criteria determine the groups. Model parsing cannot silently add these restrictions. Use the structured editor for sources that the conservative parser does not recognize.

Sample payloads have a shared 40,000-character cap for deep assessment at all tiers. Compact raw characteristics avoid duplicated text, and records alternate across derived group/species/assay buckets. Oversized records are omitted whole; any omitted record keeps sample coverage incomplete. This cap is separate from tokens and does not guarantee all samples fit. Generic disease/control topics use case/control groups. Derived group inventories count GSM records, never independent donors, and do not replace original sample evidence.

The UI defaults to medium. Limits are maxima, not promised coverage or costs.

| Tier | Queries | Unique GSE | SOFT/deep targets | Tokens | Runtime |
| --- | ---: | ---: | ---: | ---: | ---: |
| Low | 4 | 80 | 0 | 20,000 | 10 minutes |
| Medium | 8 | 150 | 6 | 150,000 | 30 minutes |
| High | 16 | 400 | 20 | 600,000 | 90 minutes |
| Ultra | 40 | 1,500 | 100 | 4,000,000 | 6 hours |

Ultra increases retrieval and evidence-review budgets. It does not switch models or enable provider thinking mode. Current DeepSeek JSON requests disable thinking. Independent first assessment and review are used for deep targets at every tier; missing evidence still prevents recommendation.

The UI reads /api/budget-presets. POST a run with tier set to low, medium, high, or ultra. Explicit budget overrides take precedence and are recorded as custom. Requests without tier retain legacy one_click screen/deep behavior.

Token/runtime guards apply before external actions and each model fallback. Model requests additionally reserve estimated input plus the requested output allowance before dispatch. These estimates are not provider billing caps. There is no strict per-HTTP-model-call cap; bounded format fallbacks and repairs can add calls. Every attempted model response contributes usage even if its content is empty or invalid. Missing usage reserves estimated input and the output allowance, marks the total as estimated, and increments missing_usage_requests. It is never evidence of zero cost. Explicit criteria parsing has a separate cumulative project total, also included in new runs' configuration snapshots. No exact currency estimate is promised.

Queries now have persistent query_index order, with the original query first. Each pending query gets a share of remaining capacity; unused capacity rolls forward. Already retrieved UIDs do not consume later query shares. Paging is bounded, so this is still not exhaustive retrieval and a larger tier is not guaranteed to contain every candidate from a smaller run.

Low remains summary screening with zero deep targets. It is for candidate discovery. Do not treat Low/Medium/High/Ultra as accuracy grades.

Deep targets are ranked by direct disease relevance, sample-material tissue/source evidence versus background mentions, patient/control context, and supported criteria. Similar titles are deferred only among near scores so diversity cannot replace a much stronger hit with an off-tissue study. The selected IDs are checkpointed before fetching so a resume does not change the target list. Ranking is a heuristic, not eligibility evidence or a probability.

Mixed species/assay records with a potentially usable subset remain unknown instead of being excluded as a whole. Mixed-study passes require explicit GSM subsets; missing or incomplete evidence cannot justify whole-study failure. Retained live records were replayed offline after these changes; no new live-model accuracy claim follows from that replay. Patient tissue versus model semantics, bounded sample coverage and unvalidated processed matrices remain limitations. Further representative live evaluation is needed before stable-release claims.
