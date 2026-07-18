"""MCP prompt definitions for Spotify-Analytic MCP."""
from textwrap import dedent
from typing import Annotated, Literal

from pydantic import Field

from fastmcp import FastMCP
from fastmcp.prompts import Message

from spotify_core.db.queries import get_data_range
from spotify_mcp.config import DB_PATH

LANGUAGE_NAMES = {"en": "English", "cht": "Traditional Chinese (zh-TW)"}

REPORT_PROMPT_TEMPLATE = dedent("""
    Respond entirely in {language_name}. Keep tool names, date strings, and
    artist/track names as-is — do not translate them.

    Generate a Spotify listening report covering {window_desc}.

    ## Workflow

    ### 1. Setup check
    Call `setup_check`. If `ready: false`, call `setup`. Proceed with whatever local data is
    available — don't block on `sync_history` errors.

    ### 2. Data fetch (one call per window)
    Time windows to analyze: {windows}

    For each (start_date, end_date) window:
    - `get_listening_summary(start_date, end_date)`
    - `get_top_artists(start_date, end_date, limit=15)`
    - `get_top_tracks(start_date, end_date, limit=10)`
    - `get_listening_patterns(start_date, end_date)`

    ### 3. Written analysis
    Per-period paragraph:
    - Dominant artists and inferred genres (named, not generic)
    - Listening behavior (skip rate, avg plays/day, peak hour/day)
    - What's new or surprising vs the prior period

    Cross-period observations:
    - Direction of taste shift (deeper niche / broader exploration / regional shift)
    - Consistent anchor artists across all periods
    - Behavioral trends

    Tone: analytical and personal — reference actual artist names. No filler.

    ### 4. Optional visualization
    If the client supports rendering charts or interactive widgets (e.g. Claude Desktop artifacts),
    you may add visualizations such as annual plays, diversity (unique artists/tracks), behavior
    (avg plays/day, skip rate), and top-artists bars. Skip this step entirely for clients that
    only render text.

    ## Edge cases
    - Empty DB → suggest to run setup or sync history then exit gracefully.
    - Single period only → render a single-period summary, skip trend comparisons.
    - User asks for genre breakdown → there is no genre field; infer from artist names and note
      the caveat.
    - User wants a recap playlist → use `get_top_tracks` (results include `track_id` URIs) then `create_playlist`.

    ## After delivering
    Offer follow-ups: month-level zoom, time-of-day breakdown, or recap playlist generation.
""").strip()


