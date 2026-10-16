"""Bulk matching and the reciprocal probe that proves uniqueness.

The probe is the heart of the product. Sweeping both providers and subtracting the
matched set would label every sweep miss as a coverage gap — and the two APIs have
structurally different recall (Google has a category radius search, GrabMaps only has
text search), so those misses are not rare. Instead, every unmatched record gets a
targeted lookup in the opposite provider using its own name, address and coordinates.
Only an empty or clearly-irrelevant probe result promotes a record to UNIQUE_VERIFIED.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    MatchDecision,
    MatchMethod,
    PoiMatch,
    Project,
    Provider,
    ProviderPlace,
    UniquenessProbe,
    UniquenessVerdict,
    utcnow,
)
from ..providers import ProviderAdapter, ProviderError
from .matching import candidate_pairs, decide, resolve_one_to_one, score_pair
from .sweep import upsert_place


def _thresholds(project: Project) -> tuple[float, float, float]:
    from ..config import get_settings

    settings = get_settings()
    return (
        float(project.match_auto_threshold or settings.match_auto_threshold),
        float(project.match_possible_threshold or settings.match_possible_threshold),
        settings.match_max_distance_m,
    )


def in_scope_places(db: Session, project_id: int, provider: Provider) -> list[ProviderPlace]:
    return list(
        db.scalars(
            select(ProviderPlace).where(
                ProviderPlace.project_id == project_id,
                ProviderPlace.provider == provider,
                ProviderPlace.in_scope.is_(True),
            )
        ).all()
    )


def run_bulk_match(db: Session, project: Project) -> dict:
    """Score every plausible Grab<->Google pair and persist the decisions."""
    auto, possible, max_distance = _thresholds(project)
    grab_places = in_scope_places(db, project.id, Provider.GRAB)
    google_places = in_scope_places(db, project.id, Provider.GOOGLE)

    scored = []
    for left, right in candidate_pairs(grab_places, google_places):
        signals = score_pair(left, right, max_distance_m=max_distance)
        decision = decide(signals, auto, possible)
        if decision == "NO_MATCH":
            continue
        scored.append((left, right, signals, decision))

    resolved = resolve_one_to_one(scored)

    counts = {"MATCHED": 0, "POSSIBLE_MATCH": 0}
    for left, right, signals, decision in resolved:
        existing = db.scalar(
            select(PoiMatch).where(PoiMatch.grab_place_id == left.id, PoiMatch.google_place_id == right.id)
        )
        if existing and existing.method == MatchMethod.MANUAL:
            continue  # never overwrite a human adjudication
        row = existing or PoiMatch(project_id=project.id, grab_place_id=left.id, google_place_id=right.id)
        row.score = signals.score
        row.distance_m = signals.distance_m
        row.signals = signals.signals
        row.decision = MatchDecision(decision)
        row.method = MatchMethod.AUTO_SWEEP
        if not existing:
            db.add(row)
        counts[decision] = counts.get(decision, 0) + 1

    db.flush()
    apply_verdicts(db, project.id)
    return {
        "grab_places": len(grab_places),
        "google_places": len(google_places),
        "pairs_scored": len(scored),
        "matched": counts.get("MATCHED", 0),
        "possible": counts.get("POSSIBLE_MATCH", 0),
    }


def _matched_place_ids(db: Session, project_id: int) -> tuple[set[int], set[int]]:
    rows = db.execute(
        select(PoiMatch.grab_place_id, PoiMatch.google_place_id).where(
            PoiMatch.project_id == project_id, PoiMatch.decision == MatchDecision.MATCHED
        )
    ).all()
    return {r[0] for r in rows}, {r[1] for r in rows}


def unprobed_places(db: Session, project_id: int, provider: Provider) -> list[ProviderPlace]:
    """In-scope places that have no confirmed match and no probe evidence yet."""
    grab_matched, google_matched = _matched_place_ids(db, project_id)
    matched = grab_matched if provider == Provider.GRAB else google_matched
    probed = {
        row[0]
        for row in db.execute(
            select(UniquenessProbe.provider_place_id).where(UniquenessProbe.project_id == project_id)
        ).all()
    }
    return [p for p in in_scope_places(db, project_id, provider) if p.id not in matched and p.id not in probed]


def probe_place(
    db: Session,
    project: Project,
    place: ProviderPlace,
    adapter: ProviderAdapter,
    opposite: Provider,
    job_id: int | None = None,
) -> UniquenessProbe:
    """Look for one place in the opposite provider and record the evidence."""
    auto, possible, max_distance = _thresholds(project)
    query = {"name": place.name, "address": place.address, "lat": place.lat, "lng": place.lng}

    try:
        result = adapter.probe(place.name, place.lat, place.lng, place.address)
    except ProviderError as exc:
        probe = UniquenessProbe(
            project_id=project.id,
            provider_place_id=place.id,
            probed_provider=opposite,
            queries=[query],
            result_count=0,
            verdict=UniquenessVerdict.UNRESOLVED,
            reason=f"Probe failed: {exc}"[:1000],
        )
        db.add(probe)
        place.verdict = UniquenessVerdict.UNRESOLVED
        db.flush()
        return probe

    best_score = None
    best_place = None
    best_signals = None
    for dto in result.places:
        if not dto.provider_place_id:
            continue
        candidate, created = upsert_place(db, project.id, None, dto, job_id=job_id)
        if created:
            candidate.discovered_by_probe = True
        db.flush()
        signals = score_pair(place, candidate, max_distance_m=max_distance) if place.provider == Provider.GRAB \
            else score_pair(candidate, place, max_distance_m=max_distance)
        if best_score is None or signals.score > best_score:
            best_score, best_place, best_signals = signals.score, candidate, signals

    if best_score is None:
        verdict = UniquenessVerdict.UNIQUE_VERIFIED
        reason = "Targeted lookup in the opposite provider returned no results"
    else:
        decision = decide(best_signals, auto, possible)
        if decision == "MATCHED":
            verdict = UniquenessVerdict.MATCHED
            reason = f"Probe found a confirmed match at score {best_score}"
        elif decision == "POSSIBLE_MATCH":
            verdict = UniquenessVerdict.POSSIBLE_MATCH
            reason = f"Probe found an ambiguous candidate at score {best_score}; needs human review"
        else:
            verdict = UniquenessVerdict.UNIQUE_VERIFIED
            reason = f"Probe returned {len(result.places)} result(s), best score {best_score} is below the match threshold"

    if best_place is not None and verdict in (UniquenessVerdict.MATCHED, UniquenessVerdict.POSSIBLE_MATCH):
        grab_id = place.id if place.provider == Provider.GRAB else best_place.id
        google_id = best_place.id if place.provider == Provider.GRAB else place.id
        existing = db.scalar(select(PoiMatch).where(PoiMatch.grab_place_id == grab_id, PoiMatch.google_place_id == google_id))
        row = existing or PoiMatch(project_id=project.id, grab_place_id=grab_id, google_place_id=google_id)
        if not existing or row.method != MatchMethod.MANUAL:
            row.score = best_signals.score
            row.distance_m = best_signals.distance_m
            row.signals = best_signals.signals
            row.decision = MatchDecision.MATCHED if verdict == UniquenessVerdict.MATCHED else MatchDecision.POSSIBLE_MATCH
            row.method = MatchMethod.PROBE
        if not existing:
            db.add(row)

    probe = UniquenessProbe(
        project_id=project.id,
        provider_place_id=place.id,
        probed_provider=opposite,
        queries=[query],
        result_count=len(result.places),
        best_score=best_score,
        verdict=verdict,
        reason=reason,
    )
    db.add(probe)
    place.verdict = verdict
    db.flush()
    return probe


def apply_verdicts(db: Session, project_id: int) -> None:
    """Recompute the verdict on every in-scope place from matches and probe evidence.

    Precedence, strongest first:
      1. a confirmed match           -> MATCHED
      2. stored uniqueness evidence  -> whatever that evidence concluded
      3. an unadjudicated possible   -> POSSIBLE_MATCH (a human has to decide)
      4. nothing                     -> UNRESOLVED, never "unique"
    """
    grab_matched, google_matched = _matched_place_ids(db, project_id)
    probes = {
        row.provider_place_id: row
        for row in db.scalars(
            select(UniquenessProbe).where(UniquenessProbe.project_id == project_id).order_by(UniquenessProbe.probed_at)
        ).all()
    }
    possible_rows = db.execute(
        select(PoiMatch.grab_place_id, PoiMatch.google_place_id).where(
            PoiMatch.project_id == project_id, PoiMatch.decision == MatchDecision.POSSIBLE_MATCH
        )
    ).all()
    grab_possible = {r[0] for r in possible_rows}
    google_possible = {r[1] for r in possible_rows}

    for provider, matched, possible in (
        (Provider.GRAB, grab_matched, grab_possible),
        (Provider.GOOGLE, google_matched, google_possible),
    ):
        for place in in_scope_places(db, project_id, provider):
            if place.id in matched:
                place.verdict = UniquenessVerdict.MATCHED
            elif place.id in probes:
                place.verdict = probes[place.id].verdict
            elif place.id in possible:
                # An ambiguous candidate exists in the other provider. Not unique,
                # not confirmed: it belongs in the human review queue.
                place.verdict = UniquenessVerdict.POSSIBLE_MATCH
            else:
                place.verdict = UniquenessVerdict.UNRESOLVED
    db.flush()
