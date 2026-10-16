"""Resolve HERE, Google and Grab records into one set of real-world places.

The two-provider engine answers "is this Grab place in Google?". Three providers
change the question into "which of the three maps knows about this place?", which
needs clustering rather than pairing.

Method, and why:

  1. Score all three provider pairs with the existing pairwise matcher, so every
     merge keeps the same explainable signal breakdown the two-way report shows.
  2. Sort every MATCHED edge by score, descending, and union greedily.
  3. Refuse any union that would put two records from the *same* provider into one
     cluster. This is the rule that keeps transitive drift out: A(here)~B(google)
     and B(google)~C(here) would otherwise silently merge two distinct HERE places
     into one, deleting a record from the comparison. The weaker edge is dropped and
     recorded as contested instead.

A cluster of one is not a failure — it is the finding. The whole deliverable is
which places sit in only one or two of the three maps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ..models import PresenceBucket, Provider
from .matching import candidate_pairs, decide, score_pair
from .taxonomy import UnifiedCategory

#: Which provider's record to trust for the cluster's display identity. Google
#: first because it is the only one of the three that returns phone and website in
#: this region; Grab last because it returns neither.
IDENTITY_PRIORITY = [Provider.GOOGLE, Provider.HERE, Provider.GRAB]

#: (providers present) -> bucket. Frozensets so lookup is order-independent.
_BUCKET_BY_PRESENCE: dict[frozenset[Provider], PresenceBucket] = {
    frozenset({Provider.HERE, Provider.GOOGLE, Provider.GRAB}): PresenceBucket.ALL_THREE,
    frozenset({Provider.HERE, Provider.GOOGLE}): PresenceBucket.HERE_GOOGLE,
    frozenset({Provider.HERE, Provider.GRAB}): PresenceBucket.HERE_GRAB,
    frozenset({Provider.GOOGLE, Provider.GRAB}): PresenceBucket.GOOGLE_GRAB,
    frozenset({Provider.HERE}): PresenceBucket.HERE_ONLY,
    frozenset({Provider.GOOGLE}): PresenceBucket.GOOGLE_ONLY,
    frozenset({Provider.GRAB}): PresenceBucket.GRAB_ONLY,
}


@dataclass
class Cluster:
    """One resolved real-world place and the provider records that evidence it."""

    members: dict[Provider, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    max_pair_distance_m: float | None = None

    @property
    def bucket(self) -> PresenceBucket:
        return _BUCKET_BY_PRESENCE[frozenset(self.members.keys())]

    @property
    def identity(self):
        for provider in IDENTITY_PRIORITY:
            if provider in self.members:
                return self.members[provider]
        return None

    @property
    def unified_category(self) -> str:
        """First non-OTHER classification, in identity-priority order.

        Falling back through the providers matters because Grab's free-text
        categories are often absent entirely, and an absent category would
        otherwise dump a well-classified Google record into OTHER.
        """
        fallback = UnifiedCategory.OTHER.value
        for provider in IDENTITY_PRIORITY:
            place = self.members.get(provider)
            if place is None:
                continue
            value = getattr(place, "unified_category", None)
            if value and value != UnifiedCategory.OTHER.value:
                return value
            if value:
                fallback = value
        return fallback


class _DisjointSet:
    """Union-find with a per-provider occupancy guard on each set."""

    def __init__(self) -> None:
        self.parent: dict[int, int] = {}
        self.providers: dict[int, set[Provider]] = {}

    def add(self, key: int, provider: Provider) -> None:
        if key not in self.parent:
            self.parent[key] = key
            self.providers[key] = {provider}

    def find(self, key: int) -> int:
        root = key
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[key] != root:  # path compression
            self.parent[key], key = root, self.parent[key]
        return root

    def can_union(self, left: int, right: int) -> bool:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return False
        # The guard: no cluster may hold two records from the same provider.
        return not (self.providers[left_root] & self.providers[right_root])

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        self.parent[right_root] = left_root
        self.providers[left_root] |= self.providers[right_root]


def _pair_key(left: Provider, right: Provider) -> str:
    return "|".join(sorted([left.value, right.value]))


def build_clusters(
    places_by_provider: dict[Provider, list],
    auto_threshold: float = 85.0,
    possible_threshold: float = 60.0,
    max_distance_m: float = 300.0,
) -> tuple[list[Cluster], list[dict[str, Any]]]:
    """Cluster provider records into real-world places.

    Returns (clusters, contested) where `contested` holds edges that scored as a
    match but were refused by the same-provider guard. Those are surfaced rather
    than dropped, because a contested edge usually means two genuinely adjacent
    businesses or a duplicate inside one provider's own index — both worth seeing.
    """
    index: dict[int, Any] = {}
    provider_of: dict[int, Provider] = {}
    disjoint = _DisjointSet()

    for provider, places in places_by_provider.items():
        for place in places:
            key = id(place)
            index[key] = place
            provider_of[key] = provider
            disjoint.add(key, provider)

    # --- score every provider pair -----------------------------------------
    edges: list[tuple[float, int, int, Any]] = []
    providers_present = [p for p in IDENTITY_PRIORITY if places_by_provider.get(p)]
    for i, left_provider in enumerate(providers_present):
        for right_provider in providers_present[i + 1:]:
            left_places = places_by_provider[left_provider]
            right_places = places_by_provider[right_provider]
            for left, right in candidate_pairs(left_places, right_places):
                signals = score_pair(left, right, max_distance_m=max_distance_m)
                if decide(signals, auto_threshold, possible_threshold) != "MATCHED":
                    continue
                edges.append((signals.score, id(left), id(right), signals))

    # --- greedy union, strongest edge first ---------------------------------
    edges.sort(key=lambda row: row[0], reverse=True)
    accepted: list[tuple[int, int, Any]] = []
    contested: list[dict[str, Any]] = []
    for score, left_key, right_key, signals in edges:
        if disjoint.find(left_key) == disjoint.find(right_key):
            continue  # already the same place via a stronger path
        if not disjoint.can_union(left_key, right_key):
            contested.append({
                "score": score,
                "distance_m": signals.distance_m,
                "left_provider": provider_of[left_key].value,
                "right_provider": provider_of[right_key].value,
                "left_name": index[left_key].name,
                "right_name": index[right_key].name,
                "reason": (
                    "Refused: merging would put two records from the same provider in "
                    "one cluster. Kept separate so neither record disappears."
                ),
            })
            continue
        disjoint.union(left_key, right_key)
        accepted.append((left_key, right_key, signals))

    # --- materialise clusters ----------------------------------------------
    grouped: dict[int, Cluster] = {}
    for key, place in index.items():
        cluster = grouped.setdefault(disjoint.find(key), Cluster())
        cluster.members[provider_of[key]] = place

    for left_key, right_key, signals in accepted:
        cluster = grouped[disjoint.find(left_key)]
        pair = _pair_key(provider_of[left_key], provider_of[right_key])
        cluster.evidence[pair] = {
            "score": signals.score,
            "distance_m": signals.distance_m,
            "signals": signals.signals,
        }
        if signals.distance_m is not None:
            current = cluster.max_pair_distance_m
            cluster.max_pair_distance_m = max(current or 0.0, signals.distance_m)

    return list(grouped.values()), contested


def summarise_buckets(clusters: Iterable[Cluster]) -> dict[str, int]:
    """Cluster counts keyed by PresenceBucket value, with every bucket present.

    Zero-filled on purpose: a missing key in the interface reads as "not measured",
    while an explicit 0 reads as "measured, found none".
    """
    counts = {bucket.value: 0 for bucket in PresenceBucket}
    for cluster in clusters:
        counts[cluster.bucket.value] += 1
    return counts


def summarise_categories(clusters: Iterable[Cluster]) -> dict[str, dict[str, int]]:
    """{unified_category: {provider or bucket: count}} for the breakdown table."""
    matrix: dict[str, dict[str, int]] = {}
    for cluster in clusters:
        row = matrix.setdefault(cluster.unified_category, {
            "HERE": 0, "GOOGLE": 0, "GRAB": 0, "clusters": 0, "all_three": 0, "single_provider": 0,
        })
        row["clusters"] += 1
        for provider in cluster.members:
            row[provider.value] += 1
        if len(cluster.members) == 3:
            row["all_three"] += 1
        elif len(cluster.members) == 1:
            row["single_provider"] += 1
    return matrix
