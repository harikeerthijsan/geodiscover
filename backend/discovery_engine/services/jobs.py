"""End-to-end city discovery: one action instead of six API calls.

A job sweeps both providers over one city, matches the results, probes everything
that did not match, and leaves a downloadable set of unique records behind. It is a
thin orchestrator over the existing services — the guarantees live there, not here.

Note on "real time": this runs against live provider APIs, but it is not instant. A
core-area sweep of a mid-size city is a few hundred calls and takes minutes; a full
city can be thousands. Progress is polled via the job row, and the spend caps in
settings are what bound it.
"""
from __future__ import annotations

from itertools import zip_longest

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..data.indonesia import City, radius_for
from ..models import (
    DiscoveryJob,
    DiscoveryRun,
    JobStage,
    PresenceBucket,
    Project,
    Provider,
    ProviderPlace,
    RunStatus,
    SearchArea,
    UniquenessVerdict,
    utcnow,
)
from ..providers import ProviderError, get_adapter
from .comparison import calculate_comparison_kpis
from .coverage import resolve_by_area_coverage
from .geo import cover_circle_with_tiles
from .pricing import estimate_sweep, probe_operation, summarise, sweep_operation
from .probe import apply_verdicts, probe_place, run_bulk_match, unprobed_places
from .sweep import run_sweep
from .three_way import build_clusters, summarise_buckets


def available_providers(settings=None) -> list[Provider]:
    settings = settings or get_settings()
    providers = []
    if settings.grab_enabled:
        providers.append(Provider.GRAB)
    if settings.google_enabled:
        providers.append(Provider.GOOGLE)
    if settings.here_enabled:
        providers.append(Provider.HERE)
    return providers


def estimate_job(city: City, coverage: str, tile_radius_m: float, settings=None) -> dict:
    """Full cost picture for a city before anything is spent."""
    settings = settings or get_settings()
    radius = radius_for(city, coverage)
    tiles = len(cover_circle_with_tiles(city.lat, city.lng, radius, tile_radius_m))

    per_provider = {p.value: estimate_sweep(p, tiles, settings) for p in available_providers(settings)}

    totals: dict[str, int] = {}
    for provider in available_providers(settings):
        operation = sweep_operation(provider)
        totals[operation] = totals.get(operation, 0) + per_provider[provider.value]["calls_expected"]

    sweep_total = summarise(totals, settings)
    return {
        "city_code": city.code,
        "city": city.name,
        "province": city.province,
        "coverage": coverage.upper(),
        "radius_m": radius,
        "tile_radius_m": tile_radius_m,
        "tiles": tiles,
        "providers": per_provider,
        "sweep_calls_expected": sweep_total["total_calls"],
        "sweep_cost_expected_usd": sweep_total["cost_usd"],
        "cost_is_complete": sweep_total["cost_is_complete"],
        "unpriced_operations": sweep_total["unpriced_operations"],
        "probe_note": (
            "Probing is charged on top and cannot be estimated in advance: it depends "
            "on how many records fail to match, which is only known after the sweeps."
        ),
        "providers_configured": [p.value for p in available_providers(settings)],
    }


def create_job(
    db: Session,
    project: Project,
    city: City,
    coverage: str,
    tile_radius_m: float,
    user_id: int | None,
    radius_m: float | None = None,
) -> DiscoveryJob:
    """Create a city job. `radius_m` overrides the catalogue radius for the coverage
    level, which is how you fit a complete sweep of a smaller area inside a small
    budget rather than getting partial coverage of a large one."""
    settings = get_settings()
    radius = float(radius_m) if radius_m else radius_for(city, coverage)
    estimate = estimate_job(city, coverage, tile_radius_m, settings)

    area = SearchArea(
        project_id=project.id,
        city=city.name,
        name=f"{city.name} — {coverage.upper()} coverage",
        center_lat=city.lat,
        center_lng=city.lng,
        radius_m=radius,
    )
    db.add(area)
    db.flush()

    job = DiscoveryJob(
        project_id=project.id,
        city_code=city.code,
        city_name=city.name,
        province=city.province,
        coverage=coverage.upper(),
        radius_m=radius,
        tile_radius_m=tile_radius_m,
        area_id=area.id,
        est_cost_usd=estimate["sweep_cost_expected_usd"],
        created_by=user_id,
    )
    db.add(job)
    db.flush()
    return job


