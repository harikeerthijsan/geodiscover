"""Coverage-comparison tests: geometry, matching rules, probe evidence, invariants.

Providers are faked so the whole pipeline is exercised without spending API calls.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from discovery_engine.database import SessionLocal
from discovery_engine.models import (
    MatchDecision,
    Project,
    Provider,
    ProviderPlace,
    RunStatus,
    SearchArea,
    UniquenessVerdict,
    DiscoveryRun,
)
from discovery_engine.providers.base import ProviderError, ProviderPlaceDTO, SweepResult
from discovery_engine.services.comparison import calculate_comparison_kpis
from discovery_engine.services.geo import Tile, cover_circle_with_tiles, haversine_m
from discovery_engine.services.matching import decide, score_pair
from discovery_engine.services.normalization import match_name, normalize_phone_id, website_domain
from discovery_engine.services.probe import probe_place, run_bulk_match, unprobed_places
from discovery_engine.services.sweep import run_sweep

JAKARTA = (-6.2088, 106.8456)


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------

def dto(provider, pid, name, lat, lng, address="Jl. Kemang Raya 10, Jakarta", categories=("hair_salon",), phone=None, website=None):
    return ProviderPlaceDTO(
        provider=provider, provider_place_id=pid, name=name, lat=lat, lng=lng,
        address=address, categories=list(categories), phone=phone, website=website,
        raw={"id": pid, "name": name},
    )


class FakeAdapter:
    """Returns places whose coordinates fall inside the requested tile."""

    def __init__(self, provider, places, page_size=20, fail=False):
        self.provider = provider
        self._places = places
        self._page_size = page_size
        self._fail = fail
        self.sweep_calls = 0
        self.probe_calls = 0

    def sweep(self, tile: Tile) -> SweepResult:
        self.sweep_calls += 1
        inside = [
            p for p in self._places
            if haversine_m(tile.lat, tile.lng, p.lat, p.lng) <= tile.radius_m
        ]
        page = inside[: self._page_size]
        return SweepResult(places=page, api_calls=1, saturated=len(inside) >= self._page_size)

    def probe(self, name, lat, lng, address) -> SweepResult:
        self.probe_calls += 1
        if self._fail:
            raise ProviderError("simulated provider outage")
        hits = [
            p for p in self._places
            if haversine_m(lat, lng, p.lat, p.lng) <= 500
        ]
        return SweepResult(places=hits, api_calls=1)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def project(db):
    row = Project(name="Coverage Comparison Test", customer="Test", country="Indonesia",
                  cities=["Jakarta"], categories=["Hair Salon"])
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def area(db, project):
    row = SearchArea(project_id=project.id, city="Jakarta", name="Kemang",
                     center_lat=JAKARTA[0], center_lng=JAKARTA[1], radius_m=300.0)
    db.add(row)
    db.flush()
    return row


def make_run(db, project, provider):
    run = DiscoveryRun(project_id=project.id, provider=provider, area_ids=[], params={})
    db.add(run)
    db.flush()
    return run


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

def test_haversine_matches_known_distance():
    # One degree of latitude is ~111.2 km.
    assert 110_000 < haversine_m(0.0, 0.0, 1.0, 0.0) < 112_000
    assert haversine_m(*JAKARTA, *JAKARTA) == 0.0


def test_tiles_cover_the_area_of_interest():
    tiles = cover_circle_with_tiles(*JAKARTA, radius_m=1000, tile_radius_m=400)
    assert tiles
    # Every point on a coarse lattice inside the AOI must fall in some tile.
    for dlat in (-0.005, 0.0, 0.005):
        for dlng in (-0.005, 0.0, 0.005):
            lat, lng = JAKARTA[0] + dlat, JAKARTA[1] + dlng
            if haversine_m(*JAKARTA, lat, lng) > 1000:
                continue
            assert any(haversine_m(t.lat, t.lng, lat, lng) <= t.radius_m for t in tiles), (lat, lng)


def test_subdivision_shrinks_radius_and_tracks_level():
    tile = Tile(*JAKARTA, radius_m=400, level=0)
    children = tile.subdivide()
    assert len(children) == 4
    assert all(c.level == 1 for c in children)
    assert all(c.radius_m < tile.radius_m for c in children)


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

def test_match_name_strips_generic_trade_words():
    assert match_name("Salon Kecantikan") == ""
    assert match_name("Salon Gita Pattern") == "gita pattern"
    assert match_name("GITA Hair & Beauty Studio") == "gita"


def test_phone_normalisation_to_indonesian_e164():
    assert normalize_phone_id("0812-3456-7890") == "+62812345678 90".replace(" ", "")
    assert normalize_phone_id("+62 812 3456 7890") == "+6281234567890"
    assert normalize_phone_id("") is None
    assert normalize_phone_id("12") is None


def test_website_domain_extraction():
    assert website_domain("https://www.SalonGita.co.id/booking?x=1") == "salongita.co.id"
    assert website_domain(None) is None


# --------------------------------------------------------------------------
# Matching rules
# --------------------------------------------------------------------------

class P:
    """Minimal stand-in for a provider place row."""

    def __init__(self, name, lat, lng, address=None, phone=None, domain=None):
        self.name = name
        self.match_name = match_name(name)
        self.lat = lat
        self.lng = lng
        self.address = address
        self.phone_e164 = phone
        self.website_domain = domain


def test_same_business_slightly_offset_is_matched():
    left = P("Salon Gita Pattern", -6.2088, 106.8456, "Jl. Kemang Raya 10")
    right = P("Gita Pattern Hair Salon", -6.20885, 106.84565, "Jl. Kemang Raya 10, Jakarta")
    signals = score_pair(left, right)
    assert signals.distance_m < 25
    assert decide(signals, 85, 60) == "MATCHED"


def test_generic_only_names_cannot_auto_match():
    """Two adjacent salons whose names carry no distinguishing tokens.

    These must land in the review queue, not in NO_MATCH: a NO_MATCH here would send
    both records to the probe stage, where each would be reported as unique to its own
    provider, inventing a coverage gap on both sides.
    """
    left = P("Salon Kecantikan", -6.2088, 106.8456, "Jl. Kemang Raya 10")
    right = P("Salon Kecantikan", -6.20882, 106.84562, "Jl. Kemang Raya 10")
    signals = score_pair(left, right)

    assert signals.forced == "CAP_POSSIBLE"
    assert signals.signals["generic_only_name"] is True
    # Name is renormalised out rather than scored zero, so missing evidence does not
    # masquerade as contradicting evidence.
    assert "name" not in signals.signals["contributions"]
    assert decide(signals, 85, 60) == "POSSIBLE_MATCH"


def test_generic_names_far_apart_still_no_match():
    """Dropping the name signal must not make distant generic pairs match."""
    left = P("Salon Kecantikan", -6.2088, 106.8456, "Jl. Kemang Raya 10")
    right = P("Salon Kecantikan", -6.2098, 106.8466, "Jl. Melati 3")
    signals = score_pair(left, right)
    assert decide(signals, 85, 60) == "NO_MATCH"


def test_distance_rule_overrides_a_perfect_name():
    left = P("Salon Gita Pattern", -6.2088, 106.8456)
    right = P("Salon Gita Pattern", -6.2188, 106.8456)  # ~1.1 km away
    signals = score_pair(left, right)
    assert signals.forced == "NO_MATCH"
    assert decide(signals, 85, 60) == "NO_MATCH"


def test_exact_phone_forces_a_match_despite_name_drift():
    left = P("Gita Pattern", -6.2088, 106.8456, phone="+6281234567890")
    right = P("Rumah Cantik Bu Gita", -6.2091, 106.8459, phone="+6281234567890")
    signals = score_pair(left, right)
    assert signals.forced == "MATCHED"
    assert decide(signals, 85, 60) == "MATCHED"


def test_conflicting_phones_cap_at_possible():
    left = P("Salon Gita Pattern", -6.2088, 106.8456, phone="+6281111111111")
    right = P("Salon Gita Pattern", -6.20881, 106.84561, phone="+6282222222222")
    signals = score_pair(left, right)
    assert signals.signals["phone_conflict"] is True
    assert decide(signals, 85, 60) == "POSSIBLE_MATCH"


def test_missing_contact_data_does_not_penalise_the_pair():
    """Grab returns no phone or website, so pairs must score on geo+name+address."""
    left = P("Salon Gita Pattern", -6.2088, 106.8456, "Jl. Kemang Raya 10")
    right = P("Salon Gita Pattern", -6.2088, 106.8456, "Jl. Kemang Raya 10")
    signals = score_pair(left, right)
    assert "phone" not in signals.signals["contributions"]
    assert signals.score == pytest.approx(100.0)


# --------------------------------------------------------------------------
# Sweep
# --------------------------------------------------------------------------

def test_sweep_persists_places_and_counts_calls(db, project, area):
    places = [dto(Provider.GOOGLE, f"g{i}", f"Salon Gita {i}", JAKARTA[0] + i * 0.0002, JAKARTA[1]) for i in range(5)]
    adapter = FakeAdapter(Provider.GOOGLE, places)
    run = make_run(db, project, Provider.GOOGLE)

    run_sweep(db, run, adapter, [area], tile_radius_m=400)

    assert run.status == RunStatus.COMPLETED
    assert run.api_calls == adapter.sweep_calls > 0
    stored = db.query(ProviderPlace).filter_by(project_id=project.id, provider=Provider.GOOGLE).all()
    assert len(stored) == 5
    assert all(p.in_scope for p in stored)


def test_saturated_tile_is_subdivided(db, project, area):
    """A full page of results means the provider may be hiding places."""
    places = [dto(Provider.GOOGLE, f"g{i}", f"Salon Gita {i}", JAKARTA[0] + i * 0.00002, JAKARTA[1]) for i in range(30)]
    adapter = FakeAdapter(Provider.GOOGLE, places, page_size=20)
    run = make_run(db, project, Provider.GOOGLE)

    run_sweep(db, run, adapter, [area], tile_radius_m=400)

    assert run.saturated_tiles > 0
    assert run.tiles_planned > len(cover_circle_with_tiles(area.center_lat, area.center_lng, area.radius_m, 400))


def test_sweep_aborts_at_the_call_cap(db, project, area):
    places = [dto(Provider.GOOGLE, "g1", "Salon Gita", *JAKARTA)]
    adapter = FakeAdapter(Provider.GOOGLE, places)
    run = make_run(db, project, Provider.GOOGLE)

    run_sweep(db, run, adapter, [area], tile_radius_m=100, max_calls=3)

    assert run.status == RunStatus.ABORTED_BUDGET
    assert run.api_calls <= 3
    assert "cap" in (run.error or "")


# --------------------------------------------------------------------------
# Matching + probe + invariants
# --------------------------------------------------------------------------

def seed_two_providers(db, project, area):
    """Grab and Google each see one shared salon plus one the other does not have."""
    shared_grab = dto(Provider.GRAB, "grab-shared", "Salon Gita Pattern", JAKARTA[0], JAKARTA[1])
    grab_only = dto(Provider.GRAB, "grab-only", "Nusa Hair Studio Melati", JAKARTA[0] + 0.0015, JAKARTA[1])
    shared_google = dto(Provider.GOOGLE, "goog-shared", "Gita Pattern Salon", JAKARTA[0] + 0.00005, JAKARTA[1])
    google_only = dto(Provider.GOOGLE, "goog-only", "Mawar Beauty Cempaka", JAKARTA[0] - 0.0015, JAKARTA[1])

    grab_adapter = FakeAdapter(Provider.GRAB, [shared_grab, grab_only])
    google_adapter = FakeAdapter(Provider.GOOGLE, [shared_google, google_only])

    for provider, adapter in ((Provider.GRAB, grab_adapter), (Provider.GOOGLE, google_adapter)):
        run = make_run(db, project, provider)
        run_sweep(db, run, adapter, [area], tile_radius_m=400)
    return grab_adapter, google_adapter


def test_bulk_match_pairs_the_shared_salon(db, project, area):
    seed_two_providers(db, project, area)
    result = run_bulk_match(db, project)

    assert result["grab_places"] == 2
    assert result["google_places"] == 2
    assert result["matched"] == 1


def test_probe_verifies_uniqueness_and_records_evidence(db, project, area):
    grab_adapter, google_adapter = seed_two_providers(db, project, area)
    run_bulk_match(db, project)

    # Probe Grab's unmatched record against Google, and vice versa.
    for provider, opposite_adapter in ((Provider.GRAB, google_adapter), (Provider.GOOGLE, grab_adapter)):
        opposite = Provider.GOOGLE if provider == Provider.GRAB else Provider.GRAB
        for place in unprobed_places(db, project.id, provider):
            probe_place(db, project, place, opposite_adapter, opposite)

    kpis = calculate_comparison_kpis(db, project.id)

    assert kpis["M_matched"] == 1
    assert kpis["GU_grab_only_verified"] == 1
    assert kpis["KU_google_only_verified"] == 1
    assert kpis["invariant_grab_partition"] is True
    assert kpis["invariant_google_partition"] is True
    assert kpis["invariant_unique_has_probe_evidence"] is True
    assert kpis["unique_records_missing_probe_evidence"] == 0


def test_unmatched_and_unprobed_is_unresolved_never_unique(db, project, area):
    """The core guarantee: absence of a match is not evidence of absence."""
    seed_two_providers(db, project, area)
    run_bulk_match(db, project)

    kpis = calculate_comparison_kpis(db, project.id)

    assert kpis["GU_grab_only_verified"] == 0
    assert kpis["KU_google_only_verified"] == 0
    assert kpis["U_grab_unresolved"] == 1
    assert kpis["U_google_unresolved"] == 1


def test_failed_probe_yields_unresolved_not_unique(db, project, area):
    seed_two_providers(db, project, area)
    run_bulk_match(db, project)
    broken = FakeAdapter(Provider.GOOGLE, [], fail=True)

    for place in unprobed_places(db, project.id, Provider.GRAB):
        probe = probe_place(db, project, place, broken, Provider.GOOGLE)
        assert probe.verdict == UniquenessVerdict.UNRESOLVED
        assert "Probe failed" in probe.reason

    kpis = calculate_comparison_kpis(db, project.id)
    assert kpis["GU_grab_only_verified"] == 0


def test_probe_can_recover_a_place_the_sweep_missed(db, project, area):
    """A place Google's sweep never returned but its probe does must count as matched."""
    grab_place = dto(Provider.GRAB, "grab-1", "Salon Gita Pattern", JAKARTA[0], JAKARTA[1])
    run = make_run(db, project, Provider.GRAB)
    run_sweep(db, run, FakeAdapter(Provider.GRAB, [grab_place]), [area], tile_radius_m=400)

    hidden = dto(Provider.GOOGLE, "goog-hidden", "Gita Pattern Salon", JAKARTA[0] + 0.00005, JAKARTA[1])
    google_adapter = FakeAdapter(Provider.GOOGLE, [hidden])

    for place in unprobed_places(db, project.id, Provider.GRAB):
        probe = probe_place(db, project, place, google_adapter, Provider.GOOGLE)
        assert probe.verdict == UniquenessVerdict.MATCHED

    recovered = db.query(ProviderPlace).filter_by(
        project_id=project.id, provider=Provider.GOOGLE, discovered_by_probe=True
    ).all()
    assert len(recovered) == 1

    kpis = calculate_comparison_kpis(db, project.id)
    assert kpis["M_matched"] == 1
    assert kpis["GU_grab_only_verified"] == 0


