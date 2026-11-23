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

-- TODO: replace this query, then delete this line.
SELECT NULL::BIGINT AS player_id, NULL::VARCHAR AS player_name, NULL::BIGINT AS team_id,
       NULL::VARCHAR AS team_name, NULL::BIGINT AS matches, NULL::DOUBLE AS minutes,
       NULL::BIGINT AS passes, NULL::BIGINT AS completed, NULL::DOUBLE AS completion_pct,
       NULL::BIGINT AS progressive, NULL::DOUBLE AS passes_p90, NULL::DOUBLE AS progressive_p90
WHERE false