# Share of a job's budget the sweep stages may consume. The remainder is reserved for
# probing, which is the stage that actually licenses the "unique" claim. Without a
# reservation the sweep spends the whole budget and every record ends up UNRESOLVED —
# technically honest, commercially useless.
SWEEP_BUDGET_SHARE = 0.5


def job_spend_ceiling(settings) -> float:
    """The single USD budget for an entire job: sweeps and probes together.

    Stages must share one ceiling. Enforcing a separate ceiling per stage lets a job
    spend a multiple of the configured limit — a live Denpasar run set to $5 spent
    $7.25 that way, $2.24 on the sweep and $5.00 more on probing.
    """
    ceilings = [c for c in (settings.google_max_spend_per_run_usd, settings.grab_max_spend_per_run_usd) if c > 0]
    return min(ceilings) if ceilings else 0.0


def job_spend_to_date(db: Session, job: DiscoveryJob) -> tuple[float | None, dict[str, int]]:
    """Priced spend so far across every stage of this job, and the raw call counts."""
    settings = get_settings()
    totals: dict[str, int] = {}
    for run in db.scalars(select(DiscoveryRun).where(DiscoveryRun.id.in_(job.run_ids or [0]))).all():
        for operation, calls in (run.call_counts or {}).items():
            totals[operation] = totals.get(operation, 0) + calls
    for operation, calls in (job.probe_call_counts or {}).items():
        totals[operation] = totals.get(operation, 0) + calls
    return summarise(totals, settings)["cost_usd"], totals


def _checkpoint(db: Session) -> None:
    """Commit so far, making progress visible to anyone polling the job row.

    Flushing alone is not enough: uncommitted work is invisible to other database
    connections, so a poller would see the job sit at QUEUED for the whole run and
    then jump straight to FINISHED. Each stage is a natural commit boundary, and a
    partially-completed job is a legitimate state here anyway — a sweep that stops at
    its budget cap is recorded and reported, not rolled back.
    """
    db.commit()


