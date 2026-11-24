-- 01 - Minutes played.
--
-- View name: minutes_played. One row per player who was on the pitch:
--   match_id, team_id, player_id, player_name, minutes (DOUBLE)
--
-- Definition (implement exactly this - the tests check numbers):
--   * Match time is REAL elapsed time, stoppage time included, taken from the
--     events: a period lasts as long as the `ts_seconds` of its 'Half End' event
--     (take the max of the two teams' Half End). Periods 1-4 only: the
--     shoot-out (period 5) is not playing time.
--   * An event's absolute time = length of all earlier periods + its ts_seconds.
--   * A player comes on at kick-off (starting XI) or at the 'Substitution'
--     event that brings him on (details->'$.substitution.replacement.id').
--   * He goes off at his own 'Substitution' event, at his sending-off (card
--     'Red Card' or 'Second Yellow', in a 'Foul Committed' or 'Bad Behaviour'
--     event), or at the end of the last period played.
--   * Temporary absences ('Player Off' / 'Player On', e.g. treatment) are ignored.
--   * minutes = (time off - time on) / 60. Unused substitutes get no row.
--
-- Do NOT use lineups.from_clock / to_clock for this: M1 shows why.
-- Tip: write it as a chain of CTEs (period_length, period_offset, on, off, ...).

WITH period_lengths AS (
    SELECT match_id,
           period,
           max(ts_seconds) AS seconds
    FROM events
    WHERE type_name = 'Half End'
      AND period BETWEEN 1 AND 4
    GROUP BY match_id, period
),
period_timeline AS (
    SELECT match_id,
           period,
           seconds,
           coalesce(sum(seconds) OVER (
               PARTITION BY match_id
               ORDER BY period
               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
           ), 0) AS offset_seconds
    FROM period_lengths
),
match_end AS (
    SELECT match_id,
           max(period) AS last_period,
           sum(seconds) AS match_seconds
    FROM period_lengths
    GROUP BY match_id
),
starts AS (
    -- Starting XI players
    SELECT l.match_id, l.team_id, l.player_id, l.player_name,
           0.0 AS on_seconds
    FROM lineups l
    WHERE l.spell_order = 0
      AND l.start_reason = 'Starting XI'

    UNION ALL

    -- Replacement players enter at the substitution event
    SELECT e.match_id,
           e.team_id,
           CAST(details->>'$.substitution.replacement.id' AS BIGINT) AS player_id,
           details->>'$.substitution.replacement.name' AS player_name,
           pt.offset_seconds + e.ts_seconds AS on_seconds
    FROM events e
    JOIN period_timeline pt
      ON pt.match_id = e.match_id AND pt.period = e.period
    WHERE e.type_name = 'Substitution'
),
stops AS (
    -- Substituted players leave at their substitution event
    SELECT e.match_id, e.team_id, e.player_id,
           pt.offset_seconds + e.ts_seconds AS off_seconds
    FROM events e
    JOIN period_timeline pt
      ON pt.match_id = e.match_id AND pt.period = e.period
    WHERE e.type_name = 'Substitution'

    UNION ALL

    -- Red cards and second yellows
    SELECT e.match_id, e.team_id, e.player_id,
           pt.offset_seconds + e.ts_seconds AS off_seconds
    FROM events e
    JOIN period_timeline pt
      ON pt.match_id = e.match_id AND pt.period = e.period
    WHERE (
        COALESCE(CAST(details->>'$.foul_committed.card.name' AS VARCHAR), '')
        IN ('Red Card', 'Second Yellow')
        OR COALESCE(CAST(details->>'$.bad_behaviour.card.name' AS VARCHAR), '')
        IN ('Red Card', 'Second Yellow')
    )
),
players AS (
    SELECT s.match_id, s.team_id, s.player_id, s.player_name,
           s.on_seconds,
           coalesce(min(st.off_seconds), me.match_seconds) AS off_seconds
    FROM starts s
    JOIN match_end me ON me.match_id = s.match_id
    LEFT JOIN stops st
      ON st.match_id = s.match_id
     AND st.team_id = s.team_id
     AND st.player_id = s.player_id
     AND st.off_seconds >= s.on_seconds
    GROUP BY s.match_id, s.team_id, s.player_id, s.player_name,
             s.on_seconds, me.match_seconds
)
SELECT match_id, team_id, player_id, player_name,
       (off_seconds - on_seconds) / 60.0 AS minutes
FROM players
WHERE off_seconds > on_seconds
ORDER BY match_id, team_id, player_id
