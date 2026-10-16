from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from .config import get_settings
from .database import Base, engine, ensure_schema
from .routers import (
    area, audit, auth, candidates, comparison, dashboard, discovery, exports, imports, jobs, projects,
)

settings = get_settings()
ensure_schema()
Base.metadata.create_all(bind=engine)


def _close_interrupted_sweeps() -> None:
    """A sweep cannot survive a restart, so any row still RUNNING is orphaned."""
    from .database import SessionLocal
    from .services.area_sweep import mark_interrupted_sweeps

    db = SessionLocal()
    try:
        closed = mark_interrupted_sweeps(db)
        if closed:
            print(f"Closed {closed} area sweep(s) interrupted by a previous shutdown.")
    finally:
        db.close()


_close_interrupted_sweeps()

app = FastAPI(
    title="JSAN GeoDiscover API",
    version="5.0.0",
    description="Live Google/Grab discovery, comparison, reciprocal probing and budget-controlled cost engine",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "healthy", "service": "JSAN GeoDiscover API", "version": "5.0.0"}

for router in [auth.router, projects.router, imports.router, candidates.router, dashboard.router,
               exports.router, audit.router, discovery.router, comparison.router, jobs.router,
               area.router]:
    app.include_router(router, prefix="/api/v1")


class RevalidatingStaticFiles(StaticFiles):
    """Static files that the browser must revalidate on every request.

    Plain StaticFiles sends only ETag and Last-Modified. With no Cache-Control the
    browser falls back to heuristic caching and may keep serving an old app.js from
    disk without asking the server, so interface changes appear not to have shipped.
    "no-cache" does not disable caching: the browser still stores the file and still
    gets a cheap 304 when nothing changed, it just always asks first.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


app.mount(
    "/",
    RevalidatingStaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="frontend",
)