# --------------------------------------------------------------------------
# API surface
# --------------------------------------------------------------------------

def test_area_and_kpi_endpoints(client, headers):
    project = client.post("/api/v1/projects", json={
        "name": "API Comparison Project", "customer": "Test", "country": "Indonesia",
        "cities": ["Jakarta"], "categories": ["Hair Salon"],
    }, headers=headers).json()

    created = client.post("/api/v1/discovery/areas", json={
        "project_id": project["id"], "city": "Jakarta", "name": "Kemang",
        "center_lat": JAKARTA[0], "center_lng": JAKARTA[1], "radius_m": 800,
    }, headers=headers)
    assert created.status_code == 201

    listed = client.get(f"/api/v1/discovery/areas?project_id={project['id']}", headers=headers)
    assert listed.status_code == 200 and len(listed.json()) == 1

    kpis = client.get(f"/api/v1/comparison/{project['id']}/kpis", headers=headers)
    assert kpis.status_code == 200
    body = kpis.json()
    assert body["G_grab_total"] == 0 and body["K_google_total"] == 0
    assert body["invariant_unique_has_probe_evidence"] is True


def test_sweep_rejected_without_provider_credentials(client, headers):
    """Guards the credential check — and doubles as a canary that the suite is
    credential-free. If this ever returns 202, tests are reading a real .env and a
    sweep will spend real money; see the credential blanking in conftest.py."""
    project = client.post("/api/v1/projects", json={
        "name": "No Credentials Project", "customer": "Test", "country": "Indonesia",
    }, headers=headers).json()
    client.post("/api/v1/discovery/areas", json={
        "project_id": project["id"], "city": "Jakarta", "name": "Kemang",
        "center_lat": JAKARTA[0], "center_lng": JAKARTA[1], "radius_m": 500,
    }, headers=headers)

    response = client.post("/api/v1/discovery/sweeps", json={
        "project_id": project["id"], "provider": "GOOGLE",
    }, headers=headers)
    assert response.status_code == 400
    assert "GOOGLE_MAPS_API_KEY" in response.json()["detail"]


