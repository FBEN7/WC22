"""M1 acceptance tests: data-quality checks.

Two kinds of test per check:
  * on the real fixture matches: either "no violation" or "exactly these real defects";
  * on a copy with an injected defect: the check must catch it.
"""

import pandas as pd

from fdl import quality

FINAL, CAN_MAR, WAL_IRN = 3869685, 3857276, 3857273


def _ids(df: pd.DataFrame, *cols) -> set:
    return set(map(tuple, df[list(cols)].itertuples(index=False)))


# ---------------------------------------------------------------- coordinates (worked example)


def test_coordinates_clean(con):
    assert quality.check_coordinates_in_bounds(con).empty


def test_coordinates_injected(writable_con):
    ev = writable_con.execute("SELECT event_id FROM passes LIMIT 1").fetchone()[0]
    writable_con.execute("UPDATE passes SET end_x = 121.5 WHERE event_id = ?", [ev])
    out = quality.check_coordinates_in_bounds(writable_con)
    assert _ids(out, "event_id", "field") == {(ev, "pass.end_location")}


# ---------------------------------------------------------------- score reconciliation


def test_score_clean(con):
    # Fails if you count shoot-out penalties (final) or forget own goals (Canada).
    out = quality.check_score_reconciliation(con)
    assert out.empty, out


def test_score_wrong_team_injected(writable_con):
    writable_con.execute(
        "UPDATE matches SET home_score = 1, away_score = 1 WHERE match_id = ?",
        [WAL_IRN],
    )
    out = quality.check_score_reconciliation(writable_con)
    assert WAL_IRN in set(out["match_id"])


def test_score_injected(writable_con):
    goal = writable_con.execute(
        "SELECT s.event_id FROM shots s JOIN events e USING (event_id) "
        "WHERE e.match_id = ? AND s.outcome = 'Goal' LIMIT 1", [WAL_IRN]
    ).fetchone()[0]
    writable_con.execute("UPDATE shots SET outcome = 'Saved' WHERE event_id = ?", [goal])
    out = quality.check_score_reconciliation(writable_con)
    assert set(out["match_id"]) == {WAL_IRN}
    row = out.iloc[0]
    assert (row.home_goals_events, row.away_goals_events) == (0, 1)


# ---------------------------------------------------------------- event order


def test_event_order_finds_real_defects(con):
    # Two 'Ball Receipt*' events in the final carry a timestamp of ~0s
    # in the middle of a period. They are real defects in the open data.
    out = quality.check_event_order(con)
    assert _ids(out, "match_id", "idx") == {(FINAL, 3438), (FINAL, 3975)}
    assert set(out["type_name"]) == {"Ball Receipt*"}


def test_event_order_injected(writable_con):
    writable_con.execute(
        "UPDATE events SET timestamp = '00:00:01.000', ts_seconds = 1.0 "
        "WHERE match_id = ? AND period = 2 AND idx = ("
        "  SELECT min(idx) + 500 FROM events WHERE match_id = ? AND period = 2)",
        [WAL_IRN, WAL_IRN],
    )
    out = quality.check_event_order(writable_con)
    assert WAL_IRN in set(out["match_id"])


# ---------------------------------------------------------------- related events


def test_related_events_clean(con):
    # Thousands of links are one-way BY DESIGN. Find which, and don't report them.
    out = quality.check_related_events_reciprocal(con)
    assert out.empty, out.head()


def test_related_events_injected(writable_con):
    a, b = writable_con.execute(
        "SELECT p.event_id, r.event_id FROM events p JOIN events r "
        "ON r.event_id = p.related_events[1] "
        "WHERE p.match_id = ? AND p.type_name = 'Shot' AND r.type_name = 'Goal Keeper' LIMIT 1",
        [CAN_MAR],
    ).fetchone()
    back = writable_con.execute("SELECT related_events FROM events WHERE event_id = ?",
                                [b]).fetchone()[0]
    writable_con.execute("UPDATE events SET related_events = ? WHERE event_id = ?",
                         [[x for x in back if x != a], b])
    out = quality.check_related_events_reciprocal(writable_con)
    assert _ids(out, "event_id", "related_event_id") == {(a, b)}


