-- 10 - Game state of every event, and how long it lasted.
--
-- View name: game_state. One row per event of periods 1-4 (the shoot-out is not play):
--   match_id, event_id, idx, period, team_id, goals_for, goals_against, state, seconds
--
--   * goals_for / goals_against: the score BEFORE the event, seen from the side of
--     the team performing it. Goals are scoring shots plus 'Own Goal For' events
--     (StatsBomb credits that event to the team that benefits).
--   * state: 'level', 'leading' or 'trailing', from that same side.
--   * seconds: time until the next event of the same period. The clock is a running
--     maximum of ts_seconds, so the two events with corrupted timestamps found by the
--     quality checks (WC 2022 final) neither add nor remove time.

WITH ev AS (
    SELECT e.match_id, e.event_id, e.idx, e.period, e.team_id, e.ts_seconds,
           m.home_team_id,
           CASE WHEN (e.type_name = 'Shot' AND s.outcome = 'Goal') OR e.type_name = 'Own Goal For'
                THEN e.team_id END AS scoring_team
    FROM events e
    JOIN matches m USING (match_id)
    LEFT JOIN shots s USING (event_id)
    WHERE e.period < 5
),
running AS (
    SELECT *,
        coalesce(sum((scoring_team = home_team_id)::INT) OVER w_before, 0) AS home_before,
        coalesce(sum((scoring_team <> home_team_id)::INT) OVER w_before, 0) AS away_before,
        max(ts_seconds) OVER (PARTITION BY match_id, period ORDER BY idx
                              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS clock
    FROM ev
    WINDOW w_before AS (PARTITION BY match_id ORDER BY idx
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
),
sided AS (
    SELECT *,
        CASE WHEN team_id = home_team_id THEN home_before ELSE away_before END AS goals_for,
        CASE WHEN team_id = home_team_id THEN away_before ELSE home_before END AS goals_against
    FROM running
)
SELECT match_id, event_id, idx, period, team_id, goals_for, goals_against,
       CASE WHEN goals_for = goals_against THEN 'level'
            WHEN goals_for > goals_against THEN 'leading'
            ELSE 'trailing' END AS state,
       coalesce(lead(clock) OVER (PARTITION BY match_id, period ORDER BY idx) - clock, 0) AS seconds
FROM sided
