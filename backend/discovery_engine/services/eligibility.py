from datetime import date
from ..models import CandidateStatus, GoogleStatus, PoiCandidate, QualityTier, Project
from .normalization import has_usable_category

CENTROID_PRECISIONS = {"CITY_CENTROID", "NEIGHBOURHOOD_CENTROID", "DISTRICT_CENTROID", "UNKNOWN"}


def evaluate_candidate(candidate: PoiCandidate, project: Project) -> tuple[bool, list[str], QualityTier, CandidateStatus]:
    failures: list[str] = []

    if candidate.google_status != GoogleStatus.GOOGLE_ABSENT_VERIFIED:
        failures.append("Google absence is not verified")
    if not candidate.google_review_completed:
        failures.append("Google exclusion workflow is incomplete")
    if not candidate.business_name or candidate.business_name.lower().startswith("unnamed"):
        failures.append("Specific business name is missing")
    if not candidate.business_verified or not has_usable_category(candidate.category):
        failures.append("Physical business identity and category are unconfirmed")
    if not candidate.full_address:
        failures.append("Operationally usable address is missing")
    if not candidate.city:
        failures.append("City is missing")
    if not candidate.province:
        failures.append("Administrative area is missing")
    if candidate.latitude is None or candidate.longitude is None:
        failures.append("Latitude or longitude is missing")
    if not candidate.coordinate_precision or candidate.coordinate_precision.upper() in CENTROID_PRECISIONS:
        failures.append("Coordinate precision is insufficient")
    if not any([candidate.phone, candidate.whatsapp, candidate.website, candidate.booking_url,
                candidate.instagram, candidate.facebook, candidate.tiktok]):
        failures.append("No actionable contact channel is available")
    if not candidate.primary_source_url:
        failures.append("Primary source URL is missing")
    if not candidate.source_type:
        failures.append("Source type is missing")
    if not candidate.extraction_date:
        failures.append("Extraction date is missing")
    if not candidate.evidence_reference:
        failures.append("Evidence reference is missing")
    if not candidate.reviewer_identity:
        failures.append("Reviewer or system process identity is missing")
    if not (candidate.activity_verified or candidate.last_active_date):
        failures.append("No current activity or validation signal is available")
    if candidate.confidence_score < project.confidence_threshold:
        failures.append(f"Confidence is below project threshold {project.confidence_threshold}")

    eligible = not failures
    if eligible and candidate.confidence_score >= project.gold_threshold:
        return True, [], QualityTier.GOLD, CandidateStatus.ACCEPTED_GOLD
    if eligible:
        return True, [], QualityTier.SILVER, CandidateStatus.ACCEPTED_SILVER

    if candidate.status == CandidateStatus.REJECTED:
        return False, failures, QualityTier.REJECTED, CandidateStatus.REJECTED
    mapped_status = {
        GoogleStatus.GOOGLE_PRESENT_CONFIRMED: CandidateStatus.GOOGLE_PRESENT_CONFIRMED,
        GoogleStatus.GOOGLE_POSSIBLE_MATCH: CandidateStatus.GOOGLE_POSSIBLE_MATCH,
        GoogleStatus.GOOGLE_ABSENT_VERIFIED: CandidateStatus.GOOGLE_ABSENT_VERIFIED,
        GoogleStatus.GOOGLE_CHECK_INCONCLUSIVE: CandidateStatus.GOOGLE_CHECK_INCONCLUSIVE,
        GoogleStatus.GOOGLE_CHECK_PENDING: CandidateStatus.GOOGLE_CHECK_PENDING,
    }[candidate.google_status]
    return False, failures, QualityTier.RESEARCH, mapped_status


def recalculate_candidate(candidate: PoiCandidate, project: Project) -> None:
    eligible, failures, tier, status = evaluate_candidate(candidate, project)
    candidate.usability_eligible = eligible
    candidate.usability_failures = failures
    candidate.quality_tier = tier
    candidate.status = status
