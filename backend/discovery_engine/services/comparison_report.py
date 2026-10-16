"""XLSX and GeoJSON coverage-comparison reports."""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    DiscoveryRun,
    MatchDecision,
    PoiMatch,
    Project,
    Provider,
    ProviderPlace,
    UniquenessProbe,
    UniquenessVerdict,
)
from .comparison import calculate_comparison_kpis
from .geo import haversine_m

HEADER_FILL = PatternFill("solid", fgColor="183B56")
HEADER_FONT = Font(bold=True, color="FFFFFF")

UNIQUE_HEADERS = [
    "Provider", "Provider Place ID", "Business Name", "Categories", "Address", "City", "Province",
    "Latitude", "Longitude", "Phone", "Website", "Business Status",
    "Evidence Method", "Evidence Strength",
    "Probe Query", "Result Count", "Best Score", "Evidence Timestamp", "Evidence Reason",
    "Found By Probe",
]

EVIDENCE_STRENGTH = {
    "PROBE": "STRONG - live lookup, no category filter",
    "AREA_COVERAGE": "MODERATE - swept area, category filter applies",
}

MATCHED_HEADERS = [
    "Match Score", "Distance (m)", "Method", "Reviewer",
    "Grab Place ID", "Grab Name", "Grab Address", "Grab City", "Grab Lat", "Grab Lng",
    "Google Place ID", "Google Name", "Google Address", "Google City", "Google Lat", "Google Lng",
    "Google Phone", "Google Website", "Signal Breakdown",
]


