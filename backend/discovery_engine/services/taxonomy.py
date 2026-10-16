"""One shared POI taxonomy across HERE, Google and Grab.

The three providers classify places in three incompatible ways:

  * Google Places (New) emits machine type strings, e.g. "hair_salon", "hospital".
  * HERE emits numeric category IDs from its own system, e.g. "800-8000-0159",
    alongside a human-readable name.
  * GrabMaps (Amazon Location) emits hierarchical free text,
    e.g. "eat and drink::restaurant", "healthcare::hospital".

A comparison is meaningless unless all three are folded onto one set of categories
first. Otherwise "restaurants in HERE but not Google" is really just an artefact of
two taxonomies disagreeing about what a restaurant is.

SCOPE: seven categories, deliberately narrow and specific.

Restaurants, bakeries and coffee shops are kept apart rather than merged into one
"food" bucket, because they are different businesses and a customer asking for
bakeries does not want every warung in the circle.

HOSPITAL covers medical care for people — hospitals, clinics, GPs and dentists.
Vets and opticians sit under the same provider roots but are not that, and are
vetoed explicitly; pharmacies are retail and stay out too.

Anything outside the seven classifies as OTHER and is excluded from a scoped sweep.

Classification is layered, most authoritative signal first:

  1. An exact provider code we recognise (Google type, HERE category ID prefix,
     Grab hierarchy path).
  2. A keyword match on the provider's own category *labels*.
  3. A keyword match on the business name.
  4. OTHER — recorded honestly rather than guessed into a bucket.

The HERE prefixes below were verified against 228 category IDs harvested live from
/browse over Jakarta and Denpasar, not taken from documentation. Re-harvest before
adding to them.
"""
from __future__ import annotations

import enum
import re


class UnifiedCategory(str, enum.Enum):
    """The shared vocabulary every provider result is folded into."""

    # --- the core seven this deployment usually runs ---
    HOTEL = "HOTEL"
    RESTAURANT = "RESTAURANT"
    HOSPITAL = "HOSPITAL"
    BAKERY = "BAKERY"
    COFFEE_SHOP = "COFFEE_SHOP"
    GROCERY = "GROCERY"
    FUEL = "FUEL"
    # --- the rest of the POI landscape, available but not selected by default ---
    PHARMACY = "PHARMACY"
    EDUCATION = "EDUCATION"
    BEAUTY = "BEAUTY"
    RETAIL = "RETAIL"
    FINANCE = "FINANCE"
    TRANSPORT = "TRANSPORT"
    AUTOMOTIVE = "AUTOMOTIVE"
    LEISURE = "LEISURE"
    WORSHIP = "WORSHIP"
    GOVERNMENT = "GOVERNMENT"
    SERVICES = "SERVICES"
    OTHER = "OTHER"


#: Display order and labels for the interface. OTHER sorts last on purpose.
CATEGORY_LABELS: dict[UnifiedCategory, str] = {
    UnifiedCategory.HOTEL: "Hotels",
    UnifiedCategory.RESTAURANT: "Restaurants",
    UnifiedCategory.HOSPITAL: "Hospitals & Clinics",
    UnifiedCategory.BAKERY: "Bakeries",
    UnifiedCategory.COFFEE_SHOP: "Coffee shops",
    UnifiedCategory.GROCERY: "Grocery stores",
    UnifiedCategory.FUEL: "Petrol stations",
    UnifiedCategory.PHARMACY: "Pharmacies",
    UnifiedCategory.EDUCATION: "Education",
    UnifiedCategory.BEAUTY: "Beauty & Salon",
    UnifiedCategory.RETAIL: "Shops & Retail",
    UnifiedCategory.FINANCE: "Banking & Finance",
    UnifiedCategory.TRANSPORT: "Transport",
    UnifiedCategory.AUTOMOTIVE: "Automotive",
    UnifiedCategory.LEISURE: "Leisure & Culture",
    UnifiedCategory.WORSHIP: "Places of Worship",
    UnifiedCategory.GOVERNMENT: "Government & Public",
    UnifiedCategory.SERVICES: "Professional Services",
    UnifiedCategory.OTHER: "Other / Unclassified",
}

