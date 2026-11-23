-- 00 - WORKED EXAMPLE: shots, goals and xG per team and match.
--
-- View name: team_shots (the file name without its number).
-- One row per (match_id, team_id).
--
-- Things worth noticing:
--   * period 5 is the penalty shoot-out: it is not part of the match, so it is excluded;
--   * penalties stay in, but are also counted separately (they inflate xG);
--   * own goals are NOT shots, so `goals` here can differ from the final score.

SELECT
    e.match_id,
    e.team_id,
    e.team_name,
    count(*)                                                    AS shots,
    count(*) FILTER (WHERE s.outcome IN ('Goal', 'Saved', 'Saved To Post'))
                                                                AS shots_on_target,
    count(*) FILTER (WHERE s.outcome = 'Goal')                  AS goals,
    count(*) FILTER (WHERE s.shot_type = 'Penalty')             AS penalties,
    round(sum(s.statsbomb_xg), 2)                               AS xg,
    round(sum(s.statsbomb_xg) FILTER (WHERE s.shot_type <> 'Penalty'), 2)
                                                                AS npxg
FROM events e
JOIN shots s USING (event_id)
WHERE e.period < 5
GROUP BY ALL
ORDER BY e.match_id, e.team_id
