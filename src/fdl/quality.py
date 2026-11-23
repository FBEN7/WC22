"""M1 - Data-quality checks.

A data provider is judged on whether its data can be trusted. Each check below
takes a DuckDB connection to the warehouse and returns a DataFrame with ONE ROW
PER VIOLATION (empty DataFrame = check passed). Rows must carry `match_id` plus
whatever identifies the offending record, so an analyst can go and look at it.

`check_coordinates_in_bounds` is a worked example. The other checks raise
NotImplementedError: implement them until `pytest tests/test_m1_quality.py`
passes. Some of them find REAL defects in StatsBomb Open Data - the tests know
which ones.
"""

from __future__ import annotations

from collections.abc import Callable

import duckdb
import pandas as pd

Check = Callable[[duckdb.DuckDBPyConnection], pd.DataFrame]


def check_coordinates_in_bounds(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Every event location and pass / carry / shot end location lies on the 120 x 80 pitch.

    Worked example. Note what it does NOT check: 360 frames, where players seen
    just off the pitch are legitimately outside [0, 120] x [0, 80].
    """
    return con.execute("""
        WITH points AS (
            SELECT match_id, event_id, 'location' AS field, x, y FROM events
            UNION ALL SELECT match_id, event_id, 'pass.end_location', end_x, end_y FROM passes
            UNION ALL SELECT match_id, event_id, 'carry.end_location', end_x, end_y FROM carries
            UNION ALL SELECT match_id, event_id, 'shot.end_location', end_x, end_y FROM shots
        )
        SELECT match_id, event_id, field, x, y
        FROM points
        WHERE x IS NOT NULL
          AND (x < 0 OR x > 120 OR y < 0 OR y > 80)
        ORDER BY match_id, event_id
    """).df()


def check_score_reconciliation(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """The goals found in the events add up to the score in `matches`.

    One row per match whose events disagree with `matches.home_score / away_score`.
    Columns: match_id, home_score, away_score, home_goals_events, away_goals_events.

    Read the StatsBomb event spec before writing this: think about own goals and
    about penalty shoot-outs.
    """
    raise NotImplementedError("M1: check_score_reconciliation")


def check_event_order(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Within a match and period, timestamps never go backwards as `idx` increases.

    One row per event whose timestamp is earlier than the event just before it
    (by idx) in the same period. Columns: match_id, period, idx, event_id,
    type_name, timestamp, previous_timestamp.
    """
    raise NotImplementedError("M1: check_event_order")


def check_related_events_reciprocal(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """If event A lists B in `related_events`, B lists A too.

    One row per non-reciprocated link. Columns: match_id, event_id,
    related_event_id. Before you decide something is a defect, find out whether
    the spec makes some links one-way by design (look at the data by event type).
    """
    raise NotImplementedError("M1: check_related_events_reciprocal")


def check_players_in_lineups(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Every (match, team, player) that appears in events - as the actor or as a
    pass recipient - appears in that match's lineup for that team.

    One row per missing (match_id, team_id, player_id). Columns: match_id,
    team_id, player_id, player_name.
    """
    raise NotImplementedError("M1: check_players_in_lineups")


def check_lineup_spells(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """A player's position spells, taken in `spell_order`, are chronological.

    Compare points in time as (period, clock), never the clock alone. A spell is
    a violation when it ends before it starts, starts before the previous spell
    ended, or follows a spell that never ended (only the last spell may have a
    NULL `to_clock`). One row per offending spell. Columns: match_id, team_id,
    player_id, player_name, spell_order, from_clock, from_period, to_clock,
    to_period.
    """
    raise NotImplementedError("M1: check_lineup_spells")


CHECKS: dict[str, Check] = {
    "coordinates_in_bounds": check_coordinates_in_bounds,
    "score_reconciliation": check_score_reconciliation,
    "event_order": check_event_order,
    "related_events_reciprocal": check_related_events_reciprocal,
    "players_in_lineups": check_players_in_lineups,
    "lineup_spells": check_lineup_spells,
}


def run_all(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Summary table: one row per check, with its status and violation count."""
    rows = []
    for name, check in CHECKS.items():
        try:
            n = len(check(con))
            rows.append({"check": name, "status": "PASS" if n == 0 else "FAIL", "violations": n})
        except NotImplementedError:
            rows.append({"check": name, "status": "TODO", "violations": None})
    return pd.DataFrame(rows)


def violations(con: duckdb.DuckDBPyConnection, name: str) -> pd.DataFrame:
    return CHECKS[name](con)