#: The seven categories this deployment normally runs. Everything else stays
#: available so a full sweep is possible, but a run defaults to these unless the
#: caller asks otherwise.
CORE_CATEGORIES: list[UnifiedCategory] = [
    UnifiedCategory.HOTEL, UnifiedCategory.RESTAURANT, UnifiedCategory.HOSPITAL,
    UnifiedCategory.BAKERY, UnifiedCategory.COFFEE_SHOP, UnifiedCategory.GROCERY,
    UnifiedCategory.FUEL,
]

ORDERED_CATEGORIES: list[UnifiedCategory] = list(CATEGORY_LABELS.keys())


# ---------------------------------------------------------------------------
# Google Places API (New) — Table A place types
# ---------------------------------------------------------------------------
# These double as the sweep plan: searchNearby accepts includedTypes, so each
# group below becomes one request per tile. Keep groups under 50 types, which is
# the API's per-request ceiling.

GOOGLE_TYPE_GROUPS: dict[UnifiedCategory, list[str]] = {
    UnifiedCategory.HOTEL: [
        "hotel", "motel", "resort_hotel", "extended_stay_hotel", "bed_and_breakfast",
        "guest_house", "hostel", "lodging", "inn", "budget_japanese_inn",
    ],
    UnifiedCategory.RESTAURANT: [
        "restaurant", "meal_takeaway", "meal_delivery", "fast_food_restaurant",
        "food_court", "steak_house", "pizza_restaurant", "seafood_restaurant",
        "vegetarian_restaurant", "indonesian_restaurant", "chinese_restaurant",
        "japanese_restaurant", "italian_restaurant", "indian_restaurant",
        "thai_restaurant", "korean_restaurant", "sushi_restaurant",
        "hamburger_restaurant", "sandwich_shop", "buffet_restaurant",
    ],
    UnifiedCategory.HOSPITAL: [
        "hospital", "doctor", "dentist", "medical_lab", "physiotherapist",
        "chiropractor", "skin_care_clinic", "wellness_center",
    ],
    UnifiedCategory.BAKERY: [
        "bakery", "donut_shop", "bagel_shop", "dessert_shop", "cake_shop",
        "candy_store", "confectionery",
    ],
    UnifiedCategory.COFFEE_SHOP: [
        "cafe", "coffee_shop", "tea_house", "cat_cafe", "dog_cafe", "internet_cafe",
    ],
    UnifiedCategory.GROCERY: [
        "grocery_store", "supermarket", "convenience_store", "food_store",
        "market", "asian_grocery_store", "butcher_shop", "wholesaler",
    ],
    UnifiedCategory.FUEL: [
        "gas_station", "electric_vehicle_charging_station", "truck_stop",
    ],
    UnifiedCategory.PHARMACY: ["pharmacy", "drugstore"],
    UnifiedCategory.EDUCATION: [
        "school", "primary_school", "secondary_school", "university", "preschool",
        "library", "child_care_agency",
    ],
    UnifiedCategory.BEAUTY: [
        "hair_salon", "beauty_salon", "nail_salon", "barber_shop", "spa",
        "hair_care", "massage", "makeup_artist", "tanning_studio", "sauna",
    ],
    UnifiedCategory.RETAIL: [
        "store", "shopping_mall", "department_store", "clothing_store", "shoe_store",
        "electronics_store", "furniture_store", "hardware_store", "book_store",
        "jewelry_store", "sporting_goods_store", "pet_store", "florist",
        "gift_shop", "liquor_store", "home_goods_store",
    ],
    UnifiedCategory.FINANCE: ["bank", "atm", "accounting", "insurance_agency"],
    UnifiedCategory.TRANSPORT: [
        "airport", "bus_station", "train_station", "subway_station", "transit_station",
        "taxi_stand", "parking", "ferry_terminal", "bus_stop", "light_rail_station",
    ],
    UnifiedCategory.AUTOMOTIVE: [
        "car_repair", "car_dealer", "car_rental", "car_wash", "auto_parts_store",
    ],
    UnifiedCategory.LEISURE: [
        "park", "gym", "fitness_center", "movie_theater", "museum", "art_gallery",
        "tourist_attraction", "night_club", "amusement_park", "zoo", "aquarium",
        "stadium", "swimming_pool", "sports_complex", "golf_course", "casino",
        "bowling_alley", "community_center", "cultural_center", "bar",
    ],
    UnifiedCategory.WORSHIP: [
        "mosque", "church", "hindu_temple", "synagogue",
    ],
    UnifiedCategory.GOVERNMENT: [
        "local_government_office", "city_hall", "police", "fire_station",
        "post_office", "embassy", "courthouse", "government_office",
    ],
    UnifiedCategory.SERVICES: [
        "laundry", "real_estate_agency", "lawyer", "travel_agency", "moving_company",
        "storage", "electrician", "plumber", "veterinary_care", "funeral_home",
        "tailor", "consultant", "courier_service",
    ],
}