def register_prompts(mcp: FastMCP) -> None:
    """Register all MCP prompts on the given server."""

    @mcp.prompt(
        name="generate_report",
        title="Listening Report Generator",
        description=(
            "Generate a Spotify listening report with written taste-change analysis. (Defaults to the last 3 calendar years) "
            "Pulls from the local listening-history DB."
        ),
    )
    def generate_report(
        year_span: Annotated[
            str,
            Field(
                description=(
                    "Number of recentyears to analyze (range 1-10) "
                )
            ),
        ] = "3",
        start: Annotated[
            str,
            Field(
                description=(
                    "Custom range start date in YYYY-MM-DD format. Optional."
                )
            ),
        ] = "",
        end: Annotated[
            str,
            Field(
                description=(
                    "Custom range end date in YYYY-MM-DD format. Optional."
                )
            ),
        ] = "",
        language: Annotated[
            Literal["en", "cht"],
            Field(
                description=(
                    "Output language: 'cht' for Traditional Chinese (Default), 'en' for English"
                )
            ),
        ] = "cht",
    ) -> list[Message]:
        """Build a workflow prompt for an N-year (or custom-range) listening report."""
        from datetime import datetime
        if language not in ("en", "cht"):
            raise ValueError(f"Invalid language '{language}'. Must be 'en' or 'cht'.")
        warnings: list[str] = []
        if language not in LANGUAGE_NAMES:
            warnings.append(f"Unsupported language '{language}', defaulting to Traditional Chinese.")
            language = "cht"
        # Coerce everything to string up front — guards against None / int / etc.
        years_s = str(year_span) if year_span is not None else "3"
        start_s = str(start) if start else ""
        end_s = str(end) if end else ""

        windows: list[tuple[str, str]] | None = None
        window_desc = ""

        # Inspect available data range up front so we can fill in missing
        # start/end and clamp out-of-range windows. get_data_range returns ISO
        # timestamps (YYYY-MM-DDTHH:MM:SSZ); take the date portion only.
        db_range = get_data_range(DB_PATH)
        db_earliest = db_range[0][:10] if db_range and db_range[0] else None
        db_latest = db_range[1][:10] if db_range and db_range[1] else None
        # --- Custom range branch: triggered if user supplied either side ---
        if start_s or end_s:
            valid = True
            for label, val in (("start", start_s), ("end", end_s)):
                if not val:
                    continue
                try:
                    datetime.strptime(val, "%Y-%m-%d")
                except ValueError:
                    warnings.append(f"Invalid {label} date '{val}', ignoring custom range.")
                    valid = False
                    break

            eff_start, eff_end = start_s, end_s

            # No start given → default to DB earliest (if any)
            if valid and not eff_start:
                if db_earliest:
                    eff_start = db_earliest
                else:
                    warnings.append("`start` not given and DB has no data; falling back to year_span.")
                    valid = False

            # No end given → default to DB latest (if any)
            if valid and not eff_end:
                if db_latest:
                    eff_end = db_latest
                else:
                    warnings.append("`end` not given and DB has no data; falling back to year_span.")
                    valid = False
            # edge case: catch "end" before "start"
            if valid and eff_start >= eff_end:
                warnings.append(
                    f"`start` '{eff_start}' is not before `end` '{eff_end}', ignoring custom range."
                )
                valid = False

            if valid:
                if db_earliest and eff_start < db_earliest:
                    warnings.append(
                        f"`start` '{eff_start}' precedes earliest played date '{db_earliest}', clamping."
                    )
                    eff_start = db_earliest
                if db_latest and eff_end > db_latest:
                    warnings.append(
                        f"`end` '{eff_end}' exceeds latest played date '{db_latest}', clamping."
                    )
                    eff_end = db_latest
                windows = [(eff_start, eff_end)]
                window_desc = f"{eff_start} → {eff_end}"

        # --- N-year branch (also reached when custom range was rejected) ---
        if windows is None:
            try:
                n_years = int(years_s)
            except ValueError:
                warnings.append(f"Invalid years value '{years_s}', defaulting to 3.")
                n_years = 3

            if not (1 <= n_years <= 10):
                warnings.append(f"years={n_years} out of range [1–10], clamping to 3.")
                n_years = 3

            current_year = datetime.now().year
            candidate = [
                (f"{y}-01-01", f"{y}-12-31")
                for y in range(current_year - n_years, current_year)
            ]

            if db_earliest or db_latest:
                clamped: list[tuple[str, str]] = []
                for s, e in candidate: # start/end of the year window
                    if db_earliest and e < db_earliest:
                        continue
                    if db_latest and s > db_latest:
                        continue
                    if db_earliest and s < db_earliest:
                        s = db_earliest
                    if db_latest and e > db_latest:
                        e = db_latest
                    clamped.append((s, e))
                if len(clamped) < len(candidate):
                    warnings.append(
                        f"Some {n_years}-year windows lie outside available data "
                        f"({db_earliest or '?'} → {db_latest or '?'}); using {len(clamped)} window(s)."
                    )
                windows = clamped
                window_desc = (
                    f"the last {n_years} calendar years "
                    f"(clamped to available data {db_earliest or '?'} → {db_latest or '?'})"
                )
            else:
                windows = candidate
                window_desc = f"the last {n_years} calendar years"

            if not windows:
                warnings.append(
                    "No analyzable windows after clamping to available data; "
                    "consider running `import_history_from_json` or `sync_history`."
                )

        messages: list[Message] = []
        if warnings:
            messages.append(Message(
                "Some prompt arguments were invalid and have been corrected. "
                "Please mention these briefly to the user, then proceed with the "
                "analysis using the corrected values below.\n\n"
                + "\n".join(f"- {w}" for w in warnings)
            ))
        messages.append(Message(
            REPORT_PROMPT_TEMPLATE.format(
                language_name=LANGUAGE_NAMES[language],
                window_desc=window_desc,
                windows=windows,
            )
        ))
        return messages

