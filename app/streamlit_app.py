"""M5 - Streamlit app.  Run:  streamlit run app/streamlit_app.py

"Match centre" is a worked example. The other pages are yours to build (see
BRIEF.md, M5); they show what is missing until then.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
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
    st.dataframe(quality.run_all(get_con()), hide_index=True)
    todo("M5", "let the user pick a failing check and see its violations, with links "
               "to the match and the event context (events just before and after).")


def xg_model():
    st.header("xG model")
    todo("M5", "metrics table (yours vs StatsBomb vs distance+angle), calibration plot "
               "(predicted vs observed goal rate by bin), and 3 shots where your model and "
               "StatsBomb disagree most - with the freeze frame drawn on a pitch.")


def expected_threat():
    st.header("Expected threat")
    todo("M5", "xT grid as a heatmap on a pitch, and a table of players ranked by xT "
               "added per 90 (minimum minutes as a slider).")


def player_profile():
    st.header("Player profile")
    todo("M5", "pick a player, show a percentile radar (mplsoccer PyPizza or Radar) against "
               "players in the same position group, per 90, with the sample size shown.")


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
