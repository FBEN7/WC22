-- 03 - PPDA (passes allowed per defensive action).
--
-- View name: ppda. One row per (match_id, team_id) - the PRESSING team:
--   match_id, team_id, team_name, opp_passes, def_actions, ppda
--
-- Definition:
--   * opp_passes: passes by the OPPONENT that start in the opponent's own
--     defensive 60% (strictly less than 60% of the pitch length from its own
--     goal line), set pieces excluded (Corner, Free Kick, Throw-in, Goal Kick,
--     Kick Off), period 5 excluded.
--   * def_actions: the pressing team's 'Interception', 'Foul Committed' and
--     'Duel' events whose duel type is 'Tackle', made in ITS attacking 60%
--     (at least 40% of the pitch length from its own goal line).
--   * ppda = opp_passes / def_actions (low = intense pressing).
--
-- Trap: StatsBomb gives every event in the frame of the team performing it,
-- always attacking towards x = 120. Work out which x threshold applies to the
-- opponent's passes and which to the pressing team's actions.

WITH opp_passes AS (
    SELECT e.match_id,
           CASE WHEN e.team_id = m.home_team_id THEN m.away_team_id ELSE m.home_team_id END AS pressing_team_id,
           e.team_id AS opponent_team_id,
           count(*) AS opp_passes
    FROM passes p
    JOIN events e USING (event_id)
    JOIN matches m ON m.match_id = e.match_id
    WHERE e.period != 5
      AND e.team_id IN (m.home_team_id, m.away_team_id)
      AND e.x < 72.0
      AND coalesce(p.pass_type, '') NOT IN
          ('Corner', 'Free Kick', 'Throw-in', 'Goal Kick', 'Kick Off')
    GROUP BY e.match_id, pressing_team_id, opponent_team_id
),
def_actions AS (
    SELECT e.match_id, e.team_id,
           count(*) AS def_actions
    FROM events e
    WHERE e.period != 5
      AND e.x >= 48.0
      AND (
          e.type_name = 'Interception'
          OR e.type_name = 'Foul Committed'
          OR (
              e.type_name = 'Duel'
              AND json_extract_string(details, '$.duel.type.name') = 'Tackle'
          )
      )
    GROUP BY e.match_id, e.team_id
)
SELECT m.match_id,
       m.team_id,
       m.team_name,
       coalesce(op.opp_passes, 0) AS opp_passes,
       coalesce(d.def_actions, 0) AS def_actions,
       CASE WHEN coalesce(d.def_actions, 0) = 0 THEN NULL
            ELSE op.opp_passes * 1.0 / d.def_actions
       END AS ppda
FROM (
    SELECT match_id, home_team_id AS team_id, home_team_name AS team_name FROM matches
    UNION ALL
    SELECT match_id, away_team_id AS team_id, away_team_name AS team_name FROM matches
) m
LEFT JOIN opp_passes op
  ON op.match_id = m.match_id
 AND op.pressing_team_id = m.team_id
LEFT JOIN def_actions d
  ON d.match_id = m.match_id
 AND d.team_id = m.team_id
ORDER BY m.match_id, m.team_id