#: Reverse index: one Google type -> one unified category.
GOOGLE_TYPE_TO_UNIFIED: dict[str, UnifiedCategory] = {
    google_type: category
    for category, types in GOOGLE_TYPE_GROUPS.items()
    for google_type in types
}


# ---------------------------------------------------------------------------
# HERE category system
# ---------------------------------------------------------------------------
# HERE IDs are dash-joined and hierarchical: "500-5000-0053" is Accommodation >
# Hotel-Motel > Hotel. Mapping is done on prefixes, longest first, because leaf
# IDs are numerous and versioned while the upper segments are stable.
#
# Only prefixes belonging to the seven categories appear here. Everything else
# falls through to OTHER, which is what keeps a scoped sweep scoped.

HERE_PREFIX_TO_UNIFIED: list[tuple[str, UnifiedCategory]] = [
    # --- Coffee and tea, before the wider Eat & Drink root ---
    ("100-1100", UnifiedCategory.COFFEE_SHOP),      # Kopi/Teh, Kedai Kopi, Tea Room
    ("100-1000-0009", UnifiedCategory.COFFEE_SHOP),  # snack/coffee bar variants
    # --- Bakery, which HERE files under Shopping rather than Eat & Drink ---
    ("600-6300-0244", UnifiedCategory.BAKERY),      # Tukang Roti
    ("600-6300-0246", UnifiedCategory.BAKERY),      # Toko Donat
    ("600-6300-0245", UnifiedCategory.BAKERY),      # Toko Makanan Ringan (snacks)
    # --- Grocery, also under Shopping ---
    ("600-6000", UnifiedCategory.GROCERY),          # Minimarket
    ("600-6300-0064", UnifiedCategory.GROCERY),     # Makanan & Minuman Khusus
    ("600-6300-0066", UnifiedCategory.GROCERY),     # Supermarket
    ("600-6300-0067", UnifiedCategory.GROCERY),     # Toko Makanan Khusus
    ("600-6300-0363", UnifiedCategory.GROCERY),     # Toko Daging (butcher)
    ("600-6900-0247", UnifiedCategory.GROCERY),     # Pasar (market)
    # --- Restaurants: the rest of Eat & Drink ---
    ("100-1000", UnifiedCategory.RESTAURANT),       # Restoran, warung, cafeteria
    # --- Hotels ---
    ("500-5000", UnifiedCategory.HOTEL),            # Hotel, Motel
    ("500-5100", UnifiedCategory.HOTEL),            # Penginapan, Hostel, Wisma Tamu
    # --- Medical facilities: hospitals, clinics, GPs and dentists.
    #     Vets and opticians share the 800-8000 root but are not medical care for
    #     people, so they are vetoed individually before the subtree is claimed.
    ("800-8000-0161", UnifiedCategory.OTHER),       # Ahli Kacamata (optician)
    ("800-8000-0162", UnifiedCategory.OTHER),       # Dokter Hewan (veterinarian)
    ("800-8000", UnifiedCategory.HOSPITAL),         # hospital, clinic, GP, dentist, ER
    ("700-7200-0272", UnifiedCategory.HOSPITAL),    # Layanan Bantuan & Perawatan Kesehatan
    # --- Petrol ---
    ("700-7600", UnifiedCategory.FUEL),             # Pom Bensin
    ("400-4400", UnifiedCategory.FUEL),             # petrol station (alternate root)
    # --- Pharmacy, split out of Shopping ---
    ("600-6400", UnifiedCategory.PHARMACY),         # Apotek / Toko Obat
    # --- Beauty, also under Shopping ---
    ("600-6950", UnifiedCategory.BEAUTY),           # Rambut & Kecantikan
    ("700-7400-0283", UnifiedCategory.BEAUTY),      # Tato & Tindik
    # --- Finance ---
    ("700-7000", UnifiedCategory.FINANCE),          # Bank
    ("700-7010", UnifiedCategory.FINANCE),          # ATM
    ("700-7050", UnifiedCategory.FINANCE),          # cheque cashing / exchange
    ("700-7200-0271", UnifiedCategory.FINANCE),     # financial & insurance
    # --- Automotive ---
    ("700-7200-0268", UnifiedCategory.AUTOMOTIVE),  # motorcycle repair
    ("700-7800", UnifiedCategory.AUTOMOTIVE),       # car & motorcycle dealers
    ("700-7850", UnifiedCategory.AUTOMOTIVE),       # car service, wash, parts
    ("700-7851", UnifiedCategory.AUTOMOTIVE),       # car rental
    # --- Government and emergency ---
    ("700-7300", UnifiedCategory.GOVERNMENT),       # fire brigade, ambulance
    ("700-7400-0289", UnifiedCategory.GOVERNMENT),  # public administration
    ("700-7450", UnifiedCategory.GOVERNMENT),       # post office
    ("800-8100", UnifiedCategory.GOVERNMENT),       # government facility, city hall
    # --- Education ---
    ("700-7400-0286", UnifiedCategory.EDUCATION),   # childcare / daycare
    ("800-8200", UnifiedCategory.EDUCATION),        # education & training, college
    ("800-8250", UnifiedCategory.EDUCATION),        # schools
    ("800-8300", UnifiedCategory.EDUCATION),        # library
    # --- Worship, inside Sights & Museums ---
    ("300-3200", UnifiedCategory.WORSHIP),          # mosque, church, temple
    # --- Leisure ---
    ("700-7400-0292", UnifiedCategory.LEISURE),     # fitness centre
    ("700-7460", UnifiedCategory.LEISURE),          # tourist information
    ("800-8400", UnifiedCategory.LEISURE),          # exhibition / convention
    ("800-8600", UnifiedCategory.LEISURE),          # sports facility, stadium
    ("200", UnifiedCategory.LEISURE),               # Going Out
    ("300", UnifiedCategory.LEISURE),               # Sights & Museums
    ("350", UnifiedCategory.LEISURE),               # Natural & Geographical
    ("550", UnifiedCategory.LEISURE),               # Leisure & Outdoor
    # --- Transport (fuel already claimed above) ---
    ("400-4100", UnifiedCategory.TRANSPORT),        # public transport
    ("400-4200", UnifiedCategory.TRANSPORT),        # cargo, courier
    ("800-8500", UnifiedCategory.TRANSPORT),        # car park
    ("400", UnifiedCategory.TRANSPORT),
    # --- Broad roots last: whatever is left in Shopping is retail, and whatever
    #     is left in Facilities is a service.
    ("600", UnifiedCategory.RETAIL),
    ("700", UnifiedCategory.SERVICES),
]

