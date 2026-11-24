-- 12 - One row per team and match: pressing intensity, what it won, and the match outcome in xG.
--
-- View name: team_match_pressing.
--
-- Pressing intensity
--   ppda           opponent open-play passes in its own defensive 60% / this team's defensive
--                  actions (tackles, interceptions, fouls) in its attacking 60%. Same
--                  definition as the `ppda` view (03). LOWER = more intense pressing.
--   ppda_level     the same, counting only events played while the score was level.
--   possession     share of the match's open-play passes made by this team
--                  (possession_level: the same while the score was level).
-- What the press wins
--   regains, high_regains (within 40 m of goal), high_regain_npxg (xG of the possessions
--   started by a high regain).
-- Outcome (non-penalty xG from StatsBomb's model, periods 1-4)
--   npxg, npxga, npxgd = npxg - npxga; *_level = shots taken while the score was level.

WITH teams AS (
    SELECT m.match_id, c.competition_name || ' ' || c.season_name AS tournament,
           m.home_team_id AS team_id, m.home_team_name AS team_name,
           m.away_team_id AS opp_id, m.away_team_name AS opp_name
    FROM matches m JOIN competitions c USING (competition_id, season_id)
    UNION ALL
    SELECT m.match_id, c.competition_name || ' ' || c.season_name,
           m.away_team_id, m.away_team_name, m.home_team_id, m.home_team_name
    FROM matches m JOIN competitions c USING (competition_id, season_id)
),
ev AS (
    SELECT e.*, g.state, g.seconds
    FROM events e JOIN game_state g USING (event_id)
),
open_passes AS (
    SELECT ev.match_id, ev.team_id, ev.x, ev.state
    FROM ev JOIN passes p USING (event_id)
    WHERE coalesce(p.pass_type, '') NOT IN ('Corner', 'Free Kick', 'Throw-in', 'Goal Kick', 'Kick Off')
),
passing AS (
    SELECT match_id, team_id,
           count(*) AS passes,
           count(*) FILTER (WHERE state = 'level') AS passes_level,
           count(*) FILTER (WHERE x < 72) AS passes_own_60,
           count(*) FILTER (WHERE x < 72 AND state = 'level') AS passes_own_60_level
    FROM open_passes GROUP BY ALL
),
defending AS (
    SELECT match_id, team_id,
           count(*) AS def_actions,
           count(*) FILTER (WHERE state = 'level') AS def_actions_level
    FROM ev
    WHERE x >= 48
      AND (type_name IN ('Interception', 'Foul Committed')
           OR (type_name = 'Duel' AND details->>'$.duel.type.name' = 'Tackle'))
    GROUP BY ALL
),
clock AS (
    -- 'level' reads the same from both sides, so summing over all events is safe.
    SELECT match_id,
           sum(seconds) / 60 AS minutes,
           sum(seconds) FILTER (WHERE state = 'level') / 60 AS level_minutes
    FROM game_state
    GROUP BY ALL
),
shooting AS (
    SELECT ev.match_id, ev.team_id,
           sum(s.statsbomb_xg) AS npxg,
           sum(s.statsbomb_xg) FILTER (WHERE ev.state = 'level') AS npxg_level
    FROM ev JOIN shots s USING (event_id)
    WHERE s.shot_type <> 'Penalty'
    GROUP BY ALL
),
goals AS (
    SELECT match_id, team_id,
           count(*) FILTER (WHERE type_name = 'Own Goal For'
                               OR event_id IN (SELECT event_id FROM shots WHERE outcome = 'Goal'))
               AS goals
    FROM ev GROUP BY ALL
),
won AS (
    SELECT match_id, team_id,
           count(*) AS regains,
           count(*) FILTER (WHERE is_high) AS high_regains,
           sum(npxg) FILTER (WHERE is_high) AS high_regain_npxg
    FROM regains GROUP BY ALL
)
SELECT t.match_id, t.tournament, t.team_id, t.team_name, t.opp_id, t.opp_name,
       c.minutes, coalesce(c.level_minutes, 0) AS level_minutes,
       op.passes_own_60 AS opp_passes, coalesce(d.def_actions, 0) AS def_actions,
       op.passes_own_60 / nullif(d.def_actions, 0) AS ppda,
       op.passes_own_60_level AS opp_passes_level,
       coalesce(d.def_actions_level, 0) AS def_actions_level,
       op.passes_own_60_level / nullif(d.def_actions_level, 0) AS ppda_level,
       own.passes / (own.passes + op.passes) AS possession,
       own.passes_level / nullif(own.passes_level + op.passes_level, 0) AS possession_level,
       coalesce(w.regains, 0) AS regains,
       coalesce(w.high_regains, 0) AS high_regains,
       coalesce(w.high_regain_npxg, 0) AS high_regain_npxg,
       coalesce(gf.goals, 0) AS goals_for,
       coalesce(ga.goals, 0) AS goals_against,
       coalesce(sf.npxg, 0) AS npxg,
       coalesce(sa.npxg, 0) AS npxga,
       coalesce(sf.npxg, 0) - coalesce(sa.npxg, 0) AS npxgd,
       coalesce(sf.npxg_level, 0) AS npxg_level,
       coalesce(sa.npxg_level, 0) AS npxga_level
FROM teams t
JOIN clock c USING (match_id)
JOIN passing own ON own.match_id = t.match_id AND own.team_id = t.team_id
JOIN passing op ON op.match_id = t.match_id AND op.team_id = t.opp_id
LEFT JOIN defending d ON d.match_id = t.match_id AND d.team_id = t.team_id
LEFT JOIN won w ON w.match_id = t.match_id AND w.team_id = t.team_id
LEFT JOIN goals gf ON gf.match_id = t.match_id AND gf.team_id = t.team_id
LEFT JOIN goals ga ON ga.match_id = t.match_id AND ga.team_id = t.opp_id
LEFT JOIN shooting sf ON sf.match_id = t.match_id AND sf.team_id = t.team_id
LEFT JOIN shooting sa ON sa.match_id = t.match_id AND sa.team_id = t.opp_id
