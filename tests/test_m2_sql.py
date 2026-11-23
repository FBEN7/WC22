"""M2 acceptance tests: SQL exercises in sql/*.sql."""

import pytest

from fdl import sql

FINAL, CAN_MAR, WAL_IRN = 3869685, 3857276, 3857273
MESSI, HENNESSEY = 5503, 3488


@pytest.fixture
def match_minutes(con):
    """Real duration of each match in minutes (periods 1-4, stoppage time included)."""
    return dict(con.execute("""
        SELECT match_id, sum(len) / 60 FROM (
            SELECT match_id, period, max(ts_seconds) AS len FROM events
            WHERE type_name = 'Half End' AND period < 5 GROUP BY ALL)
        GROUP BY 1""").fetchall())


def test_example_team_shots(con):
    df = sql.run(con, "team_shots").set_index(["match_id", "team_name"])
    assert df.loc[(FINAL, "Argentina"), "goals"] == 3  # shoot-out excluded
    assert df.loc[(FINAL, "France"), "goals"] == 3
    assert df.loc[(CAN_MAR, "Canada"), "goals"] == 0  # Canada's goal was an own goal


# ---------------------------------------------------------------- 01 minutes played


def test_minutes_shape(con, match_minutes):
    df = sql.run(con, "minutes_played")
    assert list(df.columns) == ["match_id", "team_id", "player_id", "player_name", "minutes"]
    assert not df.duplicated(["match_id", "player_id"]).any()
    assert (df["minutes"] > 0).all()
    assert (df["minutes"] <= df["match_id"].map(match_minutes) + 1e-6).all()


def test_minutes_known_players(con):
    df = sql.run(con, "minutes_played").set_index(["match_id", "player_id"])["minutes"]
    assert df[(FINAL, MESSI)] == pytest.approx(141.41, abs=0.05)  # whole match incl. extra time
    assert df[(WAL_IRN, HENNESSEY)] == pytest.approx(88.18, abs=0.05)  # sent off


def test_minutes_team_totals(con, match_minutes):
    """11 players on the pitch at all times, except after a sending-off."""
    df = sql.run(con, "minutes_played")
    totals = df.groupby(["match_id", "team_id"])["minutes"].sum()
    wales = con.execute("SELECT home_team_id FROM matches WHERE match_id = ?",
                        [WAL_IRN]).fetchone()[0]
    for (match_id, team_id), total in totals.items():
        full = 11 * match_minutes[match_id]
        if (match_id, team_id) == (WAL_IRN, wales):
            lost = match_minutes[WAL_IRN] - 88.18  # Hennessey's slot after the red card
            assert total == pytest.approx(full - lost, abs=0.2)
        else:
            assert total == pytest.approx(full, abs=0.2), (match_id, team_id)


# ---------------------------------------------------------------- 02 player passing


def test_player_passing_messi(con):
    df = sql.run(con, "player_passing").set_index("player_id")
    m = df.loc[MESSI]
    assert (m.matches, m.passes, m.completed, m.progressive) == (1, 60, 49, 12)
    assert m.passes_p90 == pytest.approx(60 / m.minutes * 90)


def test_player_passing_consistency(con):
    df = sql.run(con, "player_passing")
    assert (df["completed"] <= df["passes"]).all()
    assert (df["progressive"] <= df["completed"]).all()
    assert not df.duplicated(["player_id", "team_id"]).any()


# ---------------------------------------------------------------- 03 PPDA


def test_ppda_values(con):
    df = sql.run(con, "ppda").set_index(["match_id", "team_name"])
    got = {k: (int(r.opp_passes), int(r.def_actions)) for k, r in df.iterrows()}
    assert got == {
        (WAL_IRN, "Iran"): (356, 14),
        (WAL_IRN, "Wales"): (222, 17),
        (CAN_MAR, "Canada"): (289, 21),
        (CAN_MAR, "Morocco"): (370, 22),
        (FINAL, "Argentina"): (367, 37),
        (FINAL, "France"): (441, 36),
    }
    assert df["ppda"].to_numpy() == pytest.approx((df["opp_passes"] / df["def_actions"]).to_numpy())
