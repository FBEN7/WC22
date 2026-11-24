-- 11 - Open-play ball regains, where they happened and what they produced.
--
-- View name: regains. One row per possession that a team WON from the opponent in open play:
--   match_id, possession, team_id, start_type, x, y, is_high, state, shots, npxg, goal
--
--   * A regain is a possession whose team differs from the previous possession's team and
--     whose first located event (by that team) is not a restart: throw-ins, free kicks,
--     goal kicks, corners, kick-offs, goalkeeper actions and drop balls are excluded.
--   * x, y: location of that first event, in the regaining team's frame (attacking x = 120).
--   * is_high: won within 40 metres of the opponent's goal line (x >= 120 - 40 / 0.9144),
--     the threshold Opta uses for "high turnovers". Counts are NOT comparable with Opta's,
--     whose possession / sequence definition differs.
--   * shots, npxg, goal: non-penalty shots by the regaining team in that possession.

WITH poss AS (
    SELECT match_id, possession, any_value(possession_team_id) AS team_id
    FROM events WHERE period < 5
    GROUP BY ALL
),
seq AS (
    SELECT *, lag(team_id) OVER (PARTITION BY match_id ORDER BY possession) AS prev_team_id
    FROM poss
),
first_own AS (
    SELECT s.match_id, s.possession, s.team_id, s.prev_team_id, e.event_id, e.x, e.y,
           coalesce(p.pass_type, e.type_name) AS start_type
    FROM seq s
    JOIN events e
      ON e.match_id = s.match_id AND e.possession = s.possession
     AND e.team_id = s.team_id AND e.x IS NOT NULL
    LEFT JOIN passes p USING (event_id)
    QUALIFY row_number() OVER (PARTITION BY s.match_id, s.possession ORDER BY e.idx) = 1
),
possession_shots AS (
    SELECT e.match_id, e.possession, e.team_id,
           count(*) AS shots, sum(s.statsbomb_xg) AS npxg, max((s.outcome = 'Goal')::INT) AS goal
    FROM events e JOIN shots s USING (event_id)
    WHERE e.period < 5 AND s.shot_type <> 'Penalty'
    GROUP BY ALL
)
SELECT f.match_id, f.possession, f.team_id, f.start_type, f.x, f.y,
       f.x >= 120 - 40 / 0.9144 AS is_high,
       g.state,
       coalesce(ps.shots, 0) AS shots,
       coalesce(ps.npxg, 0) AS npxg,
       coalesce(ps.goal, 0) AS goal
FROM first_own f
JOIN game_state g USING (event_id)
LEFT JOIN possession_shots ps
  ON ps.match_id = f.match_id AND ps.possession = f.possession AND ps.team_id = f.team_id
WHERE f.prev_team_id IS NOT NULL
  AND f.prev_team_id <> f.team_id
  AND f.start_type NOT IN ('Throw-in', 'Free Kick', 'Goal Kick', 'Corner', 'Kick Off',
                           'Goal Keeper', 'Referee Ball-Drop', 'Shot')
