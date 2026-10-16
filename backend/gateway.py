"""Application entry point.

The discovery engine is served at the root. There is no second application: the
customer demonstration workspace that used to live here was removed, along with
its seeded five-city dataset, so nothing in this deployment presents pre-canned
records as findings.
"""
from discovery_engine.main import app

__all__ = ["app"]
