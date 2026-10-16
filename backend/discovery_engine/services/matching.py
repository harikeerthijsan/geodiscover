"""Deterministic, explainable record matching between two providers.

Every decision carries its full signal breakdown so the report can show *why* two
records were judged the same business. No ML in the MVP: an unexplainable merge is
worse than an unmatched pair, because a false merge silently deletes a coverage gap
from the exact deliverable the customer is paying for.

Note on contact signals: GrabMaps via Amazon Location Service cannot return phone
numbers or websites in ap-southeast-1/5, so Grab<->Google pairs score on geometry,
name and address only. The weights below are renormalised over whichever signals are
actually present, so absent contact data weakens the evidence rather than penalising
the pair. `signal_count` records how much evidence a score was built from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable

from .geo import geocell, haversine_m, neighbour_cells
from .normalization import match_name, normalize_text

# Raw weights. Renormalised across available signals at scoring time.
WEIGHTS = {"geo": 30.0, "name": 35.0, "phone": 20.0, "web": 10.0, "addr": 5.0}

GEO_FULL_CREDIT_M = 25.0     # at or below this, geometry is perfect evidence
GEO_ZERO_CREDIT_M = 200.0    # beyond this, geometry contributes nothing
PHONE_MATCH_MAX_DIST_M = 500.0
BLOCKING_CELL_M = 150.0


@dataclass
class MatchSignals:
    score: float = 0.0
    distance_m: float | None = None
    signals: dict[str, Any] = field(default_factory=dict)
    signal_count: int = 0
    blocked_reason: str | None = None
    forced: str | None = None


def _geo_signal(distance_m: float) -> float:
    if distance_m <= GEO_FULL_CREDIT_M:
        return 1.0
    if distance_m >= GEO_ZERO_CREDIT_M:
        return 0.0
    span = GEO_ZERO_CREDIT_M - GEO_FULL_CREDIT_M
    return 1.0 - (distance_m - GEO_FULL_CREDIT_M) / span


def _name_signal(left: str, right: str) -> float:
    """Max of token-set Jaccard and sequence similarity on generic-stripped names."""
    if not left or not right:
        return 0.0
    lt, rt = set(left.split()), set(right.split())
    jaccard = len(lt & rt) / len(lt | rt) if lt | rt else 0.0
    sequence = SequenceMatcher(None, left, right).ratio()
    return max(jaccard, sequence)


def _address_signal(left: str | None, right: str | None) -> float | None:
    if not left or not right:
        return None
    lt = set(normalize_text(left).split())
    rt = set(normalize_text(right).split())
    if not lt or not rt:
        return None
    overlap = len(lt & rt) / min(len(lt), len(rt))
    # A shared house number is worth more than a shared street word.
    l_nums = {t for t in lt if t.isdigit()}
    r_nums = {t for t in rt if t.isdigit()}
    if l_nums and r_nums:
        overlap = min(1.0, overlap + (0.3 if l_nums & r_nums else -0.2))
    return max(0.0, min(1.0, overlap))


def score_pair(left, right, max_distance_m: float = 300.0) -> MatchSignals:
    """Score one candidate pair. `left` and `right` are provider place records."""
    result = MatchSignals()

    if left.lat is None or left.lng is None or right.lat is None or right.lng is None:
        result.blocked_reason = "Missing coordinates on one or both records"
        return result

    distance = haversine_m(left.lat, left.lng, right.lat, right.lng)
    result.distance_m = round(distance, 1)

    left_name = getattr(left, "match_name", "") or match_name(left.name)
    right_name = getattr(right, "match_name", "") or match_name(right.name)

    contributions: dict[str, float] = {"geo": _geo_signal(distance)}

    # A name that reduces to generic trade words carries no evidence either way, so it
    # is renormalised out rather than scored zero. Scoring it zero would penalise the
    # pair for missing data and push two adjacent "Salon Kecantikan" records to
    # NO_MATCH — which would then let the probe stage report each as unique to its own
    # provider, inventing a coverage gap on both sides. The CAP_POSSIBLE rule below
    # keeps these pairs out of auto-match and in front of a human instead.
    names_comparable = bool(left_name and right_name)
    if names_comparable:
        contributions["name"] = _name_signal(left_name, right_name)

    left_phone = getattr(left, "phone_e164", None)
    right_phone = getattr(right, "phone_e164", None)
    phone_conflict = False
    if left_phone and right_phone:
        if left_phone == right_phone:
            contributions["phone"] = 1.0
        else:
            contributions["phone"] = 0.0
            phone_conflict = True

    left_web = getattr(left, "website_domain", None)
    right_web = getattr(right, "website_domain", None)
    if left_web and right_web:
        contributions["web"] = 1.0 if left_web == right_web else 0.0

    address_signal = _address_signal(left.address, right.address)
    if address_signal is not None:
        contributions["addr"] = address_signal

    # Renormalise weights over the signals we actually have.
    total_weight = sum(WEIGHTS[k] for k in contributions)
    score = sum(WEIGHTS[k] * v for k, v in contributions.items()) / total_weight * 100 if total_weight else 0.0

    result.score = round(score, 2)
    result.signal_count = len(contributions)
    result.signals = {
        "distance_m": result.distance_m,
        "contributions": {k: round(v, 3) for k, v in contributions.items()},
        "weights_used": {k: WEIGHTS[k] for k in contributions},
        "left_match_name": left_name,
        "right_match_name": right_name,
        "phone_conflict": phone_conflict,
        "generic_only_name": not names_comparable,
    }

    # --- hard rules, applied after scoring ---
    if distance > max_distance_m:
        result.forced = "NO_MATCH"
        result.signals["rule"] = f"Distance {result.distance_m}m exceeds {max_distance_m}m limit"
    elif left_phone and right_phone and left_phone == right_phone and distance <= PHONE_MATCH_MAX_DIST_M:
        result.forced = "MATCHED"
        result.signals["rule"] = "Exact phone match within 500m"
    elif phone_conflict:
        result.forced = "CAP_POSSIBLE"
        result.signals["rule"] = "Both records have phones and they differ"
    elif not names_comparable:
        # Names reduced to nothing but generic trade words ("Salon Kecantikan").
        result.forced = "CAP_POSSIBLE"
        result.signals["rule"] = "No distinguishing name tokens; cannot auto-match on geometry alone"

    return result


def decide(signals: MatchSignals, auto_threshold: float, possible_threshold: float) -> str:
    """Map a scored pair onto MATCHED / POSSIBLE_MATCH / NO_MATCH."""
    if signals.blocked_reason:
        return "NO_MATCH"
    if signals.forced == "NO_MATCH":
        return "NO_MATCH"
    if signals.forced == "MATCHED":
        return "MATCHED"
    if signals.score >= auto_threshold:
        return "POSSIBLE_MATCH" if signals.forced == "CAP_POSSIBLE" else "MATCHED"
    if signals.score >= possible_threshold:
        return "POSSIBLE_MATCH"
    return "NO_MATCH"


def build_blocks(places: Iterable) -> dict[tuple[int, int], list]:
    """Index places by geocell so scoring is local rather than O(n^2)."""
    blocks: dict[tuple[int, int], list] = {}
    for place in places:
        if place.lat is None or place.lng is None:
            continue
        blocks.setdefault(geocell(place.lat, place.lng, BLOCKING_CELL_M), []).append(place)
    return blocks


def candidate_pairs(left_places: Iterable, right_places: Iterable):
    """Yield (left, right) pairs that are close enough to be worth scoring."""
    blocks = build_blocks(right_places)
    for left in left_places:
        if left.lat is None or left.lng is None:
            continue
        seen: set[int] = set()
        for cell in neighbour_cells(geocell(left.lat, left.lng, BLOCKING_CELL_M)):
            for right in blocks.get(cell, []):
                if id(right) in seen:
                    continue
                seen.add(id(right))
                yield left, right


def resolve_one_to_one(scored: list[tuple[Any, Any, MatchSignals, str]]):
    """Greedy highest-score-first assignment.

    One Grab place may bind to at most one Google place. Runner-up pairs are demoted
    to POSSIBLE_MATCH rather than dropped, so contention stays visible in the review
    queue instead of silently resolving in favour of whichever row was scored first.
    """
    ordered = sorted(scored, key=lambda row: row[2].score, reverse=True)
    taken_left: set[int] = set()
    taken_right: set[int] = set()
    resolved: list[tuple[Any, Any, MatchSignals, str]] = []
    for left, right, signals, decision in ordered:
        if decision == "MATCHED" and (id(left) in taken_left or id(right) in taken_right):
            signals.signals["rule"] = "Demoted: a higher-scoring pair already claimed one of these records"
            resolved.append((left, right, signals, "POSSIBLE_MATCH"))
            continue
        if decision == "MATCHED":
            taken_left.add(id(left))
            taken_right.add(id(right))
        resolved.append((left, right, signals, decision))
    return resolved
