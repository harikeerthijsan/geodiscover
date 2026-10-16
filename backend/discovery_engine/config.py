from functools import lru_cache
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Sweep field mask stays inside the Essentials + Pro SKU tiers. Adding any of
# nationalPhoneNumber / internationalPhoneNumber / websiteUri / rating / userRatingCount
# promotes EVERY tile call to the Enterprise SKU, so contact fields are fetched only
# during enrichment of surviving records. See MVP_GRAB_VS_GOOGLE.md section 7.
# addressComponents is Essentials tier, the same as formattedAddress, so adding it
# gives city and province at no SKU cost. Without it every Google record lands with
# an unknown city and the city filter is useless on half the dataset.
GOOGLE_SWEEP_FIELD_MASK = (
    "places.id,places.location,places.formattedAddress,places.addressComponents,"
    "places.types,places.displayName,places.primaryType,places.businessStatus"
)
GOOGLE_DETAIL_FIELD_MASK = (
    "id,location,formattedAddress,addressComponents,types,displayName,primaryType,"
    "businessStatus,googleMapsUri,nationalPhoneNumber,internationalPhoneNumber,websiteUri"
)


#: Postgres schema the engine's tables live in when deployed on Postgres.
ENGINE_SCHEMA = "engine"


def normalise_database_url(url: str) -> str:
    """Make a hosted Postgres URL usable by SQLAlchemy 2 with psycopg 3.

    Railway and Heroku hand out "postgres://" or "postgresql://" URLs, but
    SQLAlchemy needs an explicit driver or it reaches for psycopg2, which is not
    installed here.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Settings(BaseSettings):
    # Railway's PostgreSQL plugin exposes the connection string as DATABASE_URL.
    # Accept it directly so a deployment works with nothing but that one variable,
    # while ENGINE_DATABASE_URL still wins when set (e.g. a second, dedicated DB).
    engine_database_url: str = Field(
        default="sqlite:///./discovery_engine.db",
        validation_alias=AliasChoices("ENGINE_DATABASE_URL", "DATABASE_URL"),
    )
    # How long boot waits for a slow-to-start database (Postgres) before giving up.
    db_wait_seconds: int = 60
    # On boot, load the bundled discovery snapshot into an empty engine database.
    seed_on_boot: bool = True
    # Override the snapshot location; empty means auto-detect the bundled file.
    seed_db_path: str = ""
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480
    demo_admin_email: str = "admin@example.com"
    demo_admin_password: str
    cors_origins: str = "http://localhost:5173"

    # --- Google Places API (New) ---
    google_maps_api_key: str = ""
    google_sweep_field_mask: str = GOOGLE_SWEEP_FIELD_MASK
    google_detail_field_mask: str = GOOGLE_DETAIL_FIELD_MASK
    google_language_code: str = "id"
    google_region_code: str = "ID"

    # --- HERE Geocoding & Search v7 + Maps API for JavaScript ---
    # One HERE API key authenticates both the /browse POI endpoint and the JS
    # basemap. Empty means HERE cannot be swept at all: the API refuses the run
    # rather than substituting anything, and the map falls back to OpenStreetMap.
    here_api_key: str = ""
    here_language: str = "id-ID"
    # /browse caps at 100 results per call; saturation is handled by tile subdivision.
    here_max_results_per_call: int = 100
    here_max_calls_per_run: int = 6000

    # --- GrabMaps via Amazon Location Service (geo-places) ---
    # GrabMaps data is served from ap-southeast-1 (Singapore) and ap-southeast-5 (Malaysia).
    # Two auth modes are supported; the API key takes precedence when both are present.
    #  1. Amazon Location API key — a PASETO token beginning "v1.public.". Sent as the
    #     Key request parameter with the request otherwise unsigned.
    #  2. SigV4 IAM credentials — an access key ID + secret pair.
    aws_region: str = "ap-southeast-1"
    aws_location_api_key: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""
    # Amazon Location's Label/Core/Advanced buckets all state that results "can't be
    # stored permanently". This application persists every result into provider_places,
    # so Storage is the correct and required setting. It bills at a higher rate.
    grab_intended_use: str = "Storage"
    grab_language: str = "id"
    grab_country: str = "IDN"

    # --- Cost guardrails: a run aborts rather than overrunning these ---
    # An all-category area sweep is far heavier than the single-vertical sweep these
    # defaults were sized for: Google costs one call per category group per tile, and
    # Grab one call per keyword per tile. Raised so an exhaustive 3 km run completes
    # instead of aborting half-covered. The USD ceilings below are the real brake.
    google_max_calls_per_run: int = 20000
    grab_max_calls_per_run: int = 20000
    # Optional USD ceiling per run. 0 disables it and leaves the call cap as the only
    # bound. A run stops as soon as the next call would cross the ceiling.
    google_max_spend_per_run_usd: float = 0.0
    grab_max_spend_per_run_usd: float = 0.0

    # --- API rates, USD per 1,000 requests ---
    # A negative value means "not configured": cost is then reported as unknown rather
    # than as zero, so a missing rate cannot masquerade as a free call.
    # Verify these against your own billing console before trusting any estimate.
    # Google Places (New) bills at the highest SKU tier the field mask touches; the
    # sweep mask is Pro, enrichment is Enterprise. The defaults below use the highest
    # rate observed, so estimates are an upper bound rather than a surprise.
    rate_google_nearby_per_1k: float = 32.0
    rate_google_text_per_1k: float = 32.0
    rate_google_details_per_1k: float = 20.0
    # Amazon Location Places buckets are Label / Core / Advanced / Stored. Persisting
    # results, which this application does, requires the Stored bucket. Left
    # unconfigured by default because the rate depends on your agreement.
    rate_grab_search_text_per_1k: float = -1.0
    # HERE freemium bills nothing until the daily allowance is exhausted, so the
    # honest default is 0.0 rather than the -1.0 "unknown" sentinel. Set this to your
    # contracted per-1k rate if you move onto a paid HERE plan.
    rate_here_browse_per_1k: float = 0.0
    provider_request_timeout: float = 20.0
    provider_max_retries: int = 3

    # --- Matching thresholds (project rows may override) ---
    match_auto_threshold: int = 85
    match_possible_threshold: int = 60
    match_max_distance_m: float = 300.0

    # Retention window for cached third-party place payloads, in days.
    provider_payload_ttl_days: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_maps_api_key)

    @property
    def here_enabled(self) -> bool:
        """False means HERE cannot be selected for a sweep and the map uses OSM."""
        return bool(self.here_api_key)

    @property
    def grab_uses_api_key(self) -> bool:
        return bool(self.aws_location_api_key)

    @property
    def grab_enabled(self) -> bool:
        return self.grab_uses_api_key or bool(self.aws_access_key_id and self.aws_secret_access_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
