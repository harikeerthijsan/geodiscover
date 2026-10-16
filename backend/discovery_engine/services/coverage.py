"""Free uniqueness resolution from data already downloaded.

The probe stage proves absence by asking the other provider directly, which costs an
API call per record. But for many records the answer is already sitting in the data:
if the other provider returned a dozen other places within 300 m of this one and none
of them match it, that provider clearly swept this spot and does not list this
business. No call needed.

This is genuinely weaker evidence than a probe, and is reported as its own tier:

    PROBE          a text search with no category filter. Rules out both a coverage
                   gap and a category-taxonomy mismatch.
    AREA_COVERAGE  derived from the sweep. Rules out a coverage gap only. If the
                   other provider holds the business but files it under a category
                   outside the requested category scope, this method cannot see that.

Running this before the probe stage means the paid budget is spent only on records
that genuinely need a live lookup.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Project,
    Provider,
    ProviderPlace,
    UniquenessProbe,
    UniquenessVerdict,
)
from .geo import geocell, haversine_m, neighbour_cells
from .matching import decide, score_pair

# A spot counts as swept by the other provider when it returned at least this many
# places within this radius. Three is deliberately conservative: one or two nearby
# places could be spillover from an adjacent tile rather than proof of local coverage.
MIN_NEIGHBOURS = 3
NEIGHBOUR_RADIUS_M = 300.0
BLOCK_M = 300.0

EVIDENCE_AREA = "AREA_COVERAGE"
EVIDENCE_PROBE = "PROBE"


def _index(places: list[ProviderPlace]) -> dict[tuple[int, int], list[ProviderPlace]]:
    blocks: dict[tuple[int, int], list[ProviderPlace]] = {}
    for place in places:
        if place.lat is None or place.lng is None:
            continue
        blocks.setdefault(geocell(place.lat, place.lng, BLOCK_M), []).append(place)
    return blocks


def _neighbours(blocks, place: ProviderPlace, radius_m: float) -> list[ProviderPlace]:
    found = []
    for cell in neighbour_cells(geocell(place.lat, place.lng, BLOCK_M)):
        for other in blocks.get(cell, []):
            if haversine_m(place.lat, place.lng, other.lat, other.lng) <= radius_m:
                found.append(other)
    return found


def resolve_by_area_coverage(
    db: Session,
    project: Project,
    job_id: int | None = None,
    min_neighbours: int = MIN_NEIGHBOURS,
    radius_m: float = NEIGHBOUR_RADIUS_M,
) -> dict:
    """Resolve unresolved records from stored data alone. Makes no API calls."""
    auto = float(project.match_auto_threshold or 85)
    possible = float(project.match_possible_threshold or 60)

    query = select(ProviderPlace).where(
        ProviderPlace.project_id == project.id, ProviderPlace.in_scope.is_(True)
    )
    if job_id is not None:
        query = query.where(ProviderPlace.job_id == job_id)
    places = list(db.scalars(query).all())

    by_provider = {
        Provider.GRAB: [p for p in places if p.provider == Provider.GRAB],
        Provider.GOOGLE: [p for p in places if p.provider == Provider.GOOGLE],
    }
    blocks = {provider: _index(rows) for provider, rows in by_provider.items()}

    already_evidenced = {
        row[0] for row in db.execute(
            select(UniquenessProbe.provider_place_id).where(UniquenessProbe.project_id == project.id)
        ).all()
    }

    summary = {"examined": 0, "resolved_unique": 0, "still_unresolved_no_coverage": 0, "matched": 0}

    for provider, rows in by_provider.items():
        opposite = Provider.GOOGLE if provider == Provider.GRAB else Provider.GRAB
        opposite_blocks = blocks[opposite]

        for place in rows:
            if place.verdict != UniquenessVerdict.UNRESOLVED or place.id in already_evidenced:
                continue
            if place.lat is None or place.lng is None:
                continue
            summary["examined"] += 1

            nearby = _neighbours(opposite_blocks, place, radius_m)
            if len(nearby) < min_neighbours:
                # Too little of the other provider's data here to call this a sweep.
                summary["still_unresolved_no_coverage"] += 1
                continue

            best = None
            for candidate in nearby:
                left, right = (place, candidate) if provider == Provider.GRAB else (candidate, place)
                signals = score_pair(left, right)
                if best is None or signals.score > best.score:
                    best = signals

            if best is not None and decide(best, auto, possible) != "NO_MATCH":
                # Bulk matching should already have caught this; leave it alone.
                summary["matched"] += 1
                continue

            db.add(UniquenessProbe(
                project_id=project.id,
                provider_place_id=place.id,
                probed_provider=opposite,
                queries=[{
                    "method": EVIDENCE_AREA,
                    "neighbours_within_m": radius_m,
                    "neighbour_count": len(nearby),
                    "best_local_score": best.score if best else None,
                }],
                result_count=len(nearby),
                best_score=best.score if best else None,
                verdict=UniquenessVerdict.UNIQUE_VERIFIED,
                evidence_method=EVIDENCE_AREA,
                reason=(
                    f"{opposite.value} returned {len(nearby)} other places within "
                    f"{int(radius_m)} m of this location and none matched it "
                    f"(best local score {best.score if best else 0}). The area was swept; "
                    "the business is absent from that provider's listings. This does "
                    "not rule out the business being present under a different category."
                ),
            ))
            place.verdict = UniquenessVerdict.UNIQUE_VERIFIED
            summary["resolved_unique"] += 1

    db.flush()
    return summary
