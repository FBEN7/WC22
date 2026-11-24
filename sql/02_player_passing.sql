-- 02 - Player passing profile, per 90 minutes.
--
-- View name: player_passing. One row per (player_id, team_id) over all matches:
--   player_id, player_name, team_id, team_name, matches, minutes,
--   passes, completed, completion_pct, progressive, passes_p90, progressive_p90
--
-- Definitions:
--   * passes: every Pass event of the player, period 5 excluded.
--   * completed: passes.outcome IS NULL (StatsBomb leaves the outcome empty on success).
--   * completion_pct: 100 * completed / passes.
--   * progressive: completed, NOT a set piece (pass_type not in Corner, Free Kick,
--     Throw-in, Goal Kick, Kick Off), and the end point is at least 25% closer
--     to the centre of the goal being attacked (120, 40) than the start point.
--   * minutes: from the `minutes_played` view (exercise 01); *_p90 = count / minutes * 90.
--   * matches: number of matches with minutes > 0.
--
-- Question to answer in your write-up: why is passes_p90 misleading for a player
-- with 25 minutes, and what threshold do analysts use?

WITH player_minutes AS (
    SELECT player_id, team_id,
           sum(minutes) AS minutes,
           count(DISTINCT match_id) AS matches
    FROM minutes_played
    GROUP BY player_id, team_id
),
pass_stats AS (
    SELECT e.player_id,
           e.team_id,
           e.player_name,
           e.team_name,
           count(*) AS passes,
           count(*) FILTER (WHERE p.outcome IS NULL) AS completed,
           count(*) FILTER (
               WHERE p.outcome IS NULL
                 AND coalesce(p.pass_type, '') NOT IN
                     ('Corner', 'Free Kick', 'Throw-in', 'Goal Kick', 'Kick Off')
                 AND sqrt(power(120.0 - p.end_x, 2) + power(40.0 - p.end_y, 2))
                     <= 0.75 * sqrt(power(120.0 - e.x, 2) + power(40.0 - e.y, 2))
           ) AS progressive
    FROM passes p
    JOIN events e USING (event_id)
    WHERE e.period != 5
    GROUP BY e.player_id, e.team_id, e.player_name, e.team_name
)
SELECT m.player_id,
       s.player_name,
       m.team_id,
       s.team_name,
       m.matches,
       m.minutes,
       s.passes,
       s.completed,
       100.0 * s.completed / s.passes AS completion_pct,
       s.progressive,
       s.passes / m.minutes * 90.0 AS passes_p90,
       s.progressive / m.minutes * 90.0 AS progressive_p90
FROM player_minutes m
JOIN pass_stats s
  ON s.player_id = m.player_id
 AND s.team_id = m.team_id
WHERE s.passes > 0
ORDER BY m.player_id, m.team_id
