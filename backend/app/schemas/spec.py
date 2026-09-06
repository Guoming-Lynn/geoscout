from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Priority = Literal["hard", "soft"]
AssayType = Literal["bulk_rna_seq", "scrna_seq", "snrna_seq"]
OrganismName = Literal["Homo sapiens", "Mus musculus"]
MatrixReq = Literal["none", "preferred", "required"]
Verdict = Literal["pass", "fail", "unknown"]
RunStatus = Literal[
    "queued",
    "running",
    "pausing",
    "paused",
    "waiting_for_credentials",
    "completed",
    "partial",
    "failed",
    "cancelled",
]
RunStage = Literal["planning", "searching", "fetching", "screening", "verifying", "exporting"]
Category = Literal["recommended", "needs_review", "excluded"]


class Criterion(BaseModel):
    criterion_id: str
    field: str
    description: str
    user_text: str
    priority: Priority = "hard"
    value: Any = None


class ResearchSpec(BaseModel):
    original_request: str = ""
    disease: list[str] = Field(default_factory=list)
    tissues: list[str] = Field(default_factory=list)
    organisms: list[str] = Field(default_factory=list)
    assay_types: list[AssayType] = Field(default_factory=list)
    required_groups: list[str] = Field(default_factory=list)
    control_type: str | None = None
    minimum_donors_per_group: int | None = None
    paired_design: bool | None = None
    required_metadata: list[str] = Field(default_factory=list)
    preferred_metadata: list[str] = Field(default_factory=list)
    processed_matrix_requirement: MatrixReq = "preferred"
    inclusion_criteria: list[Criterion] = Field(default_factory=list)
    exclusion_criteria: list[Criterion] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)

    @field_validator("organisms")
    @classmethod
    def normalize_organisms(cls, values: list[str]) -> list[str]:
        mapping = {
            "human": "Homo sapiens",
            "homo sapiens": "Homo sapiens",
            "人": "Homo sapiens",
            "人类": "Homo sapiens",
            "mouse": "Mus musculus",
            "mus musculus": "Mus musculus",
            "小鼠": "Mus musculus",
        }
        out: list[str] = []
        for item in values:
            key = item.strip()
            mapped = mapping.get(key.lower(), key)
            if mapped not in out:
                out.append(mapped)
        return out


class Budget(BaseModel):
    max_rounds: int = 3
    max_queries: int = 30
    max_unique_gse: int = 1000
    max_deep_verify: int = 100
    max_runtime_s: int = 1800
    max_tokens: int = 200_000
    max_completion_tokens: int = 4096
    esearch_page_size: int = 100
    summary_batch_size: int = 40


class PlannedQuery(BaseModel):
    term: str
    round_no: int
    source: str
    concept_groups: list[str] = Field(default_factory=list)


class TermEntry(BaseModel):
    term: str
    group: str
    origin: Literal["user", "lexicon", "model", "discovered"]


class CriterionJudgement(BaseModel):
    criterion_id: str
    verdict: Verdict
    evidence_ids: list[str] = Field(default_factory=list)
    quote: str = ""
    quotes: list[str] = Field(default_factory=list)
    reason: str = ""
    qualifying_gsms: list[str] = Field(default_factory=list)
    clue_only: bool = False
    judge_source: str = ""
    support_text: str = ""


class ModelAssessment(BaseModel):
    judgements: list[CriterionJudgement]
    concerns: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class ConnectionConfigIn(BaseModel):
    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str | None = None
    llm_timeout_s: float = 60.0
    llm_input_price_per_mtok: float | None = None
    llm_output_price_per_mtok: float | None = None
    ncbi_api_key: str | None = None
    ncbi_email: str | None = None
    ncbi_tool: str | None = None


class ProjectCreate(BaseModel):
    name: str | None = None
    original_request: str


class RunCreate(BaseModel):
    mode: Literal["manual_query", "full"] = "full"
    manual_query: str | None = None
    one_click: bool = False
    budget: Budget | None = None
    demo: bool = False


class OverrideIn(BaseModel):
    category: Category
    reason: str


class ExportIn(BaseModel):
    include_json: bool = True
    selected_only: bool = False