#: HERE top-level roots worth sweeping for these seven categories.
#: 100 Eat & Drink, 500 Accommodation, 600 Shopping, 700 Facilities, 800 Areas.
#: Roots that contain none of the seven (200 Going Out, 300 Sights, 350 Natural,
#: 400 Transport beyond fuel, 550 Leisure) are skipped, which is most of the saving
#: a narrow scope buys on this provider.
HERE_SWEEP_ROOTS: list[str] = ["100", "200", "300", "350", "400", "500", "550", "600", "700", "800"]


# ---------------------------------------------------------------------------
# GrabMaps (Amazon Location) hierarchical categories
# ---------------------------------------------------------------------------

GRAB_PATH_TO_UNIFIED: list[tuple[str, UnifiedCategory]] = [
    ("eat and drink::coffee", UnifiedCategory.COFFEE_SHOP),
    ("eat and drink::cafe", UnifiedCategory.COFFEE_SHOP),
    ("eat and drink::bakery", UnifiedCategory.BAKERY),
    ("eat and drink::dessert", UnifiedCategory.BAKERY),
    ("eat and drink", UnifiedCategory.RESTAURANT),
    ("restaurant", UnifiedCategory.RESTAURANT),
    ("food and drink::coffee", UnifiedCategory.COFFEE_SHOP),
    ("food and drink::bakery", UnifiedCategory.BAKERY),
    ("food and drink", UnifiedCategory.RESTAURANT),
    ("healthcare::pets", UnifiedCategory.OTHER),
    ("healthcare::hospital", UnifiedCategory.HOSPITAL),
    ("healthcare::clinic", UnifiedCategory.HOSPITAL),
    ("healthcare::physicians", UnifiedCategory.HOSPITAL),
    ("healthcare::dentist", UnifiedCategory.HOSPITAL),
    ("accommodation", UnifiedCategory.HOTEL),
    ("hotel", UnifiedCategory.HOTEL),
    ("general merchandise::grocery", UnifiedCategory.GROCERY),
    ("general merchandise::convenience", UnifiedCategory.GROCERY),
    ("shopping::grocery", UnifiedCategory.GROCERY),
    ("automotive::petrol", UnifiedCategory.FUEL),
    ("automotive::gas", UnifiedCategory.FUEL),
    ("transportation::petrol", UnifiedCategory.FUEL),
    ("healthcare::pharmacy", UnifiedCategory.PHARMACY),
    ("education", UnifiedCategory.EDUCATION),
    ("beauty services", UnifiedCategory.BEAUTY),
    ("financial", UnifiedCategory.FINANCE),
    ("finance", UnifiedCategory.FINANCE),
    ("automotive", UnifiedCategory.AUTOMOTIVE),
    ("transportation", UnifiedCategory.TRANSPORT),
    ("transport", UnifiedCategory.TRANSPORT),
    ("religious", UnifiedCategory.WORSHIP),
    ("place of worship", UnifiedCategory.WORSHIP),
    ("government", UnifiedCategory.GOVERNMENT),
    ("public service", UnifiedCategory.GOVERNMENT),
    ("entertainment", UnifiedCategory.LEISURE),
    ("leisure", UnifiedCategory.LEISURE),
    ("sports", UnifiedCategory.LEISURE),
    ("attraction", UnifiedCategory.LEISURE),
    ("general merchandise", UnifiedCategory.RETAIL),
    ("shopping", UnifiedCategory.RETAIL),
    ("business services", UnifiedCategory.SERVICES),
    ("professional services", UnifiedCategory.SERVICES),
    ("services", UnifiedCategory.SERVICES),
]

