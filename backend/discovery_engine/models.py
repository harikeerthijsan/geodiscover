from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    PROGRAM_ADMIN = "PROGRAM_ADMIN"
    PROJECT_MANAGER = "PROJECT_MANAGER"
    DISCOVERY_ANALYST = "DISCOVERY_ANALYST"
    GOOGLE_VALIDATOR = "GOOGLE_VALIDATOR"
    QA_REVIEWER = "QA_REVIEWER"
    CUSTOMER_VIEWER = "CUSTOMER_VIEWER"
    AUDITOR = "AUDITOR"


class GoogleStatus(str, enum.Enum):
    GOOGLE_CHECK_PENDING = "GOOGLE_CHECK_PENDING"
    GOOGLE_PRESENT_CONFIRMED = "GOOGLE_PRESENT_CONFIRMED"
    GOOGLE_POSSIBLE_MATCH = "GOOGLE_POSSIBLE_MATCH"
    GOOGLE_ABSENT_VERIFIED = "GOOGLE_ABSENT_VERIFIED"
    GOOGLE_CHECK_INCONCLUSIVE = "GOOGLE_CHECK_INCONCLUSIVE"


class CandidateStatus(str, enum.Enum):
    RAW_DISCOVERED = "RAW_DISCOVERED"
    NORMALISED = "NORMALISED"
    GOOGLE_CHECK_PENDING = "GOOGLE_CHECK_PENDING"
    GOOGLE_PRESENT_CONFIRMED = "GOOGLE_PRESENT_CONFIRMED"
    GOOGLE_POSSIBLE_MATCH = "GOOGLE_POSSIBLE_MATCH"
    GOOGLE_ABSENT_VERIFIED = "GOOGLE_ABSENT_VERIFIED"
    GOOGLE_CHECK_INCONCLUSIVE = "GOOGLE_CHECK_INCONCLUSIVE"
    QA_PENDING = "QA_PENDING"
    ACCEPTED_GOLD = "ACCEPTED_GOLD"
    ACCEPTED_SILVER = "ACCEPTED_SILVER"
    REJECTED = "REJECTED"
    RELEASED = "RELEASED"


class QualityTier(str, enum.Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    RESEARCH = "RESEARCH"
    REJECTED = "REJECTED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="JSAN Administrator")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.SUPER_ADMIN)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    customer: Mapped[str] = mapped_column(String(255))
    country: Mapped[str] = mapped_column(String(100))
    cities: Mapped[list[str]] = mapped_column(JSON, default=list)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_volume: Mapped[int] = mapped_column(Integer, default=100)
    confidence_threshold: Mapped[int] = mapped_column(Integer, default=70)
    gold_threshold: Mapped[int] = mapped_column(Integer, default=85)
    # Cross-provider match thresholds. Kept separate from the POI quality thresholds
    # above: those score how usable a record is, these score whether two records from
    # different providers describe the same business.
    match_auto_threshold: Mapped[int] = mapped_column(Integer, default=85)
    match_possible_threshold: Mapped[int] = mapped_column(Integer, default=60)
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    candidates: Mapped[list[PoiCandidate]] = relationship(back_populates="project", cascade="all, delete-orphan")


class RawSourceRecord(Base):
    __tablename__ = "raw_source_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    source_name: Mapped[str] = mapped_column(String(100))
    source_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imported_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PoiCandidate(Base):
    __tablename__ = "poi_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    raw_source_record_id: Mapped[int | None] = mapped_column(ForeignKey("raw_source_records.id"), nullable=True)
    poi_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    source_name: Mapped[str] = mapped_column(String(100), index=True)
    source_type: Mapped[str] = mapped_column(String(100), default="FILE_UPLOAD")
    source_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_name: Mapped[str] = mapped_column(String(255), index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    local_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(150), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(150), nullable=True)
    business_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    full_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    locality: Mapped[str | None] = mapped_column(String(150), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    coordinate_precision: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(80), nullable=True)
    whatsapp_business: Mapped[bool] = mapped_column(Boolean, default=False)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    booking_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    instagram: Mapped[str | None] = mapped_column(Text, nullable=True)
    tiktok: Mapped[str | None] = mapped_column(Text, nullable=True)
    facebook: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_active_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    activity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    google_status: Mapped[GoogleStatus] = mapped_column(Enum(GoogleStatus), default=GoogleStatus.GOOGLE_CHECK_PENDING, index=True)
    google_review_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    google_reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence_score: Mapped[int] = mapped_column(Integer, default=0)
    quality_tier: Mapped[QualityTier] = mapped_column(Enum(QualityTier), default=QualityTier.RESEARCH, index=True)
    usability_eligible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    usability_failures: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[CandidateStatus] = mapped_column(Enum(CandidateStatus), default=CandidateStatus.GOOGLE_CHECK_PENDING)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="candidates")


