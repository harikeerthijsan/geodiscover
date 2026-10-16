from datetime import date
from discovery_engine.models import GoogleStatus, PoiCandidate, Project
from discovery_engine.services.eligibility import evaluate_candidate
from discovery_engine.services.kpi import calculate_kpis
from discovery_engine.services.normalization import normalize_text


def make_candidate(status=GoogleStatus.GOOGLE_ABSENT_VERIFIED, eligible_data=True, score=90):
    kwargs = dict(
        project_id=1, poi_id="POI-X", source_name="Directory", source_type="FILE_UPLOAD",
        business_name="Salon Test", normalized_name=normalize_text("Salon Test"), category="Hair Salon",
        business_verified=True, full_address="Jl. Test 1", city="Jakarta", province="DKI Jakarta",
        latitude=-6.2, longitude=106.8, coordinate_precision="ROOFTOP", phone="+62123",
        primary_source_url="https://example.com", evidence_reference="EV-1", extraction_date=date.today(),
        last_active_date=date.today(), activity_verified=True, google_status=status,
        google_review_completed=status != GoogleStatus.GOOGLE_CHECK_PENDING, confidence_score=score,
        reviewer_identity="validator", is_demo=False,
    )
    if not eligible_data:
        kwargs["full_address"] = None
    return PoiCandidate(**kwargs)


def test_eligible_absent_record_becomes_gold():
    project = Project(id=1, name="P", customer="C", country="Indonesia", confidence_threshold=70, gold_threshold=85)
    ok, failures, tier, status = evaluate_candidate(make_candidate(), project)
    assert ok is True
    assert failures == []
    assert tier.value == "GOLD"
    assert status.value == "ACCEPTED_GOLD"


def test_missing_address_blocks_d():
    project = Project(id=1, name="P", customer="C", country="Indonesia", confidence_threshold=70, gold_threshold=85)
    ok, failures, _, _ = evaluate_candidate(make_candidate(eligible_data=False), project)
    assert ok is False
    assert "Operationally usable address is missing" in failures


def test_possible_match_never_counts_under_c_or_d():
    row = make_candidate(status=GoogleStatus.GOOGLE_POSSIBLE_MATCH)
    row.usability_eligible = True  # simulate corrupt external state; KPI must still protect D by C subset
    result = calculate_kpis([row])
    assert result["C_google_absent_verified"] == 0
    assert result["D_usable_non_google"] == 0
    assert result["I_inconclusive_or_pending"] == 1


def test_a_equals_b_plus_c_plus_i():
    rows = [
        make_candidate(GoogleStatus.GOOGLE_PRESENT_CONFIRMED),
        make_candidate(GoogleStatus.GOOGLE_ABSENT_VERIFIED),
        make_candidate(GoogleStatus.GOOGLE_CHECK_INCONCLUSIVE),
        make_candidate(GoogleStatus.GOOGLE_CHECK_PENDING),
    ]
    rows[1].usability_eligible = True
    result = calculate_kpis(rows)
    assert result["A_total"] == 4
    assert result["A_total"] == result["B_google_present"] + result["C_google_absent_verified"] + result["I_inconclusive_or_pending"]
    assert result["invariant_a_equals_b_plus_c_plus_i"] is True
