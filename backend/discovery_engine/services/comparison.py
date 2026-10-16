"""Coverage-comparison KPIs with enforced invariants.

Mirrors the discipline of the existing A = B + C + I dashboard: every provider's set
is partitioned into explicit, disjoint, evidence-backed groups. Nothing is derived by
subtraction, and "we do not know" (UNRESOLVED) is reported as its own number rather
than being folded into one of the confident buckets.
"""
from __future__ import annotations

import statistics
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    MatchDecision,
    PoiMatch,
    Provider,
    ProviderPlace,
    UniquenessProbe,
    UniquenessVerdict,
)
from .geo import haversine_m


def pct(numerator: int, denominator: int) -> float:
    return round((numerator / denominator * 100), 2) if denominator else 0.0


def _bucket_counts(places: list[ProviderPlace]) -> dict[str, int]:
    counter = Counter(p.verdict.value if p.verdict else UniquenessVerdict.UNRESOLVED.value for p in places)
    return {
        "matched": counter.get(UniquenessVerdict.MATCHED.value, 0),
        "unique_verified": counter.get(UniquenessVerdict.UNIQUE_VERIFIED.value, 0),
        "possible": counter.get(UniquenessVerdict.POSSIBLE_MATCH.value, 0),
        "unresolved": counter.get(UniquenessVerdict.UNRESOLVED.value, 0),
    }


def _grouped(places: list[ProviderPlace], field: str) -> list[dict]:
    counter = Counter((getattr(p, field) or "Unknown") for p in places)
    return [{"name": str(k), "count": v} for k, v in sorted(counter.items(), key=lambda x: (-x[1], str(x[0])))]


def calculate_comparison_kpis(db: Session, project_id: int, job_id: int | None = None) -> dict:
    """KPIs for a project, or for one city job when job_id is given."""
    query = select(ProviderPlace).where(ProviderPlace.project_id == project_id, ProviderPlace.in_scope.is_(True))
    if job_id is not None:
        query = query.where(ProviderPlace.job_id == job_id)
    places = list(db.scalars(query).all())
    grab = [p for p in places if p.provider == Provider.GRAB]
    google = [p for p in places if p.provider == Provider.GOOGLE]

    place_ids = {p.id for p in places}
    matches = [
        m for m in db.scalars(
            select(PoiMatch).where(PoiMatch.project_id == project_id, PoiMatch.decision == MatchDecision.MATCHED)
        ).all()
        # A pair only counts for this job when both of its records belong to it.
        if job_id is None or (m.grab_place_id in place_ids and m.google_place_id in place_ids)
    ]
    place_by_id = {p.id: p for p in places}

    grab_buckets = _bucket_counts(grab)
    google_buckets = _bucket_counts(google)

    G, K, M = len(grab), len(google), len(matches)
    GU = grab_buckets["unique_verified"]
    KU = google_buckets["unique_verified"]

    # Coordinate agreement on matched pairs: a data-quality proxy that needs no
    # ground truth, since both providers claim to describe the same premises.
    deltas = []
    for match in matches:
        left, right = place_by_id.get(match.grab_place_id), place_by_id.get(match.google_place_id)
        if left and right and None not in (left.lat, left.lng, right.lat, right.lng):
            deltas.append(haversine_m(left.lat, left.lng, right.lat, right.lng))

    probes_recovered = sum(1 for p in places if p.discovered_by_probe)
    unique_without_evidence = _unique_without_probe_evidence(db, project_id, job_id)
    evidence = _evidence_split(db, project_id, place_by_id)

    return {
        "G_grab_total": G,
        "K_google_total": K,
        "M_matched": M,
        "GU_grab_only_verified": GU,
        "KU_google_only_verified": KU,

        # Evidence strength behind those two headline numbers. A probe is a live
        # lookup with no category filter; area coverage is derived from the sweep and
        # cannot rule out the other provider holding the business under a different
        # category. They are never summed into one figure.
        "GU_grab_only_probe_verified": evidence["GRAB"]["PROBE"],
        "GU_grab_only_area_verified": evidence["GRAB"]["AREA_COVERAGE"],
        "KU_google_only_probe_verified": evidence["GOOGLE"]["PROBE"],
        "KU_google_only_area_verified": evidence["GOOGLE"]["AREA_COVERAGE"],
        "P_grab_possible": grab_buckets["possible"],
        "P_google_possible": google_buckets["possible"],
        "U_grab_unresolved": grab_buckets["unresolved"],
        "U_google_unresolved": google_buckets["unresolved"],

        "google_coverage_gap_pct": pct(GU, G),
        "grab_coverage_gap_pct": pct(KU, K),
        "overlap_jaccard_pct": pct(M, G + K - M),
        "grab_resolved_pct": pct(grab_buckets["matched"] + GU, G),
        "google_resolved_pct": pct(google_buckets["matched"] + KU, K),

        "median_coordinate_delta_m": round(statistics.median(deltas), 1) if deltas else None,
        "p90_coordinate_delta_m": round(sorted(deltas)[int(len(deltas) * 0.9)], 1) if len(deltas) >= 10 else None,
        "grab_contactability_pct": pct(sum(1 for p in grab if p.phone_e164 or p.website), G),
        "google_contactability_pct": pct(sum(1 for p in google if p.phone_e164 or p.website), K),
        "places_recovered_by_probe": probes_recovered,

        # Invariants. A false value means the report must not be issued.
        "invariant_grab_partition": G == grab_buckets["matched"] + GU + grab_buckets["possible"] + grab_buckets["unresolved"],
        "invariant_google_partition": K == google_buckets["matched"] + KU + google_buckets["possible"] + google_buckets["unresolved"],
        "invariant_unique_has_probe_evidence": unique_without_evidence == 0,
        "unique_records_missing_probe_evidence": unique_without_evidence,

        "grab_by_city": _grouped(grab, "city"),
        "google_by_city": _grouped(google, "city"),
        "grab_by_verdict": [{"name": k, "count": v} for k, v in grab_buckets.items()],
        "google_by_verdict": [{"name": k, "count": v} for k, v in google_buckets.items()],
    }