def execute_job(db: Session, job: DiscoveryJob) -> DiscoveryJob:
    """Run the full pipeline for one city. Each stage records its own progress."""
    settings = get_settings()
    project = db.get(Project, job.project_id)
    area = db.get(SearchArea, job.area_id)
    providers = available_providers(settings)

    if not providers:
        job.status = RunStatus.FAILED
        job.error = "No provider credentials are configured"
        job.finished_at = utcnow()
        db.flush()
        return job

    job.status = RunStatus.RUNNING
    _checkpoint(db)

    try:
        # --- Stage 1 and 2: sweep each configured provider -----------------
        run_ids: list[int] = []
        for provider in providers:
            job.stage = {
                Provider.GRAB: JobStage.SWEEPING_GRAB,
                Provider.GOOGLE: JobStage.SWEEPING_GOOGLE,
                Provider.HERE: JobStage.SWEEPING_HERE,
            }[provider]
            _checkpoint(db)

            run = DiscoveryRun(
                project_id=project.id,
                provider=provider,
                area_ids=[area.id],
                params={"tile_radius_m": job.tile_radius_m, "job_id": job.id, "coverage": job.coverage},
                created_by=job.created_by,
            )
            db.add(run)
            db.flush()
            run_ids.append(run.id)
            job.run_ids = list(run_ids)
            db.flush()

            ceiling = job_spend_ceiling(settings)
            remaining = None
            if ceiling > 0:
                spent, _ = job_spend_to_date(db, job)
                sweep_allowance = ceiling * SWEEP_BUDGET_SHARE
                remaining = max(sweep_allowance - (spent or 0.0), 0.0)

            adapter = get_adapter(provider)
            run_sweep(db, run, adapter, [area], tile_radius_m=job.tile_radius_m,
                      job_id=job.id, max_spend_usd=remaining)
            job.api_calls += run.api_calls
            _checkpoint(db)

            if run.status == RunStatus.ABORTED_BUDGET:
                # Keep going: a partial sweep still yields a usable, clearly-labelled
                # result. The report's Method sheet records that coverage was capped.
                job.error = (run.error or "")[:2000]

        # --- Stage 3: bulk match -------------------------------------------
        job.stage = JobStage.MATCHING
        _checkpoint(db)
        run_bulk_match(db, project)

        # --- Stage 4: resolve for free, then pay for the rest ---------------
        # Area-coverage resolution reads only data already downloaded, so it runs
        # first: whatever it settles is a record the probe budget no longer has to
        # be spent on.
        job.stage = JobStage.PROBING
        _checkpoint(db)

        # Reciprocal probing is defined between Grab and Google. HERE participates in
        # the three-way resolution below but has no probe stage yet, so its absence
        # from a bucket is sweep-derived rather than probe-verified.
        if Provider.GRAB in providers and Provider.GOOGLE in providers:
            apply_verdicts(db, project.id)
            job.coverage_resolved = resolve_by_area_coverage(db, project, job_id=job.id)["resolved_unique"]
            _checkpoint(db)
            _run_probes(db, job, project, settings)

        # --- Stage 5: totals ------------------------------------------------
        _record_counts(db, job)
        job.stage = JobStage.FINISHED
        if job.status == RunStatus.RUNNING:
            job.status = RunStatus.COMPLETED
    except ProviderError as exc:
        job.status = RunStatus.FAILED
        job.error = str(exc)[:2000]
    except Exception as exc:  # noqa: BLE001 - the job row is the error report
        job.status = RunStatus.FAILED
        job.error = f"{type(exc).__name__}: {exc}"[:2000]

    job.finished_at = utcnow()
    db.flush()
    return job


def _run_probes(db: Session, job: DiscoveryJob, project: Project, settings) -> None:
    adapters = {
        Provider.GRAB: get_adapter(Provider.GOOGLE),
        Provider.GOOGLE: get_adapter(Provider.GRAB),
    }
    pending = {
        provider: [p for p in unprobed_places(db, project.id, provider) if p.job_id == job.id]
        for provider in (Provider.GRAB, Provider.GOOGLE)
    }
    job.probes_total = sum(len(v) for v in pending.values())
    db.flush()

    # Probing is charged on top of the sweep: each unmatched Grab record costs a Google
    # text search and vice versa. It draws down the SAME job budget the sweeps used, so
    # spend to date already includes them.
    spend_ceiling = job_spend_ceiling(settings)

    # Interleave the two providers rather than draining one list then the other.
    # Draining sequentially means a budget-limited run spends everything on the first
    # provider and reports zero unique records for the second — which reads as a
    # finding but is purely an ordering artifact. A live $5 Denpasar run reported
    # "Google only: 0" for exactly this reason.
    queue: list[tuple[Provider, ProviderPlace]] = []
    for grab_place, google_place in zip_longest(pending[Provider.GRAB], pending[Provider.GOOGLE]):
        if grab_place is not None:
            queue.append((Provider.GRAB, grab_place))
        if google_place is not None:
            queue.append((Provider.GOOGLE, google_place))

    probe_calls = 0
    counts = dict(job.probe_call_counts or {})
    for provider, place in queue:
        opposite = Provider.GOOGLE if provider == Provider.GRAB else Provider.GRAB
        operation = probe_operation(opposite)
        job.probe_call_counts = dict(counts)
        spent, _ = job_spend_to_date(db, job)
        over_budget = spend_ceiling > 0 and spent is not None and spent >= spend_ceiling
        if probe_calls >= job.max_probe_calls or over_budget:
            job.probe_call_counts = counts
            reason = (
                f"the ${spend_ceiling:.2f} spend ceiling" if over_budget
                else f"the {job.max_probe_calls} call cap"
            )
            job.error = (
                f"Probing stopped at {reason} with "
                f"{job.probes_total - job.probes_done} records still unprobed; "
                "those remain UNRESOLVED and are excluded from the unique counts"
            )
            job.status = RunStatus.ABORTED_BUDGET
            return
        if place.lat is None or place.lng is None:
            continue
        probe_place(db, project, place, adapters[provider], opposite, job_id=job.id)
        probe_calls += 1
        counts[operation] = counts.get(operation, 0) + 1
        job.probes_done += 1
        job.probe_call_counts = dict(counts)
        # Commit periodically so the probe counter advances for pollers without
        # paying a disk sync on every single record.
        if probe_calls % 10 == 0:
            db.commit()
        else:
            db.flush()
    job.probe_call_counts = counts
    db.commit()


