"""M5 - Streamlit app.  Run:  streamlit run app/streamlit_app.py

"Match centre" is a worked example. The other pages are yours to build (see
BRIEF.md, M5); they show what is missing until then.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from mplsoccer import Pitch

from fdl import quality, sql
from fdl.config import DB_PATH
from fdl.warehouse import connect

st.set_page_config(page_title="Football Data Lab", layout="wide")


@st.cache_resource
def get_con():
    if not DB_PATH.exists():
        st.error(f"{DB_PATH} not found. Run `python -m fdl download` then `python -m fdl build`.")
        st.stop()
    con = connect(DB_PATH)
    sql.create_views(con)
    return con


@st.cache_data
def query(q: str, params: tuple = ()) -> pd.DataFrame:
    return get_con().execute(q, list(params)).df()


def todo(milestone: str, what: str):
    st.info(f"**To do ({milestone})** - {what}")


# ------------------------------------------------------------------ pages


def match_centre():
    """Worked example: pick a match, see the score, the shot table and a shot map."""
    matches = query("""
        SELECT m.match_id, c.competition_name || ' ' || c.season_name AS competition,
               strftime(m.match_date, '%Y-%m-%d') AS match_date, m.competition_stage,
               m.home_team_name || ' ' || m.home_score || '-' || m.away_score || ' '
                 || m.away_team_name AS label,
               m.home_team_id, m.away_team_id, m.home_team_name, m.away_team_name
        FROM matches m JOIN competitions c USING (competition_id, season_id)
        ORDER BY m.match_date DESC""")
    comp = st.sidebar.selectbox("Competition", sorted(matches["competition"].unique()))
    ms = matches[matches["competition"] == comp]
    options = (ms["label"] + "  (" + ms["match_date"] + ")").tolist()
    m = ms.iloc[options.index(st.sidebar.selectbox("Match", options))]

    st.header(m["label"])
    st.caption(f"{comp} - {m['competition_stage']} - {m['match_date']}")

    team_stats = query("SELECT * FROM team_shots WHERE match_id = ?", (int(m["match_id"]),))
    st.dataframe(team_stats.drop(columns=["match_id", "team_id"]), hide_index=True)

    shots = query("""
        SELECT e.team_id, e.player_name, e.minute, e.x, e.y, s.statsbomb_xg, s.outcome, s.shot_type
        FROM shots s JOIN events e USING (event_id)
        WHERE e.match_id = ? AND e.period < 5""", (int(m["match_id"]),))

    pitch = Pitch(pitch_type="statsbomb", line_color="#888888", pitch_color="white")
    fig, ax = pitch.draw(figsize=(10, 6.5))
    for team_id, name, colour in [(m["home_team_id"], m["home_team_name"], "#1f77b4"),
                                  (m["away_team_id"], m["away_team_name"], "#d62728")]:
        t = shots[shots["team_id"] == team_id]
        # Both teams attack towards x = 120 in the data: mirror the home side
        # so the two teams shoot at opposite goals.
        x = 120 - t["x"] if team_id == m["home_team_id"] else t["x"]
        y = 80 - t["y"] if team_id == m["home_team_id"] else t["y"]
        goal = t["outcome"] == "Goal"
        pitch.scatter(x[~goal], y[~goal], s=t["statsbomb_xg"][~goal] * 800 + 20, ax=ax,
                      facecolor="none", edgecolor=colour, linewidth=1.5, label=f"{name}")
        pitch.scatter(x[goal], y[goal], s=t["statsbomb_xg"][goal] * 800 + 20, ax=ax,
                      color=colour, edgecolor="black", label=f"{name} goal")
    ax.legend(loc="lower center", ncol=4, fontsize=8, frameon=False)
    ax.set_title("Shots, sized by StatsBomb xG (shoot-out excluded)", fontsize=10)
    st.pyplot(fig)
    plt.close(fig)
    with st.expander("Shot list"):
        st.dataframe(shots.drop(columns=["team_id"]), hide_index=True)


def data_quality():
    st.header("Data quality")
    summary = quality.run_all(get_con())
    st.dataframe(summary, hide_index=True)

    failing = summary.loc[summary["status"] == "FAIL", "check"].tolist()
    if not failing:
        st.success("No failing check in the current warehouse.")
        return

    check = st.selectbox("Failing check", failing)
    if not isinstance(check, str):
        return
    violations = quality.violations(get_con(), check)
    st.caption(f"{len(violations)} violation(s) detected")
    st.dataframe(violations, hide_index=True)

    if check == "event_order" and not violations.empty:
        match_id = int(violations.iloc[0]["match_id"])
        idx = int(violations.iloc[0]["idx"])
        context = query("""
            SELECT idx, period, timestamp, type_name, player_name
            FROM events
            WHERE match_id = ? AND idx BETWEEN ? AND ?
            ORDER BY period, idx
        """, (match_id, idx - 3, idx + 3))
        st.subheader("Event context")
        st.dataframe(context, hide_index=True)


def xg_model():
    from fdl import xg

    st.header("xG model")
    shots = xg.build_shot_features(get_con())
    feature_cols = [c for c in shots.select_dtypes("number").columns
                    if c not in ("match_id", "is_goal", "statsbomb_xg")]

    n_matches = shots["match_id"].nunique()
    if n_matches < 2:
        st.warning("At least two matches are needed for grouped cross-validation.")
        return

    n_splits = min(5, n_matches)

    @st.cache_data(show_spinner=False)
    def cached_predictions(_shots: pd.DataFrame, cols: tuple[str, ...]):
        ours_cached = xg.fit_predict_oof(_shots, list(cols), n_splits=n_splits)
        geo_cached = xg.fit_predict_oof(_shots, ["distance", "angle"], n_splits=n_splits)
        return ours_cached, geo_cached

    ours, geo = cached_predictions(shots, tuple(feature_cols))
    y = shots["is_goal"].to_numpy()

    models = {
        "Constant": pd.Series(y).fillna(0).to_numpy() * 0 + y.mean(),
        "Distance + angle": geo,
        "Freeze-frame model": ours,
        "StatsBomb": shots["statsbomb_xg"].fillna(y.mean()).to_numpy(),
    }
    metrics = pd.DataFrame({name: xg.evaluate(y, p) for name, p in models.items()}).T
    st.dataframe(metrics[["n_shots", "goal_rate", "log_loss", "brier", "auc"]].round(4),
                 use_container_width=True)

    cal = xg.calibration_table(y, ours, bins=min(10, len(shots)))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(cal["mean_pred"], cal["goal_rate"], marker="o", label="Model")
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", label="Perfect calibration")
    ax.set_xlabel("Mean predicted goal probability")
    ax.set_ylabel("Observed goal rate")
    ax.legend()
    st.pyplot(fig)
    plt.close(fig)

    disagreement = shots.assign(
        abs_error=np.abs(ours - shots["statsbomb_xg"].fillna(y.mean()).to_numpy())
    )
    disagreement["model_xg"] = ours
    disagreement = disagreement.nlargest(3, "abs_error")[
        ["event_id", "match_id", "distance", "angle", "statsbomb_xg", "model_xg"]
    ]
    st.subheader("Largest model/StatsBomb disagreements")
    st.dataframe(disagreement.round(4), hide_index=True)

    for _, shot in disagreement.iterrows():
        event = query("""
            SELECT match_id, x, y, player_name
            FROM events
            WHERE event_id = ?
        """, (shot["event_id"] ,))
        frame = query("""
            SELECT x, y, teammate, position_name
            FROM shot_freeze_frames
            WHERE shot_event_id = ?
        """, (shot["event_id"],))
        if event.empty:
            continue
        pitch = Pitch(pitch_type="statsbomb", pitch_color="white", line_color="#888888")
        fig, ax = pitch.draw(figsize=(8, 5))
        ball = event.iloc[0]
        pitch.scatter(ball["x"], ball["y"], ax=ax, s=100,
                      color="#111111", edgecolor="white", label="Shot")
        if not frame.empty:
            teammates = frame[frame["teammate"]]
            opponents = frame[~frame["teammate"]]
            pitch.scatter(teammates["x"], teammates["y"], ax=ax,
                          s=35, color="#1f77b4", label="Teammates")
            pitch.scatter(opponents["x"], opponents["y"], ax=ax,
                          s=35, color="#d62728", label="Opponents")
        ax.set_title(
            f"Disagreement: {ball['player_name']} — "
            f"model {shot['model_xg']:.3f}, "
            f"StatsBomb {shot['statsbomb_xg']:.3f}"
        )
        ax.legend(loc="lower center", ncol=3, fontsize=8, frameon=False)
        st.pyplot(fig)
        plt.close(fig)


def expected_threat():
    from fdl import xt

    st.header("Expected threat")
    moves, shots = xt.load_actions(get_con())
    grid = xt.expected_threat(moves, shots)

    pitch = Pitch(pitch_type="statsbomb", pitch_color="white", line_color="#888888")
    fig, ax = pitch.draw(figsize=(10, 6.5))
    image = ax.imshow(
        grid,
        origin="lower",
        extent=(0, 120, 0, 80),
        aspect="auto",
        cmap="YlGn",
        alpha=0.75,
    )
    fig.colorbar(image, ax=ax, shrink=0.6, label="xT")
    ax.set_title("Expected-threat grid")
    st.pyplot(fig)
    plt.close(fig)

    min_minutes = st.sidebar.slider("Minimum minutes", 0, 200, 25, 5)
    added = xt.rate_moves(moves, grid)
    totals = (
        moves.assign(xt_added=added)
        .groupby(["player_id", "player_name", "team_id"], as_index=False)["xt_added"]
        .sum()
    )
    minutes = query("SELECT * FROM minutes_played")
    minute_totals = minutes.groupby(["player_id", "team_id"], as_index=False)["minutes"].sum()
    ranking = totals.merge(minute_totals, on=["player_id", "team_id"])
    ranking = ranking[ranking["minutes"] >= min_minutes].copy()
    ranking["xt_added_p90"] = ranking["xt_added"] / ranking["minutes"] * 90
    st.dataframe(ranking.nlargest(20, "xt_added_p90")
                 [["player_name", "team_id", "minutes", "xt_added", "xt_added_p90"]]
                 .round(4), hide_index=True)


def player_profile():
    st.header("Player profile")
    players = query("""
        SELECT DISTINCT player_id, player_name
        FROM events
        WHERE player_id IS NOT NULL
        ORDER BY player_name
    """)
    if players.empty:
        st.info("No players available.")
        return

    labels = (players["player_name"] + " (" + players["player_id"].astype(str) + ")").tolist()
    selected = st.sidebar.selectbox("Player", labels)
    player_id = int(players.iloc[labels.index(selected)]["player_id"])

    profile = query("SELECT * FROM player_passing WHERE player_id = ?", (player_id,))
    if profile.empty:
        st.info("This player has no completed passing profile.")
        return

    profile = profile.iloc[0]
    position = query("SELECT position_name FROM events WHERE player_id = ? LIMIT 1", (player_id,))
    position_name = position.iloc[0]["position_name"] if not position.empty else None

    defender = position_name and (
        "Back" in position_name
        or "Defensive" in position_name
        or position_name == "Goalkeeper"
    )
    midfielder = position_name and ("Midfield" in position_name or "Wing" in position_name)
    position_group = "Defenders" if defender else "Midfielders" if midfielder else "Attackers"

    if position_group == "Defenders":
        position_filter = (
            "position_name LIKE '%Back%'",
            "position_name LIKE '%Defensive%'",
            "position_name = 'Goalkeeper'",
        )
    elif position_group == "Midfielders":
        position_filter = ("position_name LIKE '%Midfield%'", "position_name LIKE '%Wing%'")
    else:
        position_filter = ("position_name LIKE '%Forward%'", "position_name LIKE '%Striker%'")

    group_players = query(
        "SELECT DISTINCT player_id FROM events WHERE " + " OR ".join(position_filter)
    )

    metrics = ["passes_p90", "progressive_p90", "completion_pct"]
    population = query("SELECT * FROM player_passing WHERE minutes >= 25")
    if not group_players.empty:
        ids = tuple(int(value) for value in group_players["player_id"])
        if ids:
            placeholders = ",".join("?" for _ in ids)
            population = query(
                "SELECT * FROM player_passing "
                "WHERE minutes >= 25 AND player_id IN ("
                f"{placeholders})",
                ids,
            )
    percentiles = {m: 100 * (population[m] < profile[m]).mean() for m in metrics}

    st.subheader(profile["player_name"])
    col1, col2, col3 = st.columns(3)
    col1.metric("Minutes", f"{profile['minutes']:.1f}")
    col2.metric("Matches", int(profile["matches"]))
    col3.metric("Sample size", len(population))

    theta = [i * 2 * 3.14159 / len(metrics) for i in range(len(metrics))]
    values = [percentiles[m] for m in metrics]
    theta += theta[:1]
    values += values[:1]
    fig, ax = plt.subplots(subplot_kw={"projection": "polar"}, figsize=(6, 6))
    ax.plot(theta, values)
    ax.fill(theta, values, alpha=0.25)
    ax.set_xticks(theta[:-1])
    ax.set_xticklabels(["Passes/90", "Progressive/90", "Completion %"])
    ax.set_ylim(0, 100)
    ax.set_title("Percentile profile among players with 25+ minutes")
    st.pyplot(fig)
    plt.close(fig)

    if not population.empty:
        comparison = pd.DataFrame({
            "Metric": ["Passes/90", "Progressive/90", "Completion %"],
            "Player": [profile[m] for m in metrics],
            "Position group mean": [population[m].mean() for m in metrics],
        })
        comparison["Difference"] = (
            comparison["Player"] - comparison["Position group mean"]
        )
        st.subheader(f"Comparison — {position_group}")
        st.dataframe(comparison.round(4), hide_index=True)


PAGES = {
    "Match centre": match_centre,
    "Data quality": data_quality,
    "xG model": xg_model,
    "Expected threat": expected_threat,
    "Player profile": player_profile,
}

page = st.sidebar.radio("Page", list(PAGES))
PAGES[page]()
st.sidebar.caption("Data: StatsBomb Open Data")
