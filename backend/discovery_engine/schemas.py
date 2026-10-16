from datetime import date, datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from .models import (
    GoogleStatus, JobStage, MatchDecision, MatchMethod, Provider, QualityTier, RunStatus,
    UniquenessVerdict, UserRole,
)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=3, max_length=255)
    customer: str
    country: str = "Indonesia"
    cities: list[str] = []
    categories: list[str] = ["Hair Salon"]
    target_volume: int = Field(default=100, ge=1)
    confidence_threshold: int = Field(default=70, ge=0, le=100)
    gold_threshold: int = Field(default=85, ge=0, le=100)
    match_auto_threshold: int = Field(default=85, ge=0, le=100)
    match_possible_threshold: int = Field(default=60, ge=0, le=100)


class ProjectOut(ProjectCreate):
    id: int
    status: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CandidateOut(BaseModel):
    id: int
    poi_id: str
    project_id: int
    source_name: str
    source_type: str
    source_record_id: str | None
    business_name: str
    normalized_name: str
    category: str
    business_verified: bool
    full_address: str | None
    locality: str | None
    city: str | None
    province: str | None
    latitude: float | None
    longitude: float | None
    coordinate_precision: str | None
    phone: str | None
    whatsapp: str | None
    whatsapp_business: bool
    website: str | None
    booking_url: str | None
    instagram: str | None
    tiktok: str | None
    facebook: str | None
    primary_source_url: str | None
    evidence_reference: str | None
    extraction_date: date | None
    last_active_date: date | None
    activity_verified: bool
    google_status: GoogleStatus
    google_review_completed: bool
    google_reviewer: str | None
    confidence_score: int
    quality_tier: QualityTier
    usability_eligible: bool
    usability_failures: list[str]
    status: str
    is_demo: bool
    reviewer_identity: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CandidateUpdate(BaseModel):
    business_name: str | None = None
    category: str | None = None
    business_verified: bool | None = None
    full_address: str | None = None
    locality: str | None = None
    city: str | None = None
    province: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    coordinate_precision: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    whatsapp_business: bool | None = None
    website: str | None = None
    booking_url: str | None = None
    instagram: str | None = None
    tiktok: str | None = None
    facebook: str | None = None
    primary_source_url: str | None = None
    evidence_reference: str | None = None
    extraction_date: date | None = None
    last_active_date: date | None = None
    activity_verified: bool | None = None
    confidence_score: int | None = Field(default=None, ge=0, le=100)
    reviewer_identity: str | None = None


class GoogleReviewRequest(BaseModel):
    decision: GoogleStatus
    completed: bool
    reason: str = Field(min_length=5)
    evidence_reference: str | None = None
    queries: list[dict[str, Any]] = []
    candidate_place_ids: list[str] = []


class ImportResult(BaseModel):
    imported: int
    rejected_rows: int
    candidate_ids: list[int]


class DashboardKpi(BaseModel):
    A_total: int
    B_google_present: int
    C_google_absent_verified: int
    D_usable_non_google: int
    E_instagram_on_D: int
    F_tiktok_on_D: int
    G_facebook_on_D: int
    H_whatsapp_on_D: int
    I_inconclusive_or_pending: int
    incremental_usable_ratio: float
    google_coverage_ratio: float
    verified_gap_ratio: float
    usability_rate_of_gaps: float
    gold_quality_ratio: float
    coordinate_precision_coverage: float
    contactability_coverage: float
    invariant_a_equals_b_plus_c_plus_i: bool
    invariant_d_subset_c: bool
    by_city: list[dict[str, Any]]
    by_source: list[dict[str, Any]]
    by_google_status: list[dict[str, Any]]
    by_quality_tier: list[dict[str, Any]]


class SearchAreaCreate(BaseModel):
    project_id: int
    city: str
    name: str
    center_lat: float = Field(ge=-90, le=90)
    center_lng: float = Field(ge=-180, le=180)
    radius_m: float = Field(default=1500.0, gt=0, le=50_000)


class SearchAreaOut(BaseModel):
    id: int
    project_id: int
    city: str
    name: str
    center_lat: float
    center_lng: float
    radius_m: float
    is_active: bool
    model_config = ConfigDict(from_attributes=True)