#: Grab has no radius+category discovery, only SearchText, so recall on the Grab
#: leg is bounded by this matrix. Indonesian terms lead because the target market
#: is Indonesia and Grab indexes local-language names.
#:
#: Every term costs one paginated SearchText call per tile, so this list is the
#: single biggest driver of Grab spend.
GRAB_QUERY_TERMS: dict[UnifiedCategory, list[str]] = {
    UnifiedCategory.HOTEL: ["hotel", "penginapan", "homestay", "wisma", "losmen", "guest house"],
    UnifiedCategory.RESTAURANT: ["restoran", "rumah makan", "warung makan", "depot makan", "kantin"],
    UnifiedCategory.HOSPITAL: ["rumah sakit", "rsud", "klinik", "puskesmas", "dokter"],
    UnifiedCategory.BAKERY: ["toko roti", "bakery", "kue", "roti"],
    UnifiedCategory.COFFEE_SHOP: ["kedai kopi", "kafe", "coffee shop", "warung kopi", "cafe"],
    UnifiedCategory.GROCERY: ["minimarket", "supermarket", "toko kelontong", "swalayan", "pasar swalayan"],
    UnifiedCategory.FUEL: ["spbu", "pom bensin", "pertamina", "stasiun pengisian bahan bakar"],
    UnifiedCategory.PHARMACY: ["apotek", "apotik", "toko obat"],
    UnifiedCategory.EDUCATION: ["sekolah", "universitas", "kampus", "bimbingan belajar", "paud"],
    UnifiedCategory.BEAUTY: ["salon", "barbershop", "spa", "nail art", "pangkas rambut"],
    UnifiedCategory.RETAIL: ["toko", "mall", "pasar", "butik", "toko elektronik"],
    UnifiedCategory.FINANCE: ["bank", "atm", "pegadaian", "koperasi"],
    UnifiedCategory.TRANSPORT: ["terminal", "stasiun", "parkir", "pelabuhan"],
    UnifiedCategory.AUTOMOTIVE: ["bengkel", "cuci mobil", "dealer motor", "showroom mobil"],
    UnifiedCategory.LEISURE: ["gym", "bioskop", "taman", "museum", "lapangan"],
    UnifiedCategory.WORSHIP: ["masjid", "gereja", "pura", "vihara", "musholla"],
    UnifiedCategory.GOVERNMENT: ["kantor polisi", "kantor pos", "kelurahan", "kantor camat"],
    UnifiedCategory.SERVICES: ["laundry", "notaris", "agen travel", "percetakan", "fotokopi"],
}