class GoogleCheck(Base):
    __tablename__ = "google_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    poi_candidate_id: Mapped[int] = mapped_column(ForeignKey("poi_candidates.id"), index=True)
    decision: Mapped[GoogleStatus] = mapped_column(Enum(GoogleStatus))
    queries: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    candidate_place_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    reviewer: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(Text)
    evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExportRecord(Base):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    record_count: Mapped[int] = mapped_column(Integer)
    validation_summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Provider(str, enum.Enum):
    GRAB = "GRAB"
    GOOGLE = "GOOGLE"
    HERE = "HERE"


class PresenceBucket(str, enum.Enum):
    """Which providers hold a record for one resolved real-world place.

    These seven values are the complete partition of a three-provider comparison:
    one for all three agreeing, three for each pair, three for each provider alone.
    """

    ALL_THREE = "ALL_THREE"
    HERE_GOOGLE = "HERE_GOOGLE"
    HERE_GRAB = "HERE_GRAB"
    GOOGLE_GRAB = "GOOGLE_GRAB"
    HERE_ONLY = "HERE_ONLY"
    GOOGLE_ONLY = "GOOGLE_ONLY"
    GRAB_ONLY = "GRAB_ONLY"


class RunStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED_BUDGET = "ABORTED_BUDGET"


class MatchDecision(str, enum.Enum):
    MATCHED = "MATCHED"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    NO_MATCH = "NO_MATCH"


class MatchMethod(str, enum.Enum):
    AUTO_SWEEP = "AUTO_SWEEP"
    PROBE = "PROBE"
    MANUAL = "MANUAL"


class UniquenessVerdict(str, enum.Enum):
    MATCHED = "MATCHED"
    UNIQUE_VERIFIED = "UNIQUE_VERIFIED"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    UNRESOLVED = "UNRESOLVED"


class JobStage(str, enum.Enum):
    QUEUED = "QUEUED"
    SWEEPING_GRAB = "SWEEPING_GRAB"
    SWEEPING_GOOGLE = "SWEEPING_GOOGLE"
    SWEEPING_HERE = "SWEEPING_HERE"
    MATCHING = "MATCHING"
    PROBING = "PROBING"
    FINISHED = "FINISHED"


