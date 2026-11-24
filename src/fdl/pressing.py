"""Does pressing pay off at international tournaments?

The analysis behind the README. Everything is computed from the warehouse by
`python -m fdl report`, which writes reports/pressing/ (figures, results.md,
results.json).

Unit of analysis: one team in one match (team_match_pressing view, sql/12).
Pressing intensity is PPDA (lower = more pressing); it is used as log2(PPDA), so
effects read "per doubling of PPDA". The outcome is the non-penalty xG
difference (StatsBomb xG), which is far less noisy than goals.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import statsmodels.formula.api as smf  # noqa: E402

from fdl import sql  # noqa: E402
from fdl.config import ROOT  # noqa: E402

REPORT_DIR = ROOT / "reports" / "pressing"
HIGH_REGAIN_X = 120 - 40 / 0.9144  # 40 metres from the opponent's goal line, in yards
MIN_MATCHES_FOR_RANKING = 4

# Chart tokens (light surface). One series per chart: no categorical palette needed.
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3de"
SERIES, CONTEXT = "#2a78d6", "#b9b8b1"


# ----------------------------------------------------------------- data


def team_matches(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """team_match_pressing plus log2(PPDA) and leave-one-out team strength.

    strength_loo: the team's mean npxG difference in its OTHER matches of the same
    tournament - a proxy for quality that does not use the match being explained.
    opp_strength_loo: the same for the opponent.
    """
    sql.create_views(con)
    df = con.execute("SELECT * FROM team_match_pressing").df()
    df["log2_ppda"] = np.log2(df["ppda"])
    df["log2_ppda_level"] = np.log2(df["ppda_level"])
    df["team_tournament"] = df["tournament"] + " | " + df["team_name"]

    grp = df.groupby(["tournament", "team_id"])["npxgd"]
    n, total = grp.transform("size"), grp.transform("sum")
    df["strength_loo"] = (total - df["npxgd"]) / (n - 1).where(n > 1)
    opp = df[["match_id", "team_id", "strength_loo"]].rename(
        columns={"team_id": "opp_id", "strength_loo": "opp_strength_loo"})
    df = df.merge(opp, on=["match_id", "opp_id"], how="left")

    level = df["level_minutes"] > 0
    df["npxgd_level_p90"] = np.where(
        level, (df["npxg_level"] - df["npxga_level"]) / df["level_minutes"] * 90, np.nan)
    return df


def regain_value(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """What an open-play regain is worth, by where it happens."""
    sql.create_views(con)
    r = con.execute("SELECT * FROM regains").df()
    total_npxg = con.execute("""
        SELECT sum(s.statsbomb_xg) FROM shots s JOIN events e USING (event_id)
        WHERE e.period < 5 AND s.shot_type <> 'Penalty'""").fetchone()[0]
    n_team_matches = 2 * con.execute("SELECT count(*) FROM matches").fetchone()[0]
    zones = ["Defensive third", "Middle zone", "Within 40 m of goal"]
    r["zone"] = pd.cut(r["x"], [-np.inf, 40, HIGH_REGAIN_X, np.inf], labels=zones, right=False)
    out = r.groupby("zone", observed=False).agg(
        regains=("npxg", "size"),
        shot_rate=("shots", lambda s: (s > 0).mean()),
        npxg_per_regain=("npxg", "mean"),
        goal_rate=("goal", "mean"),
        npxg=("npxg", "sum"),
    ).reset_index()
    out["per_team_match"] = out["regains"] / n_team_matches
    out["share_of_all_npxg"] = out["npxg"] / total_npxg
    return out.drop(columns="npxg")


# ----------------------------------------------------------------- models

SPECS: list[tuple[str, str, str]] = [
    # (label, formula, coefficient)
    ("Raw association", "npxgd ~ log2_ppda", "log2_ppda"),
    ("+ team & opponent strength",
     "npxgd ~ log2_ppda + strength_loo + opp_strength_loo", "log2_ppda"),
    ("+ strength + possession share",
     "npxgd ~ log2_ppda + possession + strength_loo + opp_strength_loo", "log2_ppda"),
    ("Within team (fixed effects)", "npxgd ~ log2_ppda + C(team_tournament)", "log2_ppda"),
    ("Within team + possession share",
     "npxgd ~ log2_ppda + possession + C(team_tournament)", "log2_ppda"),
    ("Score level only + possession share",
     "npxgd_level_p90 ~ log2_ppda_level + possession_level", "log2_ppda_level"),
]


def model_sample(df: pd.DataFrame) -> pd.DataFrame:
    """Rows usable by every specification, so the estimates are comparable."""
    ok = (
        df["strength_loo"].notna() & df["opp_strength_loo"].notna()
        & np.isfinite(df["log2_ppda"])
    )
    return df[ok].copy()


def effects(df: pd.DataFrame) -> pd.DataFrame:
    """Effect of doubling PPDA (i.e. pressing half as much) on npxG difference.

    OLS with standard errors clustered by national team (teams appear in several
    matches and tournaments). The level-score model uses team-matches with at least
    15 level minutes and 3 level defensive actions, and npxG difference per 90 level
    minutes as outcome.
    """
    base = model_sample(df)
    level = base[(base["level_minutes"] >= 15) & (base["def_actions_level"] >= 3)
                 & base["possession_level"].notna()]
    rows = []
    for label, formula, coef in SPECS:
        data = level if coef == "log2_ppda_level" else base
        fit = smf.ols(formula, data).fit(cov_type="cluster",
                                         cov_kwds={"groups": data["team_id"]})
        lo, hi = fit.conf_int().loc[coef]
        rows.append({"model": label, "effect": fit.params[coef], "ci_low": lo, "ci_high": hi,
                     "p_value": fit.pvalues[coef], "n": int(fit.nobs), "r2": fit.rsquared})
    return pd.DataFrame(rows)


def correlations(df: pd.DataFrame) -> dict[str, float]:
    d = model_sample(df)
    rho = d[["log2_ppda", "possession", "npxgd", "high_regains"]].corr(method="spearman")
    return {
        "ppda_vs_npxgd": rho.loc["log2_ppda", "npxgd"],
        "ppda_vs_possession": rho.loc["log2_ppda", "possession"],
        "possession_vs_npxgd": rho.loc["possession", "npxgd"],
        "ppda_vs_high_regains": rho.loc["log2_ppda", "high_regains"],
    }


def team_tournaments(df: pd.DataFrame) -> pd.DataFrame:
    """Pooled per team and tournament (PPDA pooled = total passes / total actions)."""
    g = df.groupby(["tournament", "team_name"])
    out = g.agg(matches=("match_id", "size"), opp_passes=("opp_passes", "sum"),
                def_actions=("def_actions", "sum"), possession=("possession", "mean"),
                high_regains=("high_regains", "sum"), npxgd=("npxgd", "sum"),
                minutes=("minutes", "sum")).reset_index()
    out["ppda"] = out["opp_passes"] / out["def_actions"]
    out["high_regains_p90"] = out["high_regains"] / out["minutes"] * 90
    out["npxgd_p90"] = out["npxgd"] / out["minutes"] * 90
    return out.drop(columns=["opp_passes", "def_actions"]).sort_values("ppda")


# ----------------------------------------------------------------- figures


def _style(ax, title: str, xlabel: str, ylabel: str):
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=12)
    ax.set_xlabel(xlabel, color=INK_2, fontsize=9)
    ax.set_ylabel(ylabel, color=INK_2, fontsize=9)
    ax.tick_params(colors=INK_2, labelsize=8, length=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _caption(fig, text: str):
    fig.text(0.01, 0.01, text, fontsize=7, color=INK_2, ha="left", va="bottom")


def figure_teams(tt: pd.DataFrame, path: Path):
    d = tt[tt["matches"] >= MIN_MATCHES_FOR_RANKING]
    fig, ax = plt.subplots(figsize=(9, 5.6))
    ax.scatter(d["ppda"], d["npxgd_p90"], s=42, color=SERIES, edgecolor=SURFACE,
               linewidth=1.5, zorder=3)
    ax.set_xscale("log", base=2)
    ax.xaxis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.set_xticks([6, 8, 12, 16, 24, 32])
    ax.invert_xaxis()
    ax.axhline(0, color=INK_2, linewidth=0.8)
    label = pd.concat([d.nsmallest(2, "ppda"), d.nlargest(2, "ppda"),
                       d.nlargest(3, "npxgd_p90"), d.nsmallest(2, "npxgd_p90")]).drop_duplicates()
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    placed: list = []  # display-space boxes of labels already drawn
    candidates = [((5, 4), "left"), ((5, -11), "left"), ((-5, 4), "right"), ((-5, -11), "right"),
                  ((5, 13), "left"), ((-5, 13), "right")]
    for _, r in label.sort_values("npxgd_p90", ascending=False).iterrows():
        short = r["tournament"].replace("FIFA World Cup", "WC").replace("UEFA Euro", "Euro")
        short = short.replace("African Cup of Nations", "AFCON").replace("Copa America", "Copa")
        text = f"{r['team_name']} ({short})"
        for offset, ha in candidates:  # first position that does not hit another label
            txt = ax.annotate(text, (r["ppda"], r["npxgd_p90"]), xytext=offset,
                              textcoords="offset points", ha=ha, fontsize=7.5, color=INK)
            box = txt.get_window_extent(renderer).expanded(1.02, 1.1)
            if not any(box.overlaps(b) for b in placed):
                break
            txt.remove()
        else:  # nothing fits: keep the default position rather than drop the label
            txt = ax.annotate(text, (r["ppda"], r["npxgd_p90"]), xytext=candidates[0][0],
                              textcoords="offset points", fontsize=7.5, color=INK)
            box = txt.get_window_extent(renderer)
        placed.append(box)
    _style(ax, "Teams that press more tend to dominate xG, but so do teams that have the ball",
           "PPDA, log scale (right = more intense pressing)",
           "Non-penalty xG difference per 90")
    _caption(fig, f"One dot per team and tournament with {MIN_MATCHES_FOR_RANKING}+ matches. "
                  "Six men's tournaments 2018-2024. Data: StatsBomb Open Data.")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)


def figure_possession(df: pd.DataFrame, path: Path):
    d = model_sample(df)
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.scatter(d["possession"] * 100, d["ppda"], s=14, color=SERIES, alpha=0.45,
               linewidth=0, zorder=3)
    ax.set_yscale("log", base=2)
    ax.yaxis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.set_yticks([4, 8, 16, 32, 64])
    ax.invert_yaxis()
    rho = correlations(df)["ppda_vs_possession"]
    _style(ax, f"PPDA is largely a possession measure (Spearman rho = {rho:.2f})",
           "Share of the match's open-play passes (%)",
           "PPDA, log scale (up = more intense pressing)")
    _caption(fig, "One dot per team and match. PPDA counts opponent passes, so a team that keeps "
                  "the ball faces fewer of them and gets a lower PPDA almost by construction.")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)


def figure_regains(rv: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=(9, 4.4))
    colors = [CONTEXT, CONTEXT, SERIES]
    y = np.arange(len(rv))[::-1]
    ax.barh(y, rv["npxg_per_regain"], color=colors, height=0.55, zorder=3)
    for yi, (_, r) in zip(y, rv.iterrows(), strict=True):
        ax.text(r["npxg_per_regain"] + 0.0006, yi,
                f"{r['npxg_per_regain']:.3f} xG  -  {r['per_team_match']:.1f} per team per match"
                f"  -  {r['share_of_all_npxg']:.0%} of all npxG",
                va="center", fontsize=8, color=INK)
    ax.set_yticks(y, rv["zone"].astype(str))
    ax.set_xlim(0, rv["npxg_per_regain"].max() * 1.9)
    _style(ax, "A high regain is worth three times a deep one - but it is rare",
           "Non-penalty xG produced by the possession that follows the regain", "")
    _caption(fig, "Open-play regains only (restarts excluded). 'Within 40 m' follows Opta's "
                  "high-turnover distance; counts are not comparable with Opta's.")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)


def figure_effects(eff: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=(9, 4.6))
    y = np.arange(len(eff))[::-1]
    ax.axvline(0, color=INK_2, linewidth=0.8)
    ax.hlines(y, eff["ci_low"], eff["ci_high"], color=SERIES, linewidth=2, zorder=3)
    ax.scatter(eff["effect"], y, s=50, color=SERIES, edgecolor=SURFACE, linewidth=1.5, zorder=4)
    labels = [f"{m}  (n={n})" for m, n in zip(eff["model"], eff["n"], strict=True)]
    ax.set_yticks(y, labels)
    _style(ax, "Once possession is accounted for, pressing intensity explains little",
           "Change in npxG difference when PPDA doubles (pressing half as much), 95% CI", "")
    _caption(fig, "OLS, standard errors clustered by national team. Negative = pressing more "
                  "goes with a better xG difference. Level-score model: npxG difference per 90.")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)


# ----------------------------------------------------------------- report


def _md(df: pd.DataFrame) -> str:
    """Markdown table without the optional `tabulate` dependency."""
    def cell(v):
        if isinstance(v, float | np.floating):
            return f"{v:.3f}"
        return str(v)
    head = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "|" + "---|" * len(df.columns)
    body = ["| " + " | ".join(cell(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *body])


def report(con: duckdb.DuckDBPyConnection, outdir: Path = REPORT_DIR) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    df = team_matches(con)
    rv = regain_value(con)
    eff = effects(df)
    tt = team_tournaments(df)
    rho = correlations(df)

    figure_teams(tt, outdir / "teams_ppda_vs_xgd.png")
    figure_possession(df, outdir / "ppda_vs_possession.png")
    figure_regains(rv, outdir / "regain_value.png")
    figure_effects(eff, outdir / "ppda_effect_by_model.png")

    scope = con.execute("""
        SELECT count(*) AS matches,
               count(DISTINCT competition_id || '-' || season_id) AS tournaments
        FROM matches""").fetchone()
    by_tournament = (df.groupby("tournament")
                       .agg(matches=("match_id", "nunique"), median_ppda=("ppda", "median"),
                            high_regains_per_team_match=("high_regains", "mean"))
                       .reset_index())
    ranked = tt[tt["matches"] >= MIN_MATCHES_FOR_RANKING]
    results = {
        "matches": scope[0], "tournaments": scope[1], "team_matches": len(df),
        "correlations": rho,
        "regain_value": rv.to_dict(orient="records"),
        "effects": eff.to_dict(orient="records"),
        "by_tournament": by_tournament.to_dict(orient="records"),
        "most_intense_pressers": ranked.head(10).to_dict(orient="records"),
    }
    (outdir / "results.json").write_text(json.dumps(results, indent=2, default=str))

    md = [
        "# Pressing at international tournaments - generated results",
        "",
        f"{scope[0]} matches, {scope[1]} tournaments, {len(df)} team-matches. "
        "Generated by `python -m fdl report`; do not edit by hand.",
        "",
        "## Spearman correlations (team-match level)",
        "",
        _md(pd.Series(rho, name="rho").rename_axis("pair").reset_index()),
        "",
        "## Value of an open-play regain, by zone",
        "",
        _md(rv),
        "",
        "## Effect of doubling PPDA on npxG difference",
        "",
        _md(eff),
        "",
        "## By tournament",
        "",
        _md(by_tournament),
        "",
        f"## Most intense pressers ({MIN_MATCHES_FOR_RANKING}+ matches, pooled PPDA)",
        "",
        _md(ranked.head(15)),
        "",
    ]
    (outdir / "results.md").write_text("\n".join(md))
    return results
