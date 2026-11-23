-- 03 - PPDA (passes allowed per defensive action), a pressing-intensity metric.
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

-- TODO: replace this query, then delete this line.
SELECT NULL::BIGINT AS match_id, NULL::BIGINT AS team_id, NULL::VARCHAR AS team_name,
       NULL::BIGINT AS opp_passes, NULL::BIGINT AS def_actions, NULL::DOUBLE AS ppda
WHERE false