# ---------------------------------------------------------------------------
# Label keyword fallback, shared by all three providers
# ---------------------------------------------------------------------------
# Applied to provider category labels first and to the business name second.
# Order matters: the first category whose pattern hits wins, so the narrower
# verticals are tested before the broader ones — a "Toko Roti" is a bakery, not a
# grocery, and a "Kedai Kopi" is a coffee shop, not a restaurant.

_LABEL_PATTERNS: list[tuple[UnifiedCategory, re.Pattern[str]]] = [
    (UnifiedCategory.FUEL, re.compile(
        r"\b(spbu|pom bensin|pertamina|shell|petrol|gas station|fuel|bahan bakar|"
        r"pengisian bahan bakar|charging station)\b")),
    (UnifiedCategory.HOSPITAL, re.compile(
        r"\b(rumah sakit|rsud|rsup|rsia|hospital|unit gawat darurat|instalasi gawat darurat)\b|"
        r"^rs\b|\brs[ud]\b")),
    (UnifiedCategory.BAKERY, re.compile(
        r"\b(bakery|bakeri|toko roti|tukang roti|roti|kue|cake|pastry|patisserie|"
        r"donat|donut|bagel|dessert)\b")),
    (UnifiedCategory.COFFEE_SHOP, re.compile(
        r"\b(coffee|kopi|kafe|cafe|caffe|espresso|kedai kopi|warkop|warung kopi|"
        r"tea room|kedai teh|teahouse)\b")),
    (UnifiedCategory.GROCERY, re.compile(
        r"\b(minimarket|supermarket|swalayan|grocery|kelontong|convenience|"
        r"indomaret|alfamart|hypermart|pasar swalayan|toko sembako|sembako)\b")),
    (UnifiedCategory.HOTEL, re.compile(
        r"\b(hotel|motel|hostel|resort|penginapan|homestay|wisma|losmen|guest house|"
        r"lodging|inn|bed and breakfast)\b")),
    (UnifiedCategory.RESTAURANT, re.compile(
        r"\b(restaurant|restoran|rumah makan|warung makan|warteg|depot|kantin|"
        r"eatery|bistro|food court|steak|pizza|seafood|nasi|bakmi|mie ayam|"
        r"ayam goreng|soto|padang)\b")),
]

_NON_WORD = re.compile(r"[^a-z0-9]+")


def _flatten(values: list[str] | None) -> str:
    return " ".join(v for v in (values or []) if v).lower()


def _match_labels(text: str) -> UnifiedCategory | None:
    if not text:
        return None
    for category, pattern in _LABEL_PATTERNS:
        if pattern.search(text):
            return category
    return None


