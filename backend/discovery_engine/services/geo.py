"""Geometry helpers: distance, adaptive tile grids, and blocking cells.

Coordinate order is (lat, lng) everywhere in this codebase. The Amazon Location
Service geo-places API uses GeoJSON order [lng, lat]; that conversion is confined
to the Grab adapter.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class Tile:
    """A circular search area. `level` counts adaptive subdivisions from the root."""
    lat: float
    lng: float
    radius_m: float
    level: int = 0
    parent_key: str | None = None

    @property
    def key(self) -> str:
        return f"{self.lat:.6f},{self.lng:.6f},{self.radius_m:.0f}"

    def subdivide(self) -> list["Tile"]:
        """Split into four child circles that together cover this circle.

        Children sit at +/- r/2 on each axis with radius r/sqrt(2), which is the
        smallest radius that leaves no gap between the four quadrants.
        """
        child_radius = self.radius_m / math.sqrt(2)
        offset = self.radius_m / 2
        d_lat = offset / 111_320.0
        d_lng = offset / (111_320.0 * max(math.cos(math.radians(self.lat)), 1e-6))
        return [
            Tile(self.lat + sy * d_lat, self.lng + sx * d_lng, child_radius, self.level + 1, self.key)
            for sy in (-1, 1)
            for sx in (-1, 1)
        ]


def cover_circle_with_tiles(lat: float, lng: float, radius_m: float, tile_radius_m: float) -> list[Tile]:
    """Tile a circular area of interest with overlapping circles.

    Centres are laid on a square lattice with spacing tile_radius * sqrt(2), the
    largest spacing at which the circles still cover the plane with no gaps.
    """
    spacing = tile_radius_m * math.sqrt(2)
    steps = max(int(math.ceil(radius_m / spacing)), 0)
    d_lat = spacing / 111_320.0
    d_lng = spacing / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))

    tiles: list[Tile] = []
    for iy in range(-steps, steps + 1):
        for ix in range(-steps, steps + 1):
            t_lat = lat + iy * d_lat
            t_lng = lng + ix * d_lng
            # Keep tiles whose disc intersects the area of interest.
            if haversine_m(lat, lng, t_lat, t_lng) <= radius_m + tile_radius_m:
                tiles.append(Tile(t_lat, t_lng, tile_radius_m, 0))
    return tiles


def geocell(lat: float, lng: float, size_m: float = 150.0) -> tuple[int, int]:
    """Quantise a coordinate into a grid cell used for match blocking."""
    d_lat = size_m / 111_320.0
    d_lng = size_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return (int(math.floor(lat / d_lat)), int(math.floor(lng / d_lng)))


def neighbour_cells(cell: tuple[int, int]) -> list[tuple[int, int]]:
    """The cell itself plus its 8 neighbours, so pairs straddling a boundary still meet."""
    y, x = cell
    return [(y + dy, x + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