def test_comparison_report_downloads(client, headers):
    project = client.post("/api/v1/projects", json={
        "name": "Report Project", "customer": "Test", "country": "Indonesia",
    }, headers=headers).json()

    xlsx = client.get(f"/api/v1/comparison/{project['id']}/report.xlsx", headers=headers)
    assert xlsx.status_code == 200
    assert xlsx.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert xlsx.content[:2] == b"PK"

    geojson = client.get(f"/api/v1/comparison/{project['id']}/report.geojson", headers=headers)
    assert geojson.status_code == 200
    assert geojson.json()["type"] == "FeatureCollection"


# --------------------------------------------------------------------------
# Free area-coverage resolution
# --------------------------------------------------------------------------

def test_area_coverage_resolves_uniques_without_api_calls(db, project, area):
    """A record surrounded by the other provider's results, matching none of them,
    is resolvable from stored data alone — no probe needed."""
    from discovery_engine.services.coverage import EVIDENCE_AREA, resolve_by_area_coverage

    # Google swept this block and returned four salons.
    google = [dto(Provider.GOOGLE, f"k{i}", f"Salon Cendana Nomor {i}",
                  JAKARTA[0] + i * 0.0003, JAKARTA[1],
                  address=f"Jl. Cendana No.{i}, Jakarta") for i in range(4)]
    run_sweep(db, make_run(db, project, Provider.GOOGLE),
              FakeAdapter(Provider.GOOGLE, google), [area], tile_radius_m=400)

    # A Grab salon sits right among them but matches none.
    # 100 m from the nearest Google result: comfortably inside the 300 m coverage
    # radius, comfortably outside anything the matcher would call a candidate.
    grab = [dto(Provider.GRAB, "g1", "Rumah Cantik Anggrek Biru", JAKARTA[0] + 0.0018, JAKARTA[1],
                address="Jl. Anggrek Biru No.77, Jakarta")]
    run_sweep(db, make_run(db, project, Provider.GRAB),
              FakeAdapter(Provider.GRAB, grab), [area], tile_radius_m=400)

    run_bulk_match(db, project)
    summary = resolve_by_area_coverage(db, project)

    assert summary["resolved_unique"] == 1
    place = db.scalars(select(ProviderPlace).where(ProviderPlace.provider_place_id == "g1")).first()
    assert place.verdict == UniquenessVerdict.UNIQUE_VERIFIED

    from discovery_engine.models import UniquenessProbe
    evidence = db.scalars(select(UniquenessProbe).where(
        UniquenessProbe.provider_place_id == place.id)).first()
    assert evidence.evidence_method == EVIDENCE_AREA
    assert evidence.result_count >= 3
    assert "swept" in evidence.reason