def _evidence_split(db: Session, project_id: int, place_by_id: dict) -> dict:
    """Count verified-unique records by how their absence was established."""
    split = {
        "GRAB": {"PROBE": 0, "AREA_COVERAGE": 0},
        "GOOGLE": {"PROBE": 0, "AREA_COVERAGE": 0},
    }
    rows = db.scalars(
        select(UniquenessProbe).where(
            UniquenessProbe.project_id == project_id,
            UniquenessProbe.verdict == UniquenessVerdict.UNIQUE_VERIFIED,
        )
    ).all()
    for row in rows:
        place = place_by_id.get(row.provider_place_id)
        if place is None or place.verdict != UniquenessVerdict.UNIQUE_VERIFIED:
            continue
        bucket = split.get(place.provider.value)
        if bucket is not None and row.evidence_method in bucket:
            bucket[row.evidence_method] += 1
    return split


def _unique_without_probe_evidence(db: Session, project_id: int, job_id: int | None = None) -> int:
    """The audit gate: no record may be reported unique without a stored probe."""
    query = select(ProviderPlace.id).where(
        ProviderPlace.project_id == project_id,
        ProviderPlace.verdict == UniquenessVerdict.UNIQUE_VERIFIED,
    )
    if job_id is not None:
        query = query.where(ProviderPlace.job_id == job_id)
    unique_ids = {row[0] for row in db.execute(query).all()}
    if not unique_ids:
        return 0
    probed = {
        row[0]
        for row in db.execute(
            select(UniquenessProbe.provider_place_id).where(
                UniquenessProbe.project_id == project_id,
                UniquenessProbe.verdict == UniquenessVerdict.UNIQUE_VERIFIED,
            )
        ).all()
    }
    return len(unique_ids - probed)


def bucket_records(db: Session, project_id: int, bucket: str) -> list[ProviderPlace]:
    """Fetch the records behind one headline number."""
    query = select(ProviderPlace).where(ProviderPlace.project_id == project_id, ProviderPlace.in_scope.is_(True))
    mapping = {
        "grab_only": (Provider.GRAB, UniquenessVerdict.UNIQUE_VERIFIED),
        "google_only": (Provider.GOOGLE, UniquenessVerdict.UNIQUE_VERIFIED),
        "grab_possible": (Provider.GRAB, UniquenessVerdict.POSSIBLE_MATCH),
        "google_possible": (Provider.GOOGLE, UniquenessVerdict.POSSIBLE_MATCH),
        "grab_unresolved": (Provider.GRAB, UniquenessVerdict.UNRESOLVED),
        "google_unresolved": (Provider.GOOGLE, UniquenessVerdict.UNRESOLVED),
    }
    if bucket in mapping:
        provider, verdict = mapping[bucket]
        query = query.where(ProviderPlace.provider == provider, ProviderPlace.verdict == verdict)
    elif bucket == "matched":
        query = query.where(ProviderPlace.verdict == UniquenessVerdict.MATCHED)
    return list(db.scalars(query.order_by(ProviderPlace.city, ProviderPlace.name)).all())