def classify_google(types: list[str] | None, name: str = "") -> UnifiedCategory:
    """Google emits machine types, so the code path is authoritative when it hits."""
    for google_type in types or []:
        mapped = GOOGLE_TYPE_TO_UNIFIED.get(google_type.lower())
        if mapped:
            return mapped
    return _match_labels(_flatten(types).replace("_", " ")) or _match_labels(name.lower()) or UnifiedCategory.OTHER


def classify_here(category_ids: list[str] | None, labels: list[str] | None = None, name: str = "") -> UnifiedCategory:
    """Prefix match on HERE IDs, longest prefix first, then the label fallback."""
    ids = [str(c) for c in (category_ids or [])]
    for prefix, category in HERE_PREFIX_TO_UNIFIED:
        if any(cid.startswith(prefix) for cid in ids):
            return category
    return _match_labels(_flatten(labels)) or _match_labels(name.lower()) or UnifiedCategory.OTHER


def classify_grab(categories: list[str] | None, name: str = "") -> UnifiedCategory:
    """Grab paths are 'root::leaf'; the most specific matching path wins."""
    lowered = [c.lower().strip() for c in (categories or []) if c]
    for path, category in GRAB_PATH_TO_UNIFIED:
        # A path matches its exact value, a deeper branch, or a longer leaf name:
        # "eat and drink::coffee" must catch "eat and drink::coffee shop", or the
        # broader "eat and drink" entry below it would claim every cafe.
        if any(
            value == path or value.startswith(path + "::") or value.startswith(path + " ")
            for value in lowered
        ):
            return category

    # A record that carries a full hierarchy and matched none of the paths above is
    # genuinely outside our categories, and its NAME does not get a vote. Without
    # this veto a school called "Sekolah Kopi Nusantara" classifies as a coffee shop
    # on the word "Kopi" — which is how Quran schools once reached a live export.
    if any("::" in value for value in lowered):
        return UnifiedCategory.OTHER

    return _match_labels(_flatten(categories).replace("::", " ")) or _match_labels(name.lower()) or UnifiedCategory.OTHER


def classify(provider_name: str, categories: list[str] | None, name: str = "") -> UnifiedCategory:
    """Dispatch on provider name. `provider_name` is the Provider enum's value."""
    key = (provider_name or "").upper()
    if key == "GOOGLE":
        return classify_google(categories, name)
    if key == "HERE":
        # HERE DTOs carry IDs and labels in one list; the classifier tries both.
        return classify_here(categories, categories, name)
    if key == "GRAB":
        return classify_grab(categories, name)
    return _match_labels(_flatten(categories)) or _match_labels(name.lower()) or UnifiedCategory.OTHER


def google_sweep_plan(selected: list[UnifiedCategory] | None = None) -> list[tuple[UnifiedCategory, list[str]]]:
    """One entry per searchNearby request per tile."""
    wanted = selected or [c for c in ORDERED_CATEGORIES if c is not UnifiedCategory.OTHER]
    return [(c, GOOGLE_TYPE_GROUPS[c]) for c in wanted if c in GOOGLE_TYPE_GROUPS]


def grab_sweep_plan(selected: list[UnifiedCategory] | None = None) -> list[tuple[UnifiedCategory, str]]:
    """One entry per SearchText request per tile."""
    wanted = selected or [c for c in ORDERED_CATEGORIES if c is not UnifiedCategory.OTHER]
    return [(c, term) for c in wanted for term in GRAB_QUERY_TERMS.get(c, [])]


def here_sweep_plan(selected: list[UnifiedCategory] | None = None) -> list[str]:
    """One entry per /browse request per tile, as HERE top-level category roots.

    HERE is filtered by its own roots rather than by unified category, because one
    unified category can span several HERE roots and requesting a root twice would
    be paid for twice. When the caller narrows the categories, only the roots that
    can contain them are swept.
    """
    if not selected:
        return list(HERE_SWEEP_ROOTS)
    wanted = set(selected)
    roots = [
        root for root in HERE_SWEEP_ROOTS
        if any(mapped in wanted for prefix, mapped in HERE_PREFIX_TO_UNIFIED if prefix.startswith(root))
    ]
    return roots or list(HERE_SWEEP_ROOTS)
