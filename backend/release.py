"""Railway entry point: prepare the database, then serve.

On first boot this waits for the database, builds the schema and loads the
bundled discovery snapshot (the data already fetched from the providers) into an
empty engine, so a fresh deployment comes up populated rather than blank. The
load is idempotent: a redeploy against a database that already holds data skips
it and only refreshes the administrator login from the environment.
"""
from __future__ import annotations

import os

import uvicorn


def main() -> None:
    # Imported here so the full database preparation runs before the port binds.
    from discovery_engine.seed import run_seed

    run_seed()

    uvicorn.run(
        "gateway:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
