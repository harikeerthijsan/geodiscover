import re
import unicodedata
from typing import Any

ALIASES = {
    "name": ["business_name", "name", "poi_name", "title"],
    "category": ["category", "type", "business_category", "subcategory"],
    "address": ["full_address", "address", "formatted_address", "street_address"],
    "city": ["city", "municipality", "kabupaten", "kota"],
    "province": ["province", "state", "administrative_area", "region"],
    "lat": ["latitude", "lat", "y"],
    "lon": ["longitude", "lon", "lng", "x"],
    "phone": ["phone", "telephone", "contact_number"],
    "whatsapp": ["whatsapp", "wa", "whatsapp_number"],
    "website": ["website", "url", "official_website"],
    "booking_url": ["booking_url", "booking", "fresha_url"],
    "instagram": ["instagram", "instagram_url", "ig"],
    "tiktok": ["tiktok", "tiktok_url"],
    "facebook": ["facebook", "facebook_url", "fb"],
    "source_url": ["primary_source_url", "source_url", "evidence_url"],
    "source_record_id": ["source_record_id", "record_id", "id", "place_id"],
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", value)


def pick(row: dict[str, Any], aliases: list[str]) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in aliases:
        value = lowered.get(key)
        if value not in (None, ""):
            return value
    return None


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def has_usable_category(category: str | None) -> bool:
    """True when a row carries a real category rather than a placeholder.

    This replaced a single-vertical test. Scope is now expressed as unified
    categories on the sweep itself, so the only thing left to check per row is
    whether the provider told us anything about what the place is.
    """
    text = normalize_text(category)
    return bool(text) and text not in {"unclassified", "unknown", "other", "none"}


# Trade words that carry no identifying information. Two chemists on the same street
# can both normalise to "apotek", and two eateries to "rumah makan", so a name made
# only of these tokens must never be treated as evidence that two records are the same
# business. The matcher renormalises them out and caps such a pair at POSSIBLE_MATCH.
#
# Covers every vertical in the unified taxonomy, in Indonesian and English, because a
# generic word left in place inflates the name signal for every unrelated pair sharing
# it — which is how two different schools 40 m apart get auto-merged.
GENERIC_NAME_TOKENS = {
    "salon", "salons", "beauty", "hair", "haircut", "barber", "barbershop", "barbers",
    "studio", "spa", "nail", "nails", "kecantikan", "rambut", "potong", "cukur",
    "make", "up", "makeup", "the", "dan", "and", "of", "by", "di", "de", "cabang",
    "pusat", "toko", "jasa", "perawatan", "klinik", "care", "shop", "house", "center",
    "centre", "id", "indonesia",
    # Food
    "restoran", "restaurant", "rumah", "makan", "warung", "kedai", "cafe", "kafe",
    "depot", "kantin", "bakery", "roti",
    # Retail
    "minimarket", "supermarket", "swalayan", "pasar", "store", "mart", "market",
    # Health
    "apotek", "apotik", "farma", "rumah sakit", "sakit", "puskesmas", "praktik",
    "praktek", "dokter", "clinic", "hospital", "pharmacy",
    # Education
    "sekolah", "sekolah dasar", "negeri", "swasta", "school", "kampus", "universitas",
    "university", "college", "paud",
    # Accommodation, transport, worship, services
    "hotel", "villa", "penginapan", "homestay", "guest", "wisma", "kost",
    "terminal", "stasiun", "station", "spbu", "parkir", "parking",
    "masjid", "gereja", "pura", "vihara", "musholla", "mosque", "church", "temple",
    "bengkel", "laundry", "kantor", "office", "agen", "layanan", "service", "services",
}


# Indonesian POI abbreviations, expanded before matching.
#
# Providers disagree about whether to abbreviate: Google carries "RS Sanglah
# Denpasar" where HERE and Grab carry "Rumah Sakit Sanglah". Those score far below
# the auto-match threshold on token overlap despite being metres apart, and every
# such miss invents a coverage gap — the exact false finding this pipeline exists to
# avoid. Expanding both sides to the same long form removes the whole class.
#
# Keys are matched as whole tokens only. Values are expanded before generic-token
# stripping, so an expansion that lands on a generic word is then stripped normally.
NAME_ABBREVIATIONS = {
    "rs": "rumah sakit",
    "rsu": "rumah sakit umum",
    "rsud": "rumah sakit umum daerah",
    "rsup": "rumah sakit umum pusat",
    "rsia": "rumah sakit ibu anak",
    "pkm": "puskesmas",
    "apt": "apotek",
    "sd": "sekolah dasar",
    "sdn": "sekolah dasar negeri",
    "smp": "sekolah menengah pertama",
    "smpn": "sekolah menengah pertama negeri",
    "sma": "sekolah menengah atas",
    "sman": "sekolah menengah atas negeri",
    "smk": "sekolah menengah kejuruan",
    "smkn": "sekolah menengah kejuruan negeri",
    "tk": "taman kanak kanak",
    "univ": "universitas",
    "unv": "universitas",
    "spbu": "stasiun pengisian bahan bakar umum",
    "kel": "kelurahan",
    "kec": "kecamatan",
}

# Legal-entity prefixes. They identify the company, not the place, and one provider
# routinely carries them where another does not.
ENTITY_PREFIX_TOKENS = {"pt", "cv", "ud", "tbk", "persero"}


def expand_abbreviations(text: str) -> str:
    """Expand known abbreviations in already-normalised text, token by token."""
    return " ".join(NAME_ABBREVIATIONS.get(token, token) for token in text.split())


def match_name(value: str | None) -> str:
    """Normalised name with generic trade tokens removed, used for match scoring.

    Returns an empty string when nothing distinguishing survives, which the matcher
    treats as "no name evidence" rather than "names agree".
    """
    expanded = expand_abbreviations(normalize_text(value))
    tokens = [
        t for t in expanded.split()
        if t and t not in GENERIC_NAME_TOKENS and t not in ENTITY_PREFIX_TOKENS
    ]
    return " ".join(tokens)


def normalize_phone_id(value: str | None) -> str | None:
    """Best-effort E.164 for Indonesian numbers. Returns None when unusable."""
    if not value:
        return None
    digits = re.sub(r"[^\d+]", "", str(value))
    if not digits:
        return None
    if digits.startswith("+"):
        digits = "+" + re.sub(r"\D", "", digits[1:])
        return digits if len(digits) >= 9 else None
    digits = re.sub(r"\D", "", digits)
    if digits.startswith("62"):
        candidate = "+" + digits
    elif digits.startswith("0"):
        candidate = "+62" + digits[1:]
    else:
        candidate = "+62" + digits
    return candidate if len(candidate) >= 10 else None


def website_domain(value: str | None) -> str | None:
    """Registrable-ish domain for comparing websites across providers."""
    if not value:
        return None
    text = str(value).strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    text = text.split("/")[0].split("?")[0].split("#")[0]
    text = text.split("@")[-1]
    if text.startswith("www."):
        text = text[4:]
    text = text.split(":")[0]
    return text or None


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    name = pick(row, ALIASES["name"])
    category = pick(row, ALIASES["category"]) or "Unclassified"
    return {
        "business_name": str(name).strip() if name else "Unnamed candidate",
        "normalized_name": normalize_text(str(name) if name else "Unnamed candidate"),
        "category": str(category).strip(),
        "business_verified": has_usable_category(str(category)),
        "full_address": pick(row, ALIASES["address"]),
        "city": pick(row, ALIASES["city"]),
        "province": pick(row, ALIASES["province"]),
        "latitude": parse_float(pick(row, ALIASES["lat"])),
        "longitude": parse_float(pick(row, ALIASES["lon"])),
        "phone": pick(row, ALIASES["phone"]),
        "whatsapp": pick(row, ALIASES["whatsapp"]),
        "website": pick(row, ALIASES["website"]),
        "booking_url": pick(row, ALIASES["booking_url"]),
        "instagram": pick(row, ALIASES["instagram"]),
        "tiktok": pick(row, ALIASES["tiktok"]),
        "facebook": pick(row, ALIASES["facebook"]),
        "primary_source_url": pick(row, ALIASES["source_url"]),
        "source_record_id": pick(row, ALIASES["source_record_id"]),
    }