class SweepRequest(BaseModel):
    project_id: int
    provider: Provider
    area_ids: list[int] = []
    tile_radius_m: float = Field(default=400.0, ge=50, le=5000)
    max_calls: int | None = Field(default=None, ge=1)


class DiscoveryRunOut(BaseModel):
    id: int
    project_id: int
    provider: Provider
    status: RunStatus
    area_ids: list[int]
    params: dict[str, Any]
    tiles_planned: int
    tiles_done: int
    saturated_tiles: int
    api_calls: int
    places_found: int
    places_kept: int
    est_cost_usd: float | None
    actual_cost_usd: float | None
    call_counts: dict[str, Any]
    pricing_buckets: dict[str, Any]
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class CityJobRequest(BaseModel):
    project_id: int
    city_code: str
    coverage: Literal["CORE", "FULL"] = "CORE"
    tile_radius_m: float = Field(default=400.0, ge=100, le=2000)
    max_probe_calls: int | None = Field(default=None, ge=1, le=20_000)
    # A run spends real money, so it cannot start without an explicit acknowledgement.
    confirm: bool = False


class CityJobOut(BaseModel):
    id: int
    project_id: int
    city_code: str
    city_name: str
    province: str
    coverage: str
    radius_m: float
    tile_radius_m: float
    status: RunStatus
    stage: JobStage
    run_ids: list[int]
    probes_done: int
    probes_total: int
    est_cost_usd: float | None
    actual_cost_usd: float | None
    api_calls: int
    coverage_resolved: int
    evidence_split: dict[str, Any]
    grab_only_count: int
    google_only_count: int
    here_only_count: int = 0
    matched_count: int
    unresolved_count: int
    #: Seven-bucket presence breakdown; empty when only one provider ran.
    bucket_counts: dict[str, Any] = {}
    provider_counts: dict[str, Any] = {}
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class ProbeRequest(BaseModel):
    project_id: int
    provider: Provider | None = None
    limit: int = Field(default=100, ge=1, le=2000)


class MatchReviewRequest(BaseModel):
    decision: MatchDecision
    reason: str = Field(min_length=5)


class ProviderPlaceOut(BaseModel):
    id: int
    provider: Provider
    provider_place_id: str
    name: str
    categories: list[str]
    address: str | None
    city: str | None
    province: str | None
    lat: float | None
    lng: float | None
    phone_e164: str | None
    website: str | None
    business_status: str | None
    verdict: UniquenessVerdict | None
    discovered_by_probe: bool
    model_config = ConfigDict(from_attributes=True)


class ProviderPlacePage(BaseModel):
    items: list[ProviderPlaceOut]
    total: int
    page: int
    page_size: int
    pages: int


class PlaceEvidenceOut(BaseModel):
    verdict: UniquenessVerdict
    evidence_method: str
    reason: str
    result_count: int
    best_score: float | None
    probed_at: datetime
    probed_provider: Provider
    queries: list[dict[str, Any]]
    model_config = ConfigDict(from_attributes=True)


class PlaceCounterpartOut(BaseModel):
    """The opposite-provider record this place was paired with, if any."""
    provider: Provider
    name: str
    address: str | None
    score: float
    distance_m: float | None
    decision: MatchDecision
    method: MatchMethod
    signals: dict[str, Any]


class ProviderPlaceDetail(ProviderPlaceOut):
    normalized_name: str
    postal_code: str | None
    raw_payload: dict[str, Any]
    first_seen_at: datetime
    last_seen_at: datetime
    evidence: PlaceEvidenceOut | None = None
    counterparts: list[PlaceCounterpartOut] = []


class PoiMatchOut(BaseModel):
    id: int
    score: float
    distance_m: float | None
    decision: MatchDecision
    method: MatchMethod
    signals: dict[str, Any]
    reviewer: str | None
    grab_place: ProviderPlaceOut
    google_place: ProviderPlaceOut
    model_config = ConfigDict(from_attributes=True)


class AuditOut(BaseModel):
    id: int
    actor_email: str | None
    action: str
    entity_type: str
    entity_id: str | None
    details: dict[str, Any]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