def test_related_event_missing_target_injected(writable_con):
    link = writable_con.execute("""
        SELECT event_id, related_events[1]
        FROM events
        WHERE match_id = ? AND len(related_events) > 0
        LIMIT 1
    """, [CAN_MAR]).fetchone()
    if link:
        source, _ = link
        writable_con.execute(
            "UPDATE events SET related_events = ['missing-event-id'] WHERE event_id = ?",
            [source],
        )
        out = quality.check_related_events_reciprocal(writable_con)
        assert (source, "missing-event-id") in set(
            map(tuple, out[["event_id", "related_event_id"]].itertuples(index=False))
        )


# ---------------------------------------------------------------- players in lineups


def test_players_in_lineups_clean(con):
    assert quality.check_players_in_lineups(con).empty


def test_players_in_lineups_injected(writable_con):
    team = writable_con.execute("SELECT home_team_id FROM matches WHERE match_id = ?",
                                [CAN_MAR]).fetchone()[0]
    writable_con.execute(
        "DELETE FROM lineups WHERE match_id = ? AND player_name = 'Alphonso Davies'", [CAN_MAR]
    )
    out = quality.check_players_in_lineups(writable_con)
    assert _ids(out, "match_id", "team_id", "player_name") == {
        (CAN_MAR, team, "Alphonso Davies")
    }


def test_players_in_lineups_catches_recipients(writable_con):
    # A player who only ever RECEIVES the ball must still be checked.
    writable_con.execute(
        "UPDATE passes SET recipient_id = 999999999 WHERE event_id = ("
        "  SELECT p.event_id FROM passes p JOIN events e USING (event_id) "
        "  WHERE e.match_id = ? AND p.recipient_id IS NOT NULL LIMIT 1)", [WAL_IRN]
    )
    out = quality.check_players_in_lineups(writable_con)
    assert 999999999 in set(out["player_id"])


# ---------------------------------------------------------------- lineup spells


def test_lineup_spells_finds_real_defects(con):
    # Spells of these 5 players in the final are out of order or overlap.
    out = quality.check_lineup_spells(con)
    assert set(out["match_id"]) == {FINAL}
    assert set(out["player_id"]) == {
        5485,  # Varane: subbed off at 112:28 but has a later-listed spell from 41:20 to the end
        4445,  # Kounde: same pattern
        5503,  # Messi: a spell from 115:32 (period 4) to 28:11 (period 1)
        28263,  # Montiel
        19597,  # Acuna
    }


def test_run_all_summary(con):
    summary = quality.run_all(con)
    assert list(summary["check"]) == list(quality.CHECKS)
    assert set(summary["status"]) <= {"PASS", "FAIL", "TODO"}


def test_related_events_pass_receipt_checked(writable_con):
    # Pass <-> Ball Receipt* links are reciprocal in the data: a broken one is a defect.
    p, r = writable_con.execute(
        "SELECT p.event_id, r.event_id FROM events p JOIN events r "
        "ON r.event_id = p.related_events[1] "
        "WHERE p.match_id = ? AND p.type_name = 'Pass' AND r.type_name = 'Ball Receipt*' LIMIT 1",
        [WAL_IRN],
    ).fetchone()
    back = writable_con.execute("SELECT related_events FROM events WHERE event_id = ?",
                                [r]).fetchone()[0]
    writable_con.execute("UPDATE events SET related_events = ? WHERE event_id = ?",
                         [[x for x in back if x != p], r])
    out = quality.check_related_events_reciprocal(writable_con)
    assert (p, r) in set(map(tuple, out[["event_id", "related_event_id"]].itertuples(index=False)))