def _write_header(sheet, headers: list[str]) -> None:
    for col, header in enumerate(headers, start=1):
        cell = sheet.cell(1, col, header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
    sheet.freeze_panes = "A2"


def _autosize(sheet) -> None:
    for column in sheet.columns:
        letter = column[0].column_letter
        width = max((len(str(c.value or "")) for c in column), default=10)
        sheet.column_dimensions[letter].width = min(width + 2, 48)


def build_comparison_workbook(db: Session, project: Project, job=None) -> tuple[bytes, str, dict]:
    """Build the comparison workbook for a project, or for one city job."""
    job_id = job.id if job is not None else None
    kpis = calculate_comparison_kpis(db, project.id, job_id=job_id)

    place_query = select(ProviderPlace).where(ProviderPlace.project_id == project.id)
    if job_id is not None:
        place_query = place_query.where(ProviderPlace.job_id == job_id)
    places = {p.id: p for p in db.scalars(place_query).all()}
    probes = {
        p.provider_place_id: p
        for p in db.scalars(select(UniquenessProbe).where(UniquenessProbe.project_id == project.id)).all()
    }
    run_query = select(DiscoveryRun).where(DiscoveryRun.project_id == project.id)
    if job is not None:
        run_query = run_query.where(DiscoveryRun.id.in_(job.run_ids or [0]))
    runs = list(db.scalars(run_query.order_by(DiscoveryRun.id)).all())

    wb = Workbook()

    # --- Executive summary -------------------------------------------------
    summary = wb.active
    summary.title = "Executive Summary"
    summary.append(["JSAN GeoDiscover — GrabMaps vs Google Places coverage comparison"])
    summary["A1"].font = Font(bold=True, size=13)
    summary.append([])
    summary.append(["Project", project.name])
    summary.append(["Customer", project.customer])
    if job is not None:
        summary.append(["City", job.city_name])
        summary.append(["Province", job.province])
        summary.append(["Coverage", f"{job.coverage} ({int(job.radius_m)} m radius)"])
    summary.append(["Generated (UTC)", datetime.now(timezone.utc).isoformat(timespec="seconds")])
    summary.append([])
    summary.append(["Metric", "Value"])
    header_row = summary.max_row
    for cell in (summary.cell(header_row, 1), summary.cell(header_row, 2)):
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
    for key, value in kpis.items():
        if isinstance(value, list):
            continue
        summary.append([key, value])

    summary.append([])
    summary.append(["Discovery runs", ""])
    summary.append(["Run", "Provider", "Status", "Tiles planned", "Tiles done", "Saturated tiles", "API calls", "Places kept"])
    for run in runs:
        summary.append([
            run.id, run.provider.value, run.status.value, run.tiles_planned,
            run.tiles_done, run.saturated_tiles, run.api_calls, run.places_kept,
        ])
    _autosize(summary)

    # --- Unique buckets ----------------------------------------------------
    for title, provider in (("Grab Incremental Candidates", Provider.GRAB), ("Google Baseline-Only Leads", Provider.GOOGLE)):
        sheet = wb.create_sheet(title)
        _write_header(sheet, UNIQUE_HEADERS)
        rows = [
            p for p in places.values()
            if p.provider == provider and p.in_scope and p.verdict == UniquenessVerdict.UNIQUE_VERIFIED
        ]
        for place in sorted(rows, key=lambda p: (p.city or "", p.name)):
            probe = probes.get(place.id)
            query = ""
            if probe and probe.queries:
                first = probe.queries[0]
                query = " ".join(str(first.get(k) or "") for k in ("name", "address")).strip()
            method = probe.evidence_method if probe else None
            sheet.append([
                place.provider.value, place.provider_place_id, place.name, ", ".join(place.categories or []),
                place.address, place.city, place.province, place.lat, place.lng,
                place.phone_e164, place.website, place.business_status,
                method,
                EVIDENCE_STRENGTH.get(method, "NONE"),
                query,
                probe.result_count if probe else None,
                probe.best_score if probe else None,
                probe.probed_at.isoformat() if probe else None,
                probe.reason if probe else "NO EVIDENCE — DO NOT REPORT",
                "YES" if place.discovered_by_probe else "NO",
            ])
        _autosize(sheet)

    # --- Matched -----------------------------------------------------------
    def in_scope(match: PoiMatch) -> bool:
        return match.grab_place_id in places and match.google_place_id in places

    matched_sheet = wb.create_sheet("Matched")
    _write_header(matched_sheet, MATCHED_HEADERS)
    for match in db.scalars(
        select(PoiMatch).where(PoiMatch.project_id == project.id, PoiMatch.decision == MatchDecision.MATCHED)
    ).all():
        if in_scope(match):
            _append_match_row(matched_sheet, match, places)
    _autosize(matched_sheet)

    # --- Possible matches (review queue) -----------------------------------
    possible_sheet = wb.create_sheet("Possible Matches")
    _write_header(possible_sheet, MATCHED_HEADERS)
    for match in db.scalars(
        select(PoiMatch)
        .where(PoiMatch.project_id == project.id, PoiMatch.decision == MatchDecision.POSSIBLE_MATCH)
        .order_by(PoiMatch.score.desc())
    ).all():
        if in_scope(match):
            _append_match_row(possible_sheet, match, places)
    _autosize(possible_sheet)

    # --- Unresolved --------------------------------------------------------
    unresolved_sheet = wb.create_sheet("Unresolved")
    _write_header(unresolved_sheet, ["Provider", "Provider Place ID", "Business Name", "Address", "City",
                                     "Latitude", "Longitude", "Why unresolved"])
    for place in sorted(
        [p for p in places.values() if p.in_scope and p.verdict == UniquenessVerdict.UNRESOLVED],
        key=lambda p: (p.provider.value, p.city or "", p.name),
    ):
        probe = probes.get(place.id)
        unresolved_sheet.append([
            place.provider.value, place.provider_place_id, place.name, place.address, place.city,
            place.lat, place.lng,
            probe.reason if probe else "Not yet probed in the opposite provider",
        ])
    _autosize(unresolved_sheet)

    # --- Method & limitations ---------------------------------------------
    method = wb.create_sheet("Method & Limitations")
    for line in _method_notes(kpis, runs):
        method.append([line])
    method.column_dimensions["A"].width = 130
    method["A1"].font = Font(bold=True, size=12)

    buffer = io.BytesIO()
    wb.save(buffer)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if job is not None:
        safe_city = re.sub(r"[^A-Za-z0-9]+", "_", job.city_name).strip("_") or "city"
        file_name = f"GeoDiscover_{safe_city}_{job.coverage}_{stamp}.xlsx"
    else:
        file_name = f"GeoDiscover_Coverage_Comparison_{project.id}_{stamp}.xlsx"
    return buffer.getvalue(), file_name, kpis


def _append_match_row(sheet, match: PoiMatch, places: dict[int, ProviderPlace]) -> None:
    grab = places.get(match.grab_place_id)
    google = places.get(match.google_place_id)
    contributions = (match.signals or {}).get("contributions", {})
    breakdown = ", ".join(f"{k}={v}" for k, v in contributions.items())
    sheet.append([
        match.score, match.distance_m, match.method.value, match.reviewer,
        grab.provider_place_id if grab else None, grab.name if grab else None,
        grab.address if grab else None, grab.city if grab else None,
        grab.lat if grab else None, grab.lng if grab else None,
        google.provider_place_id if google else None, google.name if google else None,
        google.address if google else None, google.city if google else None,
        google.lat if google else None, google.lng if google else None,
        google.phone_e164 if google else None, google.website if google else None,
        breakdown,
    ])


def _method_notes(kpis: dict, runs: list[DiscoveryRun]) -> list[str]:
    google_calls = sum(r.api_calls for r in runs if r.provider == Provider.GOOGLE)
    grab_calls = sum(r.api_calls for r in runs if r.provider == Provider.GRAB)
    saturated = sum(r.saturated_tiles for r in runs)
    aborted = [r.id for r in runs if r.status.value == "ABORTED_BUDGET"]
    return [
        "Method and limitations",
        "",
        "How uniqueness was established",
        "  Uniqueness is never inferred by subtracting the matched set from a sweep. Every row in the",
        "  'Grab Only' and 'Google Only' sheets carries the evidence behind it, in one of two tiers shown",
        "  in the Evidence Method column:",
        "",
        "    PROBE (strong). A targeted text search was run against the other provider using this business's",
        "    own name, address and coordinates, and it returned nothing matching. Text search applies no",
        "    category filter, so this rules out both a coverage gap and a category mismatch.",
        "",
        "    AREA_COVERAGE (moderate). No live lookup was made. The other provider's own sweep returned",
        "    several other places within 300 m of this location and none of them matched, which shows it",
        "    covered this spot and does not list this business. Because the sweep filters on category",
        "    categories, this cannot rule out the other provider holding the business under a different",
        "    category. Treat these as strong leads rather than confirmed gaps, and re-verify with a probe",
        "    before making a contractual claim about them.",
        "",
        "  The two tiers are counted separately in the summary and are never added into a single figure.",
        "",
        "Known asymmetry between the two APIs",
        "  Google Places supports a category search over a radius (searchNearby with place types).",
        "  GrabMaps through Amazon Location Service does not offer a nearby search at all: discovery there uses",
        "  text search over a matrix of Indonesian search terms. The two sweeps therefore have different",
        "  recall characteristics. The reciprocal probe stage exists to absorb that difference, but residual",
        "  recall bias cannot be fully excluded and is the main reason to treat small gaps with caution.",
        "",
        "Contact data",
        "  GrabMaps in ap-southeast-1 and ap-southeast-5 does not return phone numbers or websites, so Grab",
        "  records in this report have no contact channel and phone/website could not be used as matching",
        "  evidence. Matching rests on geometry, business name and address only.",
        "",
        "Result truncation",
        f"  Google nearby search returns at most 20 results per call with no pagination. {saturated} tile(s) hit a",
        "  provider result ceiling and were subdivided into smaller circles and re-swept. Tiles still saturated",
        "  at the minimum radius are counted here and may under-report dense blocks.",
        "",
        "Run coverage",
        f"  Google API calls: {google_calls}. Grab API calls: {grab_calls}.",
        f"  Runs stopped at their budget cap: {aborted or 'none'}.",
        "  A run that stopped at its cap did not cover its full area; its figures are a floor, not a total.",
        "",
        "Unresolved records",
        f"  Grab: {kpis.get('U_grab_unresolved')}. Google: {kpis.get('U_google_unresolved')}.",
        "  These are records we could not confidently classify. They are excluded from the unique counts",
        "  rather than assumed either way.",
        "",
        "Invariant checks",
        f"  Grab set partitions cleanly: {kpis.get('invariant_grab_partition')}",
        f"  Google set partitions cleanly: {kpis.get('invariant_google_partition')}",
        f"  Every unique record has probe evidence: {kpis.get('invariant_unique_has_probe_evidence')}",
        "  If any of the above is FALSE, this report is not fit to issue.",
        "",
        "Third-party data terms",
        "  Google Maps Platform terms restrict retention and redistribution of Places content. Google-derived",
        "  rows in this workbook are comparison evidence, not a licensed deliverable dataset. Confirm the",
        "  permitted use with your Google and Grab agreements before sharing this file externally.",
    ]


def build_comparison_geojson(db: Session, project: Project, job_id: int | None = None) -> dict:
    query = select(ProviderPlace).where(ProviderPlace.project_id == project.id, ProviderPlace.in_scope.is_(True))
    if job_id is not None:
        query = query.where(ProviderPlace.job_id == job_id)
    features = []
    for place in db.scalars(query).all():
        if place.lat is None or place.lng is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [place.lng, place.lat]},
            "properties": {
                "provider": place.provider.value,
                "provider_place_id": place.provider_place_id,
                "name": place.name,
                "city": place.city,
                "address": place.address,
                "verdict": place.verdict.value if place.verdict else UniquenessVerdict.UNRESOLVED.value,
                "bucket": _bucket_label(place),
                "found_by_probe": place.discovered_by_probe,
            },
        })
    return {"type": "FeatureCollection", "features": features}


def _bucket_label(place: ProviderPlace) -> str:
    if place.verdict == UniquenessVerdict.MATCHED:
        return "BOTH"
    if place.verdict == UniquenessVerdict.UNIQUE_VERIFIED:
        return "GRAB_ONLY" if place.provider == Provider.GRAB else "GOOGLE_ONLY"
    if place.verdict == UniquenessVerdict.POSSIBLE_MATCH:
        return "POSSIBLE"
    return "UNRESOLVED"


def matched_pair_distance(grab: ProviderPlace, google: ProviderPlace) -> float | None:
    if None in (grab.lat, grab.lng, google.lat, google.lng):
        return None
    return haversine_m(grab.lat, grab.lng, google.lat, google.lng)