def test_area_coverage_refuses_to_resolve_where_the_other_provider_has_no_data(db, project, area):
    """The whole point: absence from our download is not absence from the provider.
    With no nearby data from the other side, the record must stay UNRESOLVED."""
    from discovery_engine.services.coverage import resolve_by_area_coverage

    grab = [dto(Provider.GRAB, "g1", "Salon Anggrek Biru", JAKARTA[0], JAKARTA[1])]
    run_sweep(db, make_run(db, project, Provider.GRAB),
              FakeAdapter(Provider.GRAB, grab), [area], tile_radius_m=400)
    # Google swept nothing here at all.
    run_sweep(db, make_run(db, project, Provider.GOOGLE),
              FakeAdapter(Provider.GOOGLE, []), [area], tile_radius_m=400)

    run_bulk_match(db, project)
    summary = resolve_by_area_coverage(db, project)

    assert summary["resolved_unique"] == 0
    assert summary["still_unresolved_no_coverage"] == 1
    place = db.scalars(select(ProviderPlace).where(ProviderPlace.provider_place_id == "g1")).first()
    assert place.verdict == UniquenessVerdict.UNRESOLVED


def test_kpis_report_evidence_tiers_separately(db, project, area):
    """Probe-verified and area-verified must never be summed into one figure."""
    from discovery_engine.services.coverage import resolve_by_area_coverage

    google = [dto(Provider.GOOGLE, f"k{i}", f"Salon Cendana Nomor {i}",
                  JAKARTA[0] + i * 0.0003, JAKARTA[1],
                  address=f"Jl. Cendana No.{i}, Jakarta") for i in range(4)]
    run_sweep(db, make_run(db, project, Provider.GOOGLE),
              FakeAdapter(Provider.GOOGLE, google), [area], tile_radius_m=400)
    # 100 m from the nearest Google result: comfortably inside the 300 m coverage
    # radius, comfortably outside anything the matcher would call a candidate.
    grab = [dto(Provider.GRAB, "g1", "Rumah Cantik Anggrek Biru", JAKARTA[0] + 0.0018, JAKARTA[1],
                address="Jl. Anggrek Biru No.77, Jakarta")]
    run_sweep(db, make_run(db, project, Provider.GRAB),
              FakeAdapter(Provider.GRAB, grab), [area], tile_radius_m=400)

    run_bulk_match(db, project)
    resolve_by_area_coverage(db, project)
    kpis = calculate_comparison_kpis(db, project.id)

    assert kpis["GU_grab_only_verified"] == 1
    assert kpis["GU_grab_only_area_verified"] == 1
    assert kpis["GU_grab_only_probe_verified"] == 0
    assert kpis["invariant_unique_has_probe_evidence"] is True


# --------------------------------------------------------------------------
# City jobs
# --------------------------------------------------------------------------

def test_region_catalogue_covers_every_province():
    """A city picker is only useful if it spans the country."""
    from discovery_engine.data.indonesia import CITIES, provinces, resolve

    listed = provinces()
    assert len(listed) >= 34, "expected a province per Indonesian province"
    assert all(p["cities"] for p in listed)

    jakarta = resolve("jakarta")
    assert jakarta and jakarta.province == "DKI Jakarta"
    assert jakarta.core_radius_m < jakarta.full_radius_m
    assert resolve("not-a-city") is None

    # Coordinates must be inside Indonesia's bounding box.
    for city in CITIES:
        assert -11.5 <= city.lat <= 6.5, city.name
        assert 94.0 <= city.lng <= 141.5, city.name


def test_full_coverage_costs_more_than_core():
    from discovery_engine.data.indonesia import resolve
    from discovery_engine.services.jobs import estimate_job

    settings = priced_settings(google_maps_api_key="key", rate_google_nearby_per_1k=35.0)
    core = estimate_job(resolve("denpasar"), "CORE", 400.0, settings)
    full = estimate_job(resolve("denpasar"), "FULL", 400.0, settings)

    assert full["tiles"] > core["tiles"]
    assert full["sweep_cost_expected_usd"] > core["sweep_cost_expected_usd"]
    assert core["providers_configured"] == ["GOOGLE"]


def test_job_runs_end_to_end_and_scopes_results_to_its_city(db, project, monkeypatch):
    """One action: sweep both providers, match, probe, count — for one city only."""
    from discovery_engine.data.indonesia import resolve
    from discovery_engine.models import DiscoveryJob, JobStage
    from discovery_engine.services import jobs as jobs_module

    city = resolve("denpasar")
    shared_grab = dto(Provider.GRAB, "g-shared", "Salon Gita Pattern", city.lat, city.lng)
    grab_only = dto(Provider.GRAB, "g-only", "Nusa Hair Studio Melati", city.lat + 0.0015, city.lng)
    shared_google = dto(Provider.GOOGLE, "k-shared", "Gita Pattern Salon", city.lat + 0.00005, city.lng)
    google_only = dto(Provider.GOOGLE, "k-only", "Mawar Beauty Cempaka", city.lat - 0.0015, city.lng)

    grab_adapter = FakeAdapter(Provider.GRAB, [shared_grab, grab_only])
    google_adapter = FakeAdapter(Provider.GOOGLE, [shared_google, google_only])
    adapters = {Provider.GRAB: grab_adapter, Provider.GOOGLE: google_adapter}

    monkeypatch.setattr(jobs_module, "get_adapter", lambda p: adapters[p])
    monkeypatch.setattr(jobs_module, "available_providers",
                        lambda settings=None: [Provider.GRAB, Provider.GOOGLE])
    monkeypatch.setattr(jobs_module, "get_settings",
                        lambda: priced_settings(rate_google_nearby_per_1k=35.0,
                                                rate_grab_search_text_per_1k=2.0))

    job = jobs_module.create_job(db, project, city, "CORE", 400.0, user_id=None)
    jobs_module.execute_job(db, job)

    assert job.status == RunStatus.COMPLETED
    assert job.stage == JobStage.FINISHED
    assert job.matched_count == 1
    assert job.grab_only_count == 1
    assert job.google_only_count == 1
    assert job.unresolved_count == 0

    # Every place discovered carries this job's id, so a download is city-scoped.
    places = jobs_module.job_places(db, job.id)
    assert places and all(p.job_id == job.id for p in places)


