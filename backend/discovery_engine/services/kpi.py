from collections import Counter
from typing import Iterable
from ..models import GoogleStatus, PoiCandidate, QualityTier


def pct(numerator: int, denominator: int) -> float:
    return round((numerator / denominator * 100), 2) if denominator else 0.0


def calculate_kpis(candidates: Iterable[PoiCandidate]) -> dict:
    rows = list(candidates)
    b_rows = [r for r in rows if r.google_status == GoogleStatus.GOOGLE_PRESENT_CONFIRMED]
    c_rows = [r for r in rows if r.google_status == GoogleStatus.GOOGLE_ABSENT_VERIFIED]
    i_rows = [r for r in rows if r.google_status in {
        GoogleStatus.GOOGLE_CHECK_PENDING,
        GoogleStatus.GOOGLE_POSSIBLE_MATCH,
        GoogleStatus.GOOGLE_CHECK_INCONCLUSIVE,
    }]
    # A is intentionally constructed from the explicit disjoint status groups.
    a = len(b_rows) + len(c_rows) + len(i_rows)
    d_rows = [r for r in c_rows if r.usability_eligible]

    def grouped(field: str):
        counter = Counter((getattr(r, field) or "Unknown") for r in rows)
        return [{"name": str(k), "count": v} for k, v in sorted(counter.items(), key=lambda x: (-x[1], str(x[0])))]

    result = {
        "A_total": a,
        "B_google_present": len(b_rows),
        "C_google_absent_verified": len(c_rows),
        "D_usable_non_google": len(d_rows),
        "E_instagram_on_D": sum(bool(r.instagram) for r in d_rows),
        "F_tiktok_on_D": sum(bool(r.tiktok) for r in d_rows),
        "G_facebook_on_D": sum(bool(r.facebook) for r in d_rows),
        "H_whatsapp_on_D": sum(bool(r.whatsapp or r.whatsapp_business) for r in d_rows),
        "I_inconclusive_or_pending": len(i_rows),
        "incremental_usable_ratio": pct(len(d_rows), a),
        "google_coverage_ratio": pct(len(b_rows), a),
        "verified_gap_ratio": pct(len(c_rows), a),
        "usability_rate_of_gaps": pct(len(d_rows), len(c_rows)),
        "gold_quality_ratio": pct(sum(r.quality_tier == QualityTier.GOLD for r in d_rows), len(d_rows)),
        "coordinate_precision_coverage": pct(sum(r.latitude is not None and r.longitude is not None and (r.coordinate_precision or "").upper() not in {"", "UNKNOWN", "CITY_CENTROID", "NEIGHBOURHOOD_CENTROID"} for r in rows), a),
        "contactability_coverage": pct(sum(any([r.phone, r.whatsapp, r.website, r.booking_url, r.instagram, r.facebook, r.tiktok]) for r in rows), a),
        "invariant_a_equals_b_plus_c_plus_i": a == len(b_rows) + len(c_rows) + len(i_rows),
        "invariant_d_subset_c": all(r.google_status == GoogleStatus.GOOGLE_ABSENT_VERIFIED for r in d_rows),
        "by_city": grouped("city"),
        "by_source": grouped("source_name"),
        "by_google_status": grouped("google_status"),
        "by_quality_tier": grouped("quality_tier"),
    }
    return result
