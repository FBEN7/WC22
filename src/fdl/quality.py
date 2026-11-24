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
    """The goals found in events reconcile with match scores, excluding shoot-outs."""
    return con.execute("""
        WITH shot_goals AS (
            SELECT e.match_id, e.team_id, count(*) AS goals
            FROM shots s
            JOIN events e USING (event_id)
            WHERE s.outcome = 'Goal' AND e.period != 5
            GROUP BY e.match_id, e.team_id
        ),
        own_goals AS (
            SELECT match_id, team_id, count(*) AS goals
            FROM events
            WHERE type_name = 'Own Goal For'
            GROUP BY match_id, team_id
        ),
        goal_counts AS (
            SELECT match_id, team_id, sum(goals) AS goals
            FROM (
                SELECT * FROM shot_goals
                UNION ALL
                SELECT * FROM own_goals
            )
            GROUP BY match_id, team_id
        ),
        totals AS (
            SELECT m.match_id, m.home_team_id, m.away_team_id,
                   m.home_score, m.away_score,
                   coalesce(g_h.goals, 0) AS home_goals_events,
                   coalesce(g_a.goals, 0) AS away_goals_events
            FROM matches m
            LEFT JOIN goal_counts g_h
              ON g_h.match_id = m.match_id AND g_h.team_id = m.home_team_id
            LEFT JOIN goal_counts g_a
              ON g_a.match_id = m.match_id AND g_a.team_id = m.away_team_id
        )
        SELECT match_id, home_score, away_score,
               home_goals_events, away_goals_events
        FROM totals
        WHERE home_goals_events + away_goals_events
              != home_score + away_score
        ORDER BY match_id
    """).df()


def check_event_order(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Within a match and period, timestamps never go backwards as `idx` increases."""
    return con.execute("""
        WITH ordered AS (
            SELECT *, lag(timestamp) OVER (
                       PARTITION BY match_id, period ORDER BY idx
                   ) AS previous_timestamp,
                   lag(ts_seconds) OVER (
                       PARTITION BY match_id, period ORDER BY idx
                   ) AS previous_seconds
            FROM events
        )
        SELECT match_id, period, idx, event_id, type_name,
               timestamp, previous_timestamp
        FROM ordered
        WHERE previous_timestamp IS NOT NULL
          AND ts_seconds < previous_seconds
        ORDER BY match_id, period, idx
    """).df()


def check_related_events_reciprocal(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Report non-reciprocal links, excluding documented one-way links in the data model."""
    return con.execute("""
        WITH links AS (
            SELECT e.match_id, e.event_id, e.type_name,
                   unnest(e.related_events) AS related_event_id
            FROM events e
        )
        SELECT l.match_id, l.event_id, l.related_event_id
        FROM links l
        JOIN events target ON target.event_id = l.related_event_id
        WHERE NOT EXISTS (
            SELECT 1
            FROM events reverse
            WHERE reverse.event_id = l.related_event_id
              AND l.event_id IN (SELECT unnest(reverse.related_events))
        )
          AND NOT (l.type_name = 'Carry' AND target.type_name = 'Pass')
          AND NOT (l.type_name = 'Pass' AND target.type_name = 'Carry')
          AND l.type_name != 'Carry'
        ORDER BY l.match_id, l.event_id, l.related_event_id
    """).df()


def check_players_in_lineups(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Every event actor and pass recipient must appear in its team's lineup."""
    return con.execute("""
        WITH players AS (
            SELECT match_id, team_id, player_id, player_name
            FROM events
            WHERE player_id IS NOT NULL
            UNION
            SELECT e.match_id, e.team_id, p.recipient_id, p.recipient_name
            FROM passes p
            JOIN events e USING (event_id)
            WHERE p.recipient_id IS NOT NULL
        )
        SELECT DISTINCT p.match_id, p.team_id, p.player_id, p.player_name
        FROM players p
        LEFT JOIN lineups l
          ON l.match_id = p.match_id
         AND l.team_id = p.team_id
         AND l.player_id = p.player_id
        WHERE l.player_id IS NULL
        ORDER BY p.match_id, p.team_id, p.player_id
    """).df()


def check_lineup_spells(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Position spells are chronological and non-overlapping by period and clock."""
    return con.execute("""
        WITH clock_seconds AS (
            SELECT *,
                   try_cast(split_part(from_clock, ':', 1) AS DOUBLE) * 60
                   + try_cast(split_part(from_clock, ':', 2) AS DOUBLE)
                     AS from_seconds,
                   CASE WHEN to_clock IS NULL THEN NULL ELSE
                       try_cast(split_part(to_clock, ':', 1) AS DOUBLE) * 60
                       + try_cast(split_part(to_clock, ':', 2) AS DOUBLE)
                   END AS to_seconds
            FROM lineups
            WHERE spell_order IS NOT NULL
        ),
        checked AS (
            SELECT s.*,
                   lag(to_clock) OVER (
                       PARTITION BY match_id, team_id, player_id
                       ORDER BY spell_order
                   ) AS prev_to_clock,
                   lag(to_period) OVER (
                       PARTITION BY match_id, team_id, player_id
                       ORDER BY spell_order
                   ) AS prev_to_period,
                   lag(to_seconds) OVER (
                       PARTITION BY match_id, team_id, player_id
                       ORDER BY spell_order
                   ) AS prev_to_seconds
            FROM clock_seconds s
        )
        SELECT match_id, team_id, player_id, player_name, spell_order,
               from_clock, from_period, to_clock, to_period
        FROM checked
        WHERE (to_period IS NOT NULL AND (
                   from_period > to_period
                   OR (from_period = to_period AND from_seconds > to_seconds)
               ))
           OR (spell_order > 0 AND prev_to_clock IS NULL)
           OR (prev_to_period IS NOT NULL AND (
                   from_period < prev_to_period
                   OR (from_period = prev_to_period AND from_seconds < prev_to_seconds)
               ))
        ORDER BY match_id, team_id, player_id, spell_order
    """).df()


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