def test_job_reports_unresolved_rather_than_unique_when_probing_is_capped(db, project, monkeypatch):
    """Hitting the probe cap must not turn unprobed records into 'unique'."""
    from discovery_engine.data.indonesia import resolve
    from discovery_engine.services import jobs as jobs_module

    city = resolve("mataram")
    grab_places = [
        dto(Provider.GRAB, f"g{i}", f"Salon Melati Nomor {i}", city.lat + i * 0.0004, city.lng)
        for i in range(4)
    ]
    adapters = {
        Provider.GRAB: FakeAdapter(Provider.GRAB, grab_places),
        Provider.GOOGLE: FakeAdapter(Provider.GOOGLE, []),
    }
    monkeypatch.setattr(jobs_module, "get_adapter", lambda p: adapters[p])
    monkeypatch.setattr(jobs_module, "available_providers",
                        lambda settings=None: [Provider.GRAB, Provider.GOOGLE])
    monkeypatch.setattr(jobs_module, "get_settings",
                        lambda: priced_settings(rate_grab_search_text_per_1k=2.0))

    job = jobs_module.create_job(db, project, city, "CORE", 400.0, user_id=None)
    job.max_probe_calls = 2
    jobs_module.execute_job(db, job)

    assert job.status == RunStatus.ABORTED_BUDGET
    assert "still unprobed" in job.error
    assert job.grab_only_count == 2          # only the two we actually probed
    assert job.unresolved_count == 2         # the rest stay unknown, not unique


def test_grab_categories_classify_onto_the_unified_taxonomy():
    """Category strings verbatim from live Denpasar and Jakarta runs.

    Grab's hierarchy is the authoritative signal: the path before '::' decides the
    unified category, so a place lands in a bucket because of what the provider
    says it is, not because of what its name reads like.
    """
    from discovery_engine.services.taxonomy import UnifiedCategory, classify_grab

    assert classify_grab(["eat and drink::restaurant"]) is UnifiedCategory.RESTAURANT
    assert classify_grab(["eat and drink::coffee shop"]) is UnifiedCategory.COFFEE_SHOP
    assert classify_grab(["eat and drink::bakery"]) is UnifiedCategory.BAKERY
    assert classify_grab(["healthcare::hospital"]) is UnifiedCategory.HOSPITAL
    assert classify_grab(["accommodation::hotel"]) is UnifiedCategory.HOTEL

    # The taxonomy covers the wider POI landscape too, so these classify to their
    # real categories rather than to OTHER. Restricting a run to the core seven is
    # done by the scope gate, not by refusing to classify.
    assert classify_grab(
        ["academic space", "education::academic spaces"]) is UnifiedCategory.EDUCATION
    assert classify_grab(
        ["beauty services::other salons"]) is UnifiedCategory.BEAUTY
    assert classify_grab(
        ["toy store", "general merchandise::baby::toys"]) is UnifiedCategory.RETAIL

    # Pet care is vetoed before the healthcare root claims it: a groomer is not a
    # medical facility, and it must never land in Hospitals & Clinics.
    assert classify_grab(
        ["pet grooming", "healthcare::pets::groomer"]) is UnifiedCategory.OTHER


def test_scope_gate_uses_provider_taxonomy_not_the_name():
    """A place whose name suggests one category must not override its real one.

    This is the regression that put Quran schools into a live Denpasar export back
    when the gate trusted a loose name match.
    """
    from discovery_engine.services.sweep import _in_scope

    school = dto(Provider.GRAB, "x1", "Sekolah Kopi Nusantara", -8.65, 115.21,
                 categories=["academic space", "education::academic spaces"])
    cafe = dto(Provider.GRAB, "x2", "Kedai Kopi Ayu", -8.65, 115.21,
               categories=["eat and drink::coffee shop"])

    assert _in_scope(school, {"COFFEE_SHOP"}) is False
    assert _in_scope(cafe, {"COFFEE_SHOP"}) is True
    # The school is out of scope for every category this deployment tracks.
    assert _in_scope(school, {"RESTAURANT", "HOTEL", "HOSPITAL"}) is False


def test_no_category_filter_keeps_everything_in_scope():
    """A general POI sweep has no vertical, so nothing is filtered out."""
    from discovery_engine.services.sweep import _in_scope

    for categories in (None, set()):
        assert _in_scope(
            dto(Provider.GRAB, "y1", "Warung Bu Made", -8.65, 115.21,
                categories=["eat and drink::restaurant"]), categories) is True
        assert _in_scope(
            dto(Provider.GRAB, "y2", "Hotel Melati", -8.65, 115.21,
                categories=["accommodation::hotel"]), categories) is True


def test_google_adapter_extracts_city_from_address_components():
    """Without addressComponents every Google record lands with an unknown city and
    the workbench city filter is useless on half the dataset."""
    from discovery_engine.providers.google import GooglePlacesAdapter

    adapter = GooglePlacesAdapter(api_key="k", client=object())
    place = {
        "id": "abc",
        "displayName": {"text": "Princess Beauty Salon"},
        "formattedAddress": "Jl. Yudistira No.28, Denpasar, Bali 80229",
        "location": {"latitude": -8.65, "longitude": 115.21},
        "types": ["beauty_salon"],
        "addressComponents": [
            {"longText": "Denpasar", "types": ["locality", "political"]},
            {"longText": "Bali", "types": ["administrative_area_level_1", "political"]},
            {"longText": "80229", "types": ["postal_code"]},
        ],
    }
    row = adapter._to_dto(place)
    assert row.city == "Denpasar"
    assert row.province == "Bali"
    assert row.postal_code == "80229"

    # Missing components must not raise, just leave the fields empty.
    bare = adapter._to_dto({"id": "x", "displayName": {"text": "Salon"}, "location": {}})
    assert bare.city is None and bare.province is None