def _record_counts(db: Session, job: DiscoveryJob) -> None:
    """Totals for the job: what was found, how many calls, what it cost.

    Sweep and probe costs are summed together, and an unpriced operation on either
    side leaves the total as None rather than understating it.
    """
    settings = get_settings()
    kpis = calculate_comparison_kpis(db, job.project_id, job_id=job.id)
    job.grab_only_count = kpis["GU_grab_only_verified"]
    job.google_only_count = kpis["KU_google_only_verified"]
    job.matched_count = kpis["M_matched"]
    job.unresolved_count = kpis["U_grab_unresolved"] + kpis["U_google_unresolved"]
    job.evidence_split = {
        "grab_probe": kpis["GU_grab_only_probe_verified"],
        "grab_area": kpis["GU_grab_only_area_verified"],
        "google_probe": kpis["KU_google_only_probe_verified"],
        "google_area": kpis["KU_google_only_area_verified"],
        "possible": kpis["P_grab_possible"] + kpis["P_google_possible"],
    }

    # Three-way presence, using the same clustering the area comparison uses. Runs
    # for any provider mix: with two providers it simply yields the pair buckets,
    # so the numbers stay consistent whether or not HERE took part.
    places = job_places(db, job.id)
    by_provider: dict[Provider, list] = {}
    for place in places:
        by_provider.setdefault(place.provider, []).append(place)
    job.provider_counts = {p.value: len(v) for p, v in by_provider.items()}
    if len(by_provider) > 1:
        clusters, _ = build_clusters(
            by_provider,
            auto_threshold=settings.match_auto_threshold,
            possible_threshold=settings.match_possible_threshold,
            max_distance_m=settings.match_max_distance_m,
        )
        job.bucket_counts = summarise_buckets(clusters)
        job.here_only_count = job.bucket_counts.get(PresenceBucket.HERE_ONLY.value, 0)
    else:
        job.bucket_counts = {}
        job.here_only_count = 0

    runs = list(db.scalars(select(DiscoveryRun).where(DiscoveryRun.id.in_(job.run_ids or [0]))).all())

    totals: dict[str, int] = {}
    for run in runs:
        for operation, calls in (run.call_counts or {}).items():
            totals[operation] = totals.get(operation, 0) + calls
    for operation, calls in (job.probe_call_counts or {}).items():
        totals[operation] = totals.get(operation, 0) + calls

    costed = summarise(totals, settings)
    job.actual_cost_usd = costed["cost_usd"]
    job.api_calls = sum(r.api_calls for r in runs) + job.probes_done
    db.flush()


def job_places(db: Session, job_id: int) -> list[ProviderPlace]:
    return list(
        db.scalars(
            select(ProviderPlace).where(ProviderPlace.job_id == job_id, ProviderPlace.in_scope.is_(True))
        ).all()
    )


def unique_counts(db: Session, job_id: int) -> dict[str, int]:
    places = job_places(db, job_id)
    return {
        "grab_only": sum(
            1 for p in places if p.provider == Provider.GRAB and p.verdict == UniquenessVerdict.UNIQUE_VERIFIED
        ),
        "google_only": sum(
            1 for p in places if p.provider == Provider.GOOGLE and p.verdict == UniquenessVerdict.UNIQUE_VERIFIED
        ),
    }
