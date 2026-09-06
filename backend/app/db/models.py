from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    original_request: Mapped[str] = mapped_column(Text, default="")
    spec_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    runs: Mapped[list["Run"]] = relationship(back_populates="project")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(80), default="")
    mode: Mapped[str] = mapped_column(String(40), default="manual_query")
    spec_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    budget_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(40), default="planning")
    stop_reason: Mapped[str] = mapped_column(Text, default="")
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    config_summary: Mapped[str] = mapped_column(Text, default="{}")
    counters_json: Mapped[str] = mapped_column(Text, default="{}")
    token_usage_json: Mapped[str] = mapped_column(Text, default="{}")
    checkpoint_json: Mapped[str] = mapped_column(Text, default="{}")
    prompt_versions: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")
    duplicate_billing_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="runs")
    query_attempts: Mapped[list["QueryAttempt"]] = relationship(back_populates="run")
    run_datasets: Mapped[list["RunDataset"]] = relationship(back_populates="run")
    jobs: Mapped[list["Job"]] = relationship(back_populates="run")
    events: Mapped[list["Event"]] = relationship(back_populates="run")
    exports: Mapped[list["Export"]] = relationship(back_populates="run")


class QueryAttempt(Base):
    __tablename__ = "query_attempts"
    __table_args__ = (UniqueConstraint("run_id", "query_hash", name="uq_run_query"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    query_hash: Mapped[str] = mapped_column(String(64))
    term: Mapped[str] = mapped_column(Text)
    round_no: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(40), default="user")
    hit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_unique_gse: Mapped[int] = mapped_column(Integer, default=0)
    retstart: Mapped[int] = mapped_column(Integer, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    query_translation: Mapped[str] = mapped_column(Text, default="")
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    error_message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[Run] = relationship(back_populates="query_attempts")


class Dataset(Base):
    __tablename__ = "datasets"

    gse: Mapped[str] = mapped_column(String(40), primary_key=True)
    uid: Mapped[str] = mapped_column(String(40), default="")
    title: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    taxon: Mapped[str] = mapped_column(Text, default="")
    gdstype: Mapped[str] = mapped_column(Text, default="")
    gpl: Mapped[str] = mapped_column(Text, default="")
    n_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pdat: Mapped[str] = mapped_column(String(40), default="")
    pubmed_ids: Mapped[str] = mapped_column(Text, default="[]")
    suppfile: Mapped[str] = mapped_column(Text, default="")
    ftplink: Mapped[str] = mapped_column(Text, default="")
    bioproject: Mapped[str] = mapped_column(String(80), default="")
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Sample(Base):
    __tablename__ = "samples"
    __table_args__ = (UniqueConstraint("gse", "gsm", name="uq_gse_gsm"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    gse: Mapped[str] = mapped_column(ForeignKey("datasets.gse"), index=True)
    gsm: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    organism: Mapped[str] = mapped_column(Text, default="")
    source_name: Mapped[str] = mapped_column(Text, default="")
    characteristics_json: Mapped[str] = mapped_column(Text, default="[]")
    library_strategy: Mapped[str] = mapped_column(Text, default="")
    donor_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    group_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    attrs_json: Mapped[str] = mapped_column(Text, default="{}")
    coverage_incomplete: Mapped[bool] = mapped_column(Boolean, default=False)


class DatasetRelation(Base):
    __tablename__ = "dataset_relations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    gse: Mapped[str] = mapped_column(String(40), index=True)
    relation_type: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(80))
    evidence: Mapped[str] = mapped_column(Text, default="")


class RunDataset(Base):
    __tablename__ = "run_datasets"
    __table_args__ = (UniqueConstraint("run_id", "gse", name="uq_run_gse"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    gse: Mapped[str] = mapped_column(ForeignKey("datasets.gse"), index=True)
    hit_queries: Mapped[str] = mapped_column(Text, default="[]")
    category: Mapped[str] = mapped_column(String(40), default="needs_review")
    verification_status: Mapped[str] = mapped_column(String(40), default="summary_only")
    soft_source: Mapped[str] = mapped_column(String(40), default="")
    processed_data: Mapped[str] = mapped_column(String(40), default="unknown")
    raw_data: Mapped[str] = mapped_column(String(40), default="unknown")
    file_listing_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    link_check_status: Mapped[str] = mapped_column(String(40), default="unchecked")
    matrix_availability: Mapped[str] = mapped_column(String(40), default="unknown")
    gsm_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    biosample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    independent_donors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    donors_per_group_json: Mapped[str] = mapped_column(Text, default="{}")
    cell_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hard_unknowns: Mapped[int] = mapped_column(Integer, default=0)
    soft_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    soft_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    concerns: Mapped[str] = mapped_column(Text, default="")
    first_assess_json: Mapped[str] = mapped_column(Text, default="{}")
    verify_assess_json: Mapped[str] = mapped_column(Text, default="{}")
    conflict_json: Mapped[str] = mapped_column(Text, default="[]")
    model_output_invalid: Mapped[bool] = mapped_column(Boolean, default=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)

    run: Mapped[Run] = relationship(back_populates="run_datasets")
    dataset: Mapped[Dataset] = relationship()


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    gse: Mapped[str] = mapped_column(String(40), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    field_path: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunEvidence(Base):
    __tablename__ = "run_evidence"
    __table_args__ = (UniqueConstraint("run_id", "evidence_id", name="uq_run_evidence"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), index=True)
    source_url: Mapped[str] = mapped_column(Text, default="")
    field_path: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rebuilt: Mapped[bool] = mapped_column(Boolean, default=False)


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    gse: Mapped[str] = mapped_column(String(40), index=True)
    criterion_id: Mapped[str] = mapped_column(String(80))
    verdict: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str] = mapped_column(String(40))
    evidence_ids: Mapped[str] = mapped_column(Text, default="[]")
    quote: Mapped[str] = mapped_column(Text, default="")
    quotes_json: Mapped[str] = mapped_column(Text, default="[]")
    reason: Mapped[str] = mapped_column(Text, default="")
    judge_source: Mapped[str] = mapped_column(String(40), default="")
    actor: Mapped[str] = mapped_column(String(40), default="")
    support_text: Mapped[str] = mapped_column(Text, default="")
    clue_only: Mapped[bool] = mapped_column(Boolean, default=False)
    qualifying_gsms_json: Mapped[str] = mapped_column(Text, default="[]")


class Override(Base):
    __tablename__ = "overrides"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    gse: Mapped[str] = mapped_column(String(40), index=True)
    previous_category: Mapped[str] = mapped_column(String(40))
    new_category: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    step: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str] = mapped_column(String(80), default="")
    checkpoint_json: Mapped[str] = mapped_column(Text, default="{}")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="jobs")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    level: Mapped[str] = mapped_column(String(20), default="info")
    message: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="events")


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(300))
    complete: Mapped[bool] = mapped_column(Boolean, default=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), default="")
    include_json: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="exports")
