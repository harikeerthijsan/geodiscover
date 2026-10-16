"""Indonesian province and city catalogue for area selection.

Coordinates are approximate city centroids and the radii are approximations of the
built-up area, chosen so a sweep covers the commercially relevant part of a city
rather than its full administrative boundary (which for a regency can be mostly
farmland and would burn API calls on empty tiles).

- ``core_radius_m``  the dense central commercial area. Cheap, good for a pilot.
- ``full_radius_m``  the urban extent. Substantially more expensive; check the
  estimate before running one.

Tune these for any city you work in regularly — they are starting points, not survey
data.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    code: str
    name: str
    province: str
    lat: float
    lng: float
    core_radius_m: int
    full_radius_m: int


CITIES: list[City] = [
    # --- Sumatra ---
    City("banda-aceh", "Banda Aceh", "Aceh", 5.5483, 95.3238, 2000, 7000),
    City("medan", "Medan", "Sumatera Utara", 3.5952, 98.6722, 3500, 14000),
    City("padang", "Padang", "Sumatera Barat", -0.9471, 100.4172, 2500, 9000),
    City("pekanbaru", "Pekanbaru", "Riau", 0.5071, 101.4478, 2500, 10000),
    City("batam", "Batam", "Kepulauan Riau", 1.0456, 104.0305, 2500, 12000),
    City("tanjungpinang", "Tanjungpinang", "Kepulauan Riau", 0.9186, 104.4665, 1800, 6000),
    City("jambi", "Jambi", "Jambi", -1.6101, 103.6131, 2500, 9000),
    City("palembang", "Palembang", "Sumatera Selatan", -2.9761, 104.7754, 3000, 12000),
    City("pangkalpinang", "Pangkalpinang", "Kepulauan Bangka Belitung", -2.1316, 106.1169, 1800, 6000),
    City("bengkulu", "Bengkulu", "Bengkulu", -3.7928, 102.2608, 2000, 7000),
    City("bandar-lampung", "Bandar Lampung", "Lampung", -5.3971, 105.2668, 2500, 10000),

    # --- Java ---
    City("jakarta", "Jakarta", "DKI Jakarta", -6.2088, 106.8456, 4000, 16000),
    City("bandung", "Bandung", "Jawa Barat", -6.9175, 107.6191, 3500, 11000),
    City("bekasi", "Bekasi", "Jawa Barat", -6.2383, 106.9756, 3000, 11000),
    City("bogor", "Bogor", "Jawa Barat", -6.5950, 106.8166, 2500, 8000),
    City("depok", "Depok", "Jawa Barat", -6.4025, 106.7942, 2500, 9000),
    City("cirebon", "Cirebon", "Jawa Barat", -6.7320, 108.5523, 2000, 7000),
    City("serang", "Serang", "Banten", -6.1200, 106.1503, 2000, 7000),
    City("tangerang", "Tangerang", "Banten", -6.1783, 106.6319, 3000, 10000),
    City("tangerang-selatan", "Tangerang Selatan", "Banten", -6.2889, 106.7181, 2800, 9000),
    City("semarang", "Semarang", "Jawa Tengah", -6.9667, 110.4167, 3000, 11000),
    City("surakarta", "Surakarta (Solo)", "Jawa Tengah", -7.5755, 110.8243, 2200, 7000),
    City("yogyakarta", "Yogyakarta", "DI Yogyakarta", -7.7956, 110.3695, 2500, 8000),
    City("surabaya", "Surabaya", "Jawa Timur", -7.2575, 112.7521, 3500, 13000),
    City("malang", "Malang", "Jawa Timur", -7.9666, 112.6326, 2500, 8000),

    # --- Bali and Nusa Tenggara ---
    City("denpasar", "Denpasar", "Bali", -8.6500, 115.2167, 3000, 10000),
    City("mataram", "Mataram", "Nusa Tenggara Barat", -8.5833, 116.1167, 2000, 7000),
    City("kupang", "Kupang", "Nusa Tenggara Timur", -10.1772, 123.6070, 2000, 7000),

    # --- Kalimantan ---
    City("pontianak", "Pontianak", "Kalimantan Barat", -0.0263, 109.3425, 2500, 8000),
    City("palangkaraya", "Palangka Raya", "Kalimantan Tengah", -2.2096, 113.9108, 1800, 7000),
    City("banjarmasin", "Banjarmasin", "Kalimantan Selatan", -3.3194, 114.5908, 2500, 8000),
    City("samarinda", "Samarinda", "Kalimantan Timur", -0.5017, 117.1536, 2500, 9000),
    City("balikpapan", "Balikpapan", "Kalimantan Timur", -1.2379, 116.8529, 2500, 9000),
    City("tanjung-selor", "Tanjung Selor", "Kalimantan Utara", 2.8375, 117.3661, 1500, 5000),

    # --- Sulawesi ---
    City("manado", "Manado", "Sulawesi Utara", 1.4748, 124.8421, 2200, 8000),
    City("gorontalo", "Gorontalo", "Gorontalo", 0.5435, 123.0568, 1800, 6000),
    City("palu", "Palu", "Sulawesi Tengah", -0.8917, 119.8707, 2000, 7000),
    City("mamuju", "Mamuju", "Sulawesi Barat", -2.6748, 118.8885, 1500, 5000),
    City("makassar", "Makassar", "Sulawesi Selatan", -5.1477, 119.4327, 3000, 11000),
    City("kendari", "Kendari", "Sulawesi Tenggara", -3.9985, 122.5130, 2000, 7000),

    # --- Maluku and Papua ---
    City("ambon", "Ambon", "Maluku", -3.6954, 128.1814, 1800, 6000),
    City("ternate", "Ternate", "Maluku Utara", 0.7900, 127.3800, 1500, 5000),
    City("sofifi", "Sofifi", "Maluku Utara", 0.7286, 127.5750, 1200, 4000),
    City("manokwari", "Manokwari", "Papua Barat", -0.8615, 134.0620, 1500, 5000),
    City("sorong", "Sorong", "Papua Barat Daya", -0.8762, 131.2558, 1800, 6000),
    City("jayapura", "Jayapura", "Papua", -2.5916, 140.6690, 1800, 6000),
    City("nabire", "Nabire", "Papua Tengah", -3.3667, 135.4833, 1200, 4000),
    City("wamena", "Wamena", "Papua Pegunungan", -4.0989, 138.9490, 1200, 4000),
    City("merauke", "Merauke", "Papua Selatan", -8.4932, 140.4018, 1500, 5000),
]

CITY_BY_CODE = {city.code: city for city in CITIES}


def provinces() -> list[dict]:
    """Provinces with their cities, ordered for a picker."""
    grouped: dict[str, list[City]] = {}
    for city in CITIES:
        grouped.setdefault(city.province, []).append(city)
    return [
        {
            "province": province,
            "cities": [
                {
                    "code": c.code,
                    "name": c.name,
                    "lat": c.lat,
                    "lng": c.lng,
                    "core_radius_m": c.core_radius_m,
                    "full_radius_m": c.full_radius_m,
                }
                for c in sorted(cities, key=lambda c: c.name)
            ],
        }
        for province, cities in sorted(grouped.items())
    ]


def cities_in_province(province: str) -> list[City]:
    return [c for c in CITIES if c.province.lower() == province.lower()]


def resolve(code: str) -> City | None:
    return CITY_BY_CODE.get(code.lower().strip())


def radius_for(city: City, coverage: str) -> int:
    return city.full_radius_m if coverage.upper() == "FULL" else city.core_radius_m
