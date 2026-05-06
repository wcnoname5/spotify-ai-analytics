"""Wizard state — collects environment readiness information."""
from __future__ import annotations


def collect_report() -> dict:
    """Collect a readiness report for the current environment.

    Returns a stub dict until the full implementation is in place.
    """
    return {
        "ready": False,
        "checks": {},
        "actions_needed": [],
        "message": "stub",
    }