def test_google_daily_quota_fails_fast_instead_of_retrying(monkeypatch):
    """A per-day quota does not recover from backoff; burning retries on it wastes
    time and hides an actionable error."""
    import httpx

    from discovery_engine.providers import google as google_module

    calls = {"n": 0}

    class QuotaClient:
        def post(self, url, json=None, headers=None):
            calls["n"] += 1
            return httpx.Response(
                429,
                text='{"error":{"message":"Quota exceeded for quota metric '
                     "'SearchNearbyRequest' and limit 'SearchNearbyRequest per day'\"}}",
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(google_module, "get_settings",
                        lambda: priced_settings(google_maps_api_key="k"))
    adapter = google_module.GooglePlacesAdapter(api_key="k", client=QuotaClient())

    with pytest.raises(google_module.QuotaExhausted) as excinfo:
        adapter.sweep(Tile(-8.65, 115.21, 400.0))

    assert calls["n"] == 1, "a daily quota must not be retried"
    assert "Google Cloud console" in str(excinfo.value)


def test_job_budget_is_cumulative_across_sweep_and_probe(db, project, monkeypatch):
    """Regression: a $5 job spent $7.25 because the sweep and probe stages each
    enforced their own $5 ceiling. Stages must share one budget."""
    from discovery_engine.data.indonesia import resolve
    from discovery_engine.services import jobs as jobs_module

    city = resolve("ambon")
    grab_places = [
        dto(Provider.GRAB, f"g{i}", f"Salon Anggrek Nomor {i}", city.lat + i * 0.0004, city.lng)
        for i in range(20)
    ]
    google_places = [dto(Provider.GOOGLE, "k1", "Salon Berbeda Sekali", city.lat + 0.02, city.lng)]
    adapters = {
        Provider.GRAB: FakeAdapter(Provider.GRAB, grab_places),
        Provider.GOOGLE: FakeAdapter(Provider.GOOGLE, google_places),
    }
    monkeypatch.setattr(jobs_module, "get_adapter", lambda p: adapters[p])
    monkeypatch.setattr(jobs_module, "available_providers",
                        lambda settings=None: [Provider.GRAB, Provider.GOOGLE])
    settings = priced_settings(
        rate_google_nearby_per_1k=35.0, rate_google_text_per_1k=35.0,
        rate_grab_search_text_per_1k=-1.0,
        google_max_spend_per_run_usd=0.50, grab_max_spend_per_run_usd=0.50,
        google_max_calls_per_run=100_000, grab_max_calls_per_run=100_000,
    )
    monkeypatch.setattr(jobs_module, "get_settings", lambda: settings)
    monkeypatch.setattr("discovery_engine.services.sweep.get_settings", lambda: settings)

    job = jobs_module.create_job(db, project, city, "CORE", 400.0, user_id=None)
    job.max_probe_calls = 100_000
    jobs_module.execute_job(db, job)

    spent, _ = jobs_module.job_spend_to_date(db, job)
    # The whole job, sweeps plus probes, stays inside the single $0.50 ceiling
    # (plus at most one call of overshoot, since the check precedes each call).
    assert spent is not None
    assert spent <= 0.50 + 0.035, f"job spent {spent} against a $0.50 ceiling"


def test_sweep_cannot_consume_the_budget_reserved_for_probing(db, project, monkeypatch):
    """Probing is what licenses the 'unique' claim. If the sweep is allowed to spend
    the whole budget, every record ends up UNRESOLVED and the run yields nothing."""
    from discovery_engine.data.indonesia import resolve
    from discovery_engine.services import jobs as jobs_module

    city = resolve("ambon")
    grab_places = [
        dto(Provider.GRAB, f"g{i}", f"Salon Anggrek Nomor {i}", city.lat + i * 0.0006, city.lng)
        for i in range(6)
    ]
    # Google sweep finds nothing but still costs a call per tile, so an unreserved
    # budget would be entirely eaten before probing starts.
    adapters = {
        Provider.GRAB: FakeAdapter(Provider.GRAB, grab_places),
        Provider.GOOGLE: FakeAdapter(Provider.GOOGLE, []),
    }
    monkeypatch.setattr(jobs_module, "get_adapter", lambda p: adapters[p])
    monkeypatch.setattr(jobs_module, "available_providers",
                        lambda settings=None: [Provider.GRAB, Provider.GOOGLE])
    settings = priced_settings(
        rate_google_nearby_per_1k=35.0, rate_google_text_per_1k=35.0,
        rate_grab_search_text_per_1k=-1.0,
        google_max_spend_per_run_usd=1.0, grab_max_spend_per_run_usd=1.0,
        google_max_calls_per_run=100_000, grab_max_calls_per_run=100_000,
    )
    monkeypatch.setattr(jobs_module, "get_settings", lambda: settings)
    monkeypatch.setattr("discovery_engine.services.sweep.get_settings", lambda: settings)

    job = jobs_module.create_job(db, project, city, "CORE", 400.0, user_id=None, radius_m=2500)
    jobs_module.execute_job(db, job)

    # Probing got budget of its own, so records were actually verified.
    assert job.probes_done > 0, "the sweep consumed the entire budget"
    spent, _ = jobs_module.job_spend_to_date(db, job)
    assert spent is not None and spent <= 1.0 + 0.035


def test_probing_interleaves_providers_under_a_budget(db, project, monkeypatch):
    """Regression from a live $5 run that reported "Google only: 0".

    Draining one provider's queue before starting the other means a budget-limited run
    never probes the second provider, and reports zero unique records for it. That
    reads as a finding but is purely an ordering artifact.
    """
    from discovery_engine.data.indonesia import resolve
    from discovery_engine.models import UniquenessProbe
    from discovery_engine.services import jobs as jobs_module

    city = resolve("kupang")
    # Both providers hold records the other cannot see, so nothing matches and every
    # record needs probing — but the budget only covers a handful.
    grab_places = [dto(Provider.GRAB, f"g{i}", f"Salon Flamboyan Nomor {i}",
                       city.lat + i * 0.0008, city.lng) for i in range(6)]
    google_places = [dto(Provider.GOOGLE, f"k{i}", f"Salon Cendana Nomor {i}",
                         city.lat, city.lng + i * 0.0008) for i in range(6)]
    adapters = {
        Provider.GRAB: FakeAdapter(Provider.GRAB, grab_places),
        Provider.GOOGLE: FakeAdapter(Provider.GOOGLE, google_places),
    }
    monkeypatch.setattr(jobs_module, "get_adapter", lambda p: adapters[p])
    monkeypatch.setattr(jobs_module, "available_providers",
                        lambda settings=None: [Provider.GRAB, Provider.GOOGLE])
    settings = priced_settings(
        rate_google_nearby_per_1k=35.0, rate_google_text_per_1k=35.0,
        rate_grab_search_text_per_1k=-1.0,  # unpriced, as in the real configuration
        google_max_spend_per_run_usd=2.0, grab_max_spend_per_run_usd=2.0,
        google_max_calls_per_run=100_000, grab_max_calls_per_run=100_000,
    )
    monkeypatch.setattr(jobs_module, "get_settings", lambda: settings)
    monkeypatch.setattr("discovery_engine.services.sweep.get_settings", lambda: settings)

    job = jobs_module.create_job(db, project, city, "CORE", 400.0, user_id=None, radius_m=1200)
    job.max_probe_calls = 6  # far fewer than the 12 records needing a probe
    jobs_module.execute_job(db, job)

    assert job.probes_done > 0, "probing never ran; the test's budget premise is wrong"

    probed = db.scalars(select(UniquenessProbe).where(UniquenessProbe.project_id == project.id)).all()
    probed_providers = {db.get(ProviderPlace, p.provider_place_id).provider for p in probed}
    assert probed_providers == {Provider.GRAB, Provider.GOOGLE}, (
        "a truncated probe stage must still reach both providers"
    )


def test_create_job_accepts_a_radius_override(db, project):
    from discovery_engine.data.indonesia import resolve
    from discovery_engine.services import jobs as jobs_module

    city = resolve("denpasar")
    job = jobs_module.create_job(db, project, city, "CORE", 400.0, user_id=None, radius_m=1200)

    assert job.radius_m == 1200
    assert job.radius_m < city.core_radius_m
    from discovery_engine.models import SearchArea
    assert db.get(SearchArea, job.area_id).radius_m == 1200


def test_probe_stage_respects_its_own_spend_ceiling(db, project, monkeypatch):
    """Probing is charged separately from the sweep and must be capped in dollars too,
    or a large unmatched set silently blows past the sweep's ceiling."""
    from discovery_engine.data.indonesia import resolve
    from discovery_engine.services import jobs as jobs_module

    city = resolve("ambon")
    grab_places = [
        dto(Provider.GRAB, f"g{i}", f"Salon Anggrek Nomor {i}", city.lat + i * 0.0004, city.lng)
        for i in range(8)
    ]
    adapters = {
        Provider.GRAB: FakeAdapter(Provider.GRAB, grab_places),
        Provider.GOOGLE: FakeAdapter(Provider.GOOGLE, []),
    }
    monkeypatch.setattr(jobs_module, "get_adapter", lambda p: adapters[p])
    monkeypatch.setattr(jobs_module, "available_providers",
                        lambda settings=None: [Provider.GRAB, Provider.GOOGLE])
    # $0.10 ceiling at $35/1000 allows only 2 Google probe calls.
    monkeypatch.setattr(jobs_module, "get_settings",
                        lambda: priced_settings(rate_google_text_per_1k=35.0,
                                                rate_grab_search_text_per_1k=-1.0,
                                                google_max_spend_per_run_usd=0.10,
                                                google_max_calls_per_run=10_000))

    job = jobs_module.create_job(db, project, city, "CORE", 400.0, user_id=None)
    job.max_probe_calls = 10_000  # deliberately not the binding constraint
    jobs_module.execute_job(db, job)

    assert job.status == RunStatus.ABORTED_BUDGET
    assert "spend ceiling" in job.error
    assert job.probes_done <= 4
    assert job.unresolved_count > 0


def test_job_endpoints(client, headers):
    project = client.post("/api/v1/projects", json={
        "name": "City Job Project", "customer": "Test", "country": "Indonesia",
    }, headers=headers).json()

    regions = client.get("/api/v1/jobs/regions", headers=headers)
    assert regions.status_code == 200
    assert any(p["province"] == "Bali" for p in regions.json()["provinces"])

    est = client.post("/api/v1/jobs/estimate", json={
        "project_id": project["id"], "city_code": "denpasar", "coverage": "CORE",
    }, headers=headers)
    assert est.status_code == 200 and est.json()["tiles"] > 0

    unknown = client.post("/api/v1/jobs/estimate", json={
        "project_id": project["id"], "city_code": "atlantis",
    }, headers=headers)
    assert unknown.status_code == 404

    # No credentials in the test environment, so a run must be refused outright.
    start = client.post("/api/v1/jobs", json={
        "project_id": project["id"], "city_code": "denpasar", "confirm": True,
    }, headers=headers)
    assert start.status_code == 400
    assert "No provider credentials" in start.json()["detail"]


def test_job_requires_explicit_confirmation(client, headers, monkeypatch):
    """A run spends real money; it must never start by accident."""
    from discovery_engine.routers import jobs as jobs_router

    monkeypatch.setattr(jobs_router, "available_providers", lambda settings=None: [Provider.GOOGLE])
    project = client.post("/api/v1/projects", json={
        "name": "Confirm Project", "customer": "Test", "country": "Indonesia",
    }, headers=headers).json()

    response = client.post("/api/v1/jobs", json={
        "project_id": project["id"], "city_code": "denpasar", "confirm": False,
    }, headers=headers)
    assert response.status_code == 400
    assert "confirm=true" in response.json()["detail"]


# --------------------------------------------------------------------------
# Cost monitoring
# --------------------------------------------------------------------------

def priced_settings(**overrides):
    from discovery_engine.config import Settings

    base = dict(_env_file=None, jwt_secret="x" * 32, demo_admin_password="y")
    base.update(overrides)
    return Settings(**base)


def test_unconfigured_rate_reports_unknown_not_zero():
    """A missing rate must never read as a free call — a budget guard built on
    silent zeros never fires."""
    from discovery_engine.services.pricing import GRAB_SEARCH_TEXT, summarise

    settings = priced_settings(rate_grab_search_text_per_1k=-1.0)
    result = summarise({GRAB_SEARCH_TEXT: 5000}, settings)

    assert result["cost_usd"] is None
    assert result["cost_is_complete"] is False
    assert result["unpriced_operations"] == [GRAB_SEARCH_TEXT]
    assert result["total_calls"] == 5000


def test_partial_pricing_never_passes_as_a_complete_total():
    from discovery_engine.services.pricing import GOOGLE_NEARBY, GRAB_SEARCH_TEXT, summarise

    settings = priced_settings(rate_google_nearby_per_1k=35.0, rate_grab_search_text_per_1k=-1.0)
    result = summarise({GOOGLE_NEARBY: 1000, GRAB_SEARCH_TEXT: 8000}, settings)

    assert result["cost_usd"] == 35.0          # the Google half only
    assert result["cost_is_complete"] is False  # and it says so
    assert GRAB_SEARCH_TEXT in result["unpriced_operations"]


def test_cost_scales_per_thousand_calls():
    from discovery_engine.services.pricing import GOOGLE_NEARBY, cost_of

    settings = priced_settings(rate_google_nearby_per_1k=35.0)
    assert cost_of(GOOGLE_NEARBY, 1000, settings).cost_usd == 35.0
    assert cost_of(GOOGLE_NEARBY, 250, settings).cost_usd == 8.75
    assert cost_of(GOOGLE_NEARBY, 0, settings).cost_usd == 0.0


def test_grab_estimate_multiplies_by_the_query_term_matrix():
    """Grab has no nearby search, so each tile costs one call per search term."""
    from discovery_engine.providers.grab import default_query_terms
    from discovery_engine.services.pricing import estimate_sweep

    settings = priced_settings(rate_grab_search_text_per_1k=2.0)
    grab = estimate_sweep(Provider.GRAB, tile_count=100, settings=settings)
    google = estimate_sweep(Provider.GOOGLE, tile_count=100, settings=settings)

    assert grab["calls_per_tile"] == len(default_query_terms())
    assert google["calls_per_tile"] == 1
    assert grab["calls_minimum"] == 100 * len(default_query_terms())
    assert grab["cost_minimum_usd"] < grab["cost_expected_usd"] <= grab["cost_at_cap_usd"]


def test_sweep_records_cost_and_call_counts(db, project, area):
    from discovery_engine.services.pricing import GOOGLE_NEARBY

    places = [dto(Provider.GOOGLE, "g1", "Salon Gita Pattern", *JAKARTA)]
    adapter = FakeAdapter(Provider.GOOGLE, places)
    run = make_run(db, project, Provider.GOOGLE)

    run_sweep(db, run, adapter, [area], tile_radius_m=400)

    assert run.call_counts[GOOGLE_NEARBY] == run.api_calls
    assert run.est_cost_usd is not None
    assert run.actual_cost_usd == pytest.approx(run.api_calls * 32.0 / 1000, rel=1e-6)


def test_sweep_stops_at_the_spend_ceiling(db, project, area, monkeypatch):
    """The USD ceiling must halt a run independently of the call cap."""
    from discovery_engine.services import sweep as sweep_module

    monkeypatch.setattr(
        sweep_module, "get_settings",
        lambda: priced_settings(rate_google_nearby_per_1k=35.0, google_max_spend_per_run_usd=0.05,
                                google_max_calls_per_run=10_000),
    )
    adapter = FakeAdapter(Provider.GOOGLE, [dto(Provider.GOOGLE, "g1", "Salon Gita", *JAKARTA)])
    run = make_run(db, project, Provider.GOOGLE)

    run_sweep(db, run, adapter, [area], tile_radius_m=100)

    assert run.status == RunStatus.ABORTED_BUDGET
    assert "spend ceiling" in run.error
    assert run.actual_cost_usd >= 0.05
    assert run.api_calls < 10_000


def test_spend_ceiling_is_not_enforced_when_the_rate_is_unknown(db, project, area, monkeypatch):
    """With no rate configured, cost is unknown — the call cap must still bound the run,
    but an unknown cost must not be treated as zero and allowed to run forever."""
    from discovery_engine.services import sweep as sweep_module

    monkeypatch.setattr(
        sweep_module, "get_settings",
        lambda: priced_settings(rate_google_nearby_per_1k=-1.0, google_max_spend_per_run_usd=0.05,
                                google_max_calls_per_run=4),
    )
    adapter = FakeAdapter(Provider.GOOGLE, [dto(Provider.GOOGLE, "g1", "Salon Gita", *JAKARTA)])
    run = make_run(db, project, Provider.GOOGLE)

    run_sweep(db, run, adapter, [area], tile_radius_m=100)

    assert run.status == RunStatus.ABORTED_BUDGET
    assert "call cap" in run.error
    assert run.actual_cost_usd is None
    assert run.api_calls <= 4


def test_grab_adapter_records_the_provider_reported_pricing_bucket(monkeypatch):
    """Amazon Location says which bucket it charged; capture it rather than guessing."""
    from discovery_engine.providers import grab as grab_module

    class BucketClient:
        def search_text(self, **request):
            return {
                "ResultItems": [],
                "ResponseMetadata": {"HTTPHeaders": {"x-amz-geo-pricing-bucket": "Stored"}},
            }

    monkeypatch.setattr(grab_module, "get_settings", lambda: priced_settings(aws_location_api_key="v1.public.t"))
    adapter = grab_module.GrabMapsAdapter(client=BucketClient())
    result = adapter.probe("Salon Gita", JAKARTA[0], JAKARTA[1], None)

    assert result.pricing_buckets == {"Stored": 1}


def test_storage_intended_use_is_the_default():
    """Amazon Location's Core bucket forbids permanent storage, and this app persists
    every result, so Storage is the only correct setting."""
    assert priced_settings().grab_intended_use == "Storage"


def test_cost_endpoints(client, headers):
    project = client.post("/api/v1/projects", json={
        "name": "Cost Project", "customer": "Test", "country": "Indonesia",
    }, headers=headers).json()
    client.post("/api/v1/discovery/areas", json={
        "project_id": project["id"], "city": "Jakarta", "name": "Kemang",
        "center_lat": JAKARTA[0], "center_lng": JAKARTA[1], "radius_m": 1000,
    }, headers=headers)

    estimate = client.post("/api/v1/discovery/sweeps/estimate", json={
        "project_id": project["id"], "provider": "GOOGLE", "tile_radius_m": 400,
    }, headers=headers)
    assert estimate.status_code == 200
    body = estimate.json()
    assert body["tiles"] > 0
    assert body["calls_expected"] >= body["calls_minimum"]
    assert len(body["areas"]) == 1

    costs = client.get(f"/api/v1/discovery/costs/{project['id']}", headers=headers)
    assert costs.status_code == 200
    assert costs.json()["overall"]["total_calls"] == 0
    assert "billing console" in costs.json()["warning"]


def test_grab_adapter_sends_the_api_key_and_stays_unsigned(monkeypatch):
    """An Amazon Location API key authenticates on its own and must reach SearchText."""
    from discovery_engine.config import Settings
    from discovery_engine.providers import grab as grab_module

    captured = {}

    class RecordingClient:
        def search_text(self, **request):
            captured.update(request)
            return {"ResultItems": []}

    fake_settings = Settings(
        _env_file=None,  # never read the developer's real .env into a test
        jwt_secret="x" * 32,
        demo_admin_password="y",
        aws_location_api_key="v1.public.testtoken",
    )
    monkeypatch.setattr(grab_module, "get_settings", lambda: fake_settings)

    adapter = grab_module.GrabMapsAdapter(client=RecordingClient())
    adapter.probe("Salon Gita", JAKARTA[0], JAKARTA[1], "Jl. Kemang Raya 10")

    assert captured["Key"] == "v1.public.testtoken"
    assert captured["Filter"]["IncludeCountries"] == ["IDN"]
    # GeoJSON order: longitude first.
    assert captured["Filter"]["Circle"]["Center"] == [JAKARTA[1], JAKARTA[0]]
    assert captured["IntendedUse"] == fake_settings.grab_intended_use


def test_grab_adapter_omits_key_when_using_sigv4(monkeypatch):
    from discovery_engine.config import Settings
    from discovery_engine.providers import grab as grab_module

    captured = {}

    class RecordingClient:
        def search_text(self, **request):
            captured.update(request)
            return {"ResultItems": []}

    fake_settings = Settings(
        _env_file=None,  # never read the developer's real .env into a test
        jwt_secret="x" * 32,
        demo_admin_password="y",
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="secret",
    )
    monkeypatch.setattr(grab_module, "get_settings", lambda: fake_settings)

    adapter = grab_module.GrabMapsAdapter(client=RecordingClient())
    adapter.probe("Salon Gita", JAKARTA[0], JAKARTA[1], None)

    assert "Key" not in captured
    assert fake_settings.grab_enabled is True
    assert fake_settings.grab_uses_api_key is False


def test_bucket_validation_rejects_unknown_bucket(client, headers):
    project = client.post("/api/v1/projects", json={
        "name": "Bucket Project", "customer": "Test", "country": "Indonesia",
    }, headers=headers).json()
    response = client.get(f"/api/v1/comparison/{project['id']}/records?bucket=nonsense", headers=headers)
    assert response.status_code == 400
