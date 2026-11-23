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

-- TODO: replace this query, then delete this line.
SELECT NULL::BIGINT AS match_id, NULL::BIGINT AS team_id, NULL::BIGINT AS player_id,
       NULL::VARCHAR AS player_name, NULL::DOUBLE AS minutes
WHERE false