class DiscoveryJob(Base):
    """One end-to-end city run: sweep both providers, match, probe, report.

    This is the single-action entry point. It owns the SearchArea it creates and every
    place discovered under it, so a download can be scoped to exactly one city.
    """

    __tablename__ = "discovery_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    city_code: Mapped[str] = mapped_column(String(80), index=True)
    city_name: Mapped[str] = mapped_column(String(120))
    province: Mapped[str] = mapped_column(String(120), index=True)
    coverage: Mapped[str] = mapped_column(String(20), default="CORE")
    radius_m: Mapped[float] = mapped_column(Float, default=2500.0)
    tile_radius_m: Mapped[float] = mapped_column(Float, default=400.0)

    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.PENDING, index=True)
    stage: Mapped[JobStage] = mapped_column(Enum(JobStage), default=JobStage.QUEUED)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("search_areas.id"), nullable=True)
    run_ids: Mapped[list[int]] = mapped_column(JSON, default=list)

    probes_done: Mapped[int] = mapped_column(Integer, default=0)
    probes_total: Mapped[int] = mapped_column(Integer, default=0)
    max_probe_calls: Mapped[int] = mapped_column(Integer, default=1500)
    probe_call_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    est_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    api_calls: Mapped[int] = mapped_column(Integer, default=0)

    # Records resolved from downloaded data alone, before any probe was paid for.
    coverage_resolved: Mapped[int] = mapped_column(Integer, default=0)
    # Unique counts split by how absence was established, so the interface can show
    # the strong and moderate tiers separately instead of one blended number.
    evidence_split: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    grab_only_count: Mapped[int] = mapped_column(Integer, default=0)
    google_only_count: Mapped[int] = mapped_column(Integer, default=0)
    #: Places only HERE returned, from the three-way resolution below.
    here_only_count: Mapped[int] = mapped_column(Integer, default=0)
    #: Full PresenceBucket breakdown when HERE took part, so the city job reports the
    #: same seven buckets the area comparison does. Empty for a two-provider run.
    bucket_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Records kept per provider, keyed by Provider value.
    provider_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    unresolved_count: Mapped[int] = mapped_column(Integer, default=0)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class SearchArea(Base):
    """A circular area of interest that a sweep covers."""

    __tablename__ = "search_areas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    city: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    center_lat: Mapped[float] = mapped_column(Float)
    center_lng: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float, default=1500.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscoveryRun(Base):
    """One metered sweep of one provider over a set of areas."""

    __tablename__ = "discovery_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    provider: Mapped[Provider] = mapped_column(Enum(Provider), index=True)
    area_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.PENDING, index=True)
    tiles_planned: Mapped[int] = mapped_column(Integer, default=0)
    tiles_done: Mapped[int] = mapped_column(Integer, default=0)
    saturated_tiles: Mapped[int] = mapped_column(Integer, default=0)
    api_calls: Mapped[int] = mapped_column(Integer, default=0)
    places_found: Mapped[int] = mapped_column(Integer, default=0)
    places_kept: Mapped[int] = mapped_column(Integer, default=0)
    # Cost tracking. est_cost_usd is the pre-flight estimate; actual_cost_usd is
    # calls-made x configured rate. Null means the rate is not configured — which is
    # reported as unknown, never as zero.
    est_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    call_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Pricing buckets the provider says it actually charged, keyed by bucket name.
    # Amazon Location returns these in the x-amz-geo-pricing-bucket response header.
    pricing_buckets: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class ProviderPlace(Base):
    """A place as returned by one provider, with immutable raw lineage."""

    __tablename__ = "provider_places"
    __table_args__ = (UniqueConstraint("project_id", "provider", "provider_place_id", name="uq_provider_place"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("discovery_runs.id"), nullable=True)
    # Which city job discovered this place. Set on sweep and on probe alike, so a
    # download can be scoped to one city even when a project holds several.
    job_id: Mapped[int | None] = mapped_column(ForeignKey("discovery_jobs.id"), nullable=True, index=True)
    provider: Mapped[Provider] = mapped_column(Enum(Provider), index=True)
    provider_place_id: Mapped[str] = mapped_column(String(512), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    name: Mapped[str] = mapped_column(String(255), index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    match_name: Mapped[str] = mapped_column(String(255), default="")
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    # True when this place falls inside the run's requested category scope. Replaces
    # the old single-vertical flag: scope is now expressed as unified categories, so a
    # run can target hospitals, or schools, or everything, with the same machinery.
    # A run with no category filter marks every place in scope.
    in_scope: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # The provider's own categories folded onto the shared taxonomy, so places from
    # three incompatible classification systems can be counted side by side.
    # See services/taxonomy.py. Null on rows written before the taxonomy existed.
    unified_category: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    # Which area sweep discovered this place, so a 3 km comparison can be scoped
    # without dragging in every place the project ever collected.
    area_sweep_id: Mapped[int | None] = mapped_column(ForeignKey("area_sweeps.id"), nullable=True, index=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    phone_e164: Mapped[str | None] = mapped_column(String(40), nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    website_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    verdict: Mapped[UniquenessVerdict | None] = mapped_column(Enum(UniquenessVerdict), nullable=True, index=True)
    # True when the sweep never surfaced this place and only a targeted probe found it.
    # Kept separate so the report can show how much recall the probe stage recovered.
    discovered_by_probe: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PoiMatch(Base):
    """A scored Grab <-> Google pairing, with its full signal breakdown as evidence."""

    __tablename__ = "poi_matches"
    __table_args__ = (UniqueConstraint("grab_place_id", "google_place_id", name="uq_poi_match_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    grab_place_id: Mapped[int] = mapped_column(ForeignKey("provider_places.id"), index=True)
    google_place_id: Mapped[int] = mapped_column(ForeignKey("provider_places.id"), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    signals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    decision: Mapped[MatchDecision] = mapped_column(Enum(MatchDecision), index=True)
    method: Mapped[MatchMethod] = mapped_column(Enum(MatchMethod), default=MatchMethod.AUTO_SWEEP)
    reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    grab_place: Mapped[ProviderPlace] = relationship(foreign_keys=[grab_place_id])
    google_place: Mapped[ProviderPlace] = relationship(foreign_keys=[google_place_id])


class UniquenessProbe(Base):
    """Evidence that we actively looked for a place in the opposite provider.

    A place cannot be reported as unique without one of these rows. This is the
    audit gate that stops uniqueness being inferred by set subtraction.
    """

    __tablename__ = "uniqueness_probes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    provider_place_id: Mapped[int] = mapped_column(ForeignKey("provider_places.id"), index=True)
    probed_provider: Mapped[Provider] = mapped_column(Enum(Provider))
    queries: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    best_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # How absence was established:
    #   PROBE          a live targeted lookup in the other provider (strongest)
    #   AREA_COVERAGE  the other provider demonstrably swept this spot and returned
    #                  other places but not this one (free, but cannot rule out a
    #                  category-taxonomy miss, so it is reported as a separate tier)
    evidence_method: Mapped[str] = mapped_column(String(30), default="PROBE", index=True)
    verdict: Mapped[UniquenessVerdict] = mapped_column(Enum(UniquenessVerdict), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    probed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AreaSweep(Base):
    """One user-drawn circle swept across HERE, Google and Grab, then compared.

    This is the entry point for the three-map comparison: the user picks a centre and
    a radius on the map, and this row owns every place discovered under it plus the
    resolved clusters. Scoping by area_sweep_id is what keeps one comparison from
    contaminating another when several are run in the same project.
    """

    __tablename__ = "area_sweeps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    label: Mapped[str] = mapped_column(String(255), default="")
    center_lat: Mapped[float] = mapped_column(Float)
    center_lng: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float, default=3000.0)
    tile_radius_m: Mapped[float] = mapped_column(Float, default=400.0)
    #: Unified categories requested. Empty list means every category.
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: Providers actually swept, as Provider values.
    providers: Mapped[list[str]] = mapped_column(JSON, default=list)

    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.PENDING, index=True)
    stage: Mapped[str] = mapped_column(String(40), default="QUEUED")
    run_ids: Mapped[list[int]] = mapped_column(JSON, default=list)

    #: Raw places kept per provider, keyed by Provider value.
    provider_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Cluster totals keyed by PresenceBucket value.
    bucket_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: {unified_category: {provider: count, ...}} for the category breakdown table.
    category_matrix: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    clusters_total: Mapped[int] = mapped_column(Integer, default=0)

    api_calls: Mapped[int] = mapped_column(Integer, default=0)
    #: Calls and cost per provider, so one expensive leg is attributable.
    cost_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    est_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: Providers whose sweep stopped early on a budget cap, so partial coverage is
    #: never silently presented as complete.
    partial_providers: Mapped[list[str]] = mapped_column(JSON, default=list)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class AreaCluster(Base):
    """One real-world place, resolved across up to three providers.

    A cluster is the unit the customer actually cares about: "this hospital exists,
    and here is which of the three maps knows about it". The provider place columns
    are nullable precisely because absence is the finding.
    """

    __tablename__ = "area_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sweep_id: Mapped[int] = mapped_column(ForeignKey("area_sweeps.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    bucket: Mapped[PresenceBucket] = mapped_column(Enum(PresenceBucket), index=True)
    unified_category: Mapped[str] = mapped_column(String(40), index=True, default="OTHER")

    #: Representative identity, taken from the richest provider record in the cluster.
    display_name: Mapped[str] = mapped_column(String(255), default="")
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)

    here_place_id: Mapped[int | None] = mapped_column(ForeignKey("provider_places.id"), nullable=True)
    google_place_id: Mapped[int | None] = mapped_column(ForeignKey("provider_places.id"), nullable=True)
    grab_place_id: Mapped[int | None] = mapped_column(ForeignKey("provider_places.id"), nullable=True)

    #: Pairwise scores that justified the merge, e.g. {"HERE|GOOGLE": {"score": 91.2}}.
    #: A cluster of one carries an empty dict, which is itself the evidence that
    #: nothing scored high enough to join it.
    match_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    max_pair_distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    here_place: Mapped["ProviderPlace | None"] = relationship(foreign_keys=[here_place_id])
    google_place: Mapped["ProviderPlace | None"] = relationship(foreign_keys=[google_place_id])
    grab_place: Mapped["ProviderPlace | None"] = relationship(foreign_keys=[grab_place_id])


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
