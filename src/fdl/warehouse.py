"""Build a DuckDB warehouse from the cached StatsBomb JSON.

Tables (one row per ...):
    competitions        competition season
    matches             match
    lineups             player x position spell (as delivered: NOT cleaned, see M1)
    events              event (columns common to all event types)
    passes / carries / shots      event of that type, type-specific columns
    shot_freeze_frames  player visible in a shot's freeze frame
    frames_360          player visible in a 360 frame (any event)

Coordinates are kept exactly as StatsBomb delivers them: 120 x 80, the acting
team always attacking towards x = 120.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from fdl.config import DB_PATH, RAW_DIR


def _name(d: dict | None, key: str = "name"):
    return None if d is None else d.get(key)


def _xy(loc, i):
    return loc[i] if loc is not None and len(loc) > i else None


def clock_to_seconds(ts: str) -> float:
    """'00:04:40.798' -> 280.798 (StatsBomb timestamps restart at 0 every period)."""
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


# ---------------------------------------------------------------- flatteners


def flatten_competitions(raw: list[dict]) -> pd.DataFrame:
    cols = [
        "competition_id", "season_id", "country_name", "competition_name",
        "competition_gender", "competition_youth", "competition_international",
        "season_name", "match_available_360",
    ]
    df = pd.DataFrame(raw)[cols]
    df["has_360"] = df.pop("match_available_360").notna()
    return df


def flatten_matches(raw: list[dict]) -> pd.DataFrame:
    rows = []
    for m in raw:
        ht, at = m["home_team"], m["away_team"]
        rows.append({
            "match_id": m["match_id"],
            "competition_id": m["competition"]["competition_id"],
            "season_id": m["season"]["season_id"],
            "match_date": m["match_date"],
            "kick_off": m.get("kick_off"),
            "competition_stage": _name(m.get("competition_stage")),
            "match_week": m.get("match_week"),
            "home_team_id": ht["home_team_id"],
            "home_team_name": ht["home_team_name"],
            "away_team_id": at["away_team_id"],
            "away_team_name": at["away_team_name"],
            "home_score": m["home_score"],
            "away_score": m["away_score"],
            "stadium": _name(m.get("stadium")),
            "referee": _name(m.get("referee")),
            "status_360": m.get("match_status_360"),
            "data_version": (m.get("metadata") or {}).get("data_version"),
        })
    df = pd.DataFrame(rows)
    df["match_date"] = pd.to_datetime(df["match_date"]).dt.date
    return df


def flatten_lineups(match_id: int, raw: list[dict]) -> pd.DataFrame:
    rows = []
    for team in raw:
        for p in team["lineup"]:
            base = {
                "match_id": match_id,
                "team_id": team["team_id"],
                "team_name": team["team_name"],
                "player_id": p["player_id"],
                "player_name": p["player_name"],
                "jersey_number": p.get("jersey_number"),
            }
            if not p["positions"]:  # unused substitute
                rows.append(base | {"spell_order": None})
            for i, pos in enumerate(p["positions"]):
                rows.append(base | {
                    "spell_order": i,
                    "position_id": pos.get("position_id"),
                    "position_name": pos.get("position"),
                    "from_clock": pos.get("from"),
                    "to_clock": pos.get("to"),
                    "from_period": pos.get("from_period"),
                    "to_period": pos.get("to_period"),
                    "start_reason": pos.get("start_reason"),
                    "end_reason": pos.get("end_reason"),
                })
    return pd.DataFrame(rows)


def flatten_events(match_id: int, raw: list[dict]) -> dict[str, pd.DataFrame]:
    events, passes, carries, shots, ff = [], [], [], [], []
    for e in raw:
        loc = e.get("location")
        events.append({
            "match_id": match_id,
            "event_id": e["id"],
            "idx": e["index"],
            "period": e["period"],
            "timestamp": e["timestamp"],
            "ts_seconds": clock_to_seconds(e["timestamp"]),
            "minute": e["minute"],
            "second": e["second"],
            "type_name": e["type"]["name"],
            "possession": e["possession"],
            "possession_team_id": e["possession_team"]["id"],
            "possession_team_name": e["possession_team"]["name"],
            "play_pattern": e["play_pattern"]["name"],
            "team_id": e["team"]["id"],
            "team_name": e["team"]["name"],
            "player_id": _name(e.get("player"), "id"),
            "player_name": _name(e.get("player")),
            "position_name": _name(e.get("position")),
            "x": _xy(loc, 0),
            "y": _xy(loc, 1),
            "duration": e.get("duration"),
            "under_pressure": bool(e.get("under_pressure", False)),
            "counterpress": bool(e.get("counterpress", False)),
            "off_camera": bool(e.get("off_camera", False)),
            "out": bool(e.get("out", False)),
            "related_events": e.get("related_events") or [],
            # Everything type-specific (duel, goalkeeper, clearance, ...) kept as JSON
            # so nothing is lost; query it with DuckDB's JSON functions.
            "details": _details(e),
        })
        t = e["type"]["name"]
        if t == "Pass":
            p = e["pass"]
            end = p.get("end_location")
            passes.append({
                "match_id": match_id,
                "event_id": e["id"],
                "recipient_id": _name(p.get("recipient"), "id"),
                "recipient_name": _name(p.get("recipient")),
                "length": p.get("length"),
                "angle": p.get("angle"),
                "height": _name(p.get("height")),
                "end_x": _xy(end, 0),
                "end_y": _xy(end, 1),
                "outcome": _name(p.get("outcome")),  # NULL = completed
                "pass_type": _name(p.get("type")),  # corner, free kick, throw-in, ...
                "body_part": _name(p.get("body_part")),
                "technique": _name(p.get("technique")),
                "is_cross": bool(p.get("cross", False)),
                "is_switch": bool(p.get("switch", False)),
                "is_through_ball": bool(p.get("through_ball", False)),
                "is_cut_back": bool(p.get("cut_back", False)),
                "is_shot_assist": bool(p.get("shot_assist", False)),
                "is_goal_assist": bool(p.get("goal_assist", False)),
                "assisted_shot_id": p.get("assisted_shot_id"),
            })
        elif t == "Carry":
            end = e["carry"].get("end_location")
            carries.append({
                "match_id": match_id,
                "event_id": e["id"],
                "end_x": _xy(end, 0),
                "end_y": _xy(end, 1),
            })
        elif t == "Shot":
            s = e["shot"]
            end = s.get("end_location")
            shots.append({
                "match_id": match_id,
                "event_id": e["id"],
                "statsbomb_xg": s.get("statsbomb_xg"),
                "outcome": _name(s.get("outcome")),
                "shot_type": _name(s.get("type")),  # Open Play, Penalty, Free Kick, Corner
                "body_part": _name(s.get("body_part")),
                "technique": _name(s.get("technique")),
                "is_first_time": bool(s.get("first_time", False)),
                "is_one_on_one": bool(s.get("one_on_one", False)),
                "is_open_goal": bool(s.get("open_goal", False)),
                "is_aerial_won": bool(s.get("aerial_won", False)),
                "is_deflected": bool(s.get("deflected", False)),
                "follows_dribble": bool(s.get("follows_dribble", False)),
                "key_pass_id": s.get("key_pass_id"),
                "end_x": _xy(end, 0),
                "end_y": _xy(end, 1),
                "end_z": _xy(end, 2),
            })
            for pl in s.get("freeze_frame") or []:
                ff.append({
                    "match_id": match_id,
                    "shot_event_id": e["id"],
                    "player_id": _name(pl.get("player"), "id"),
                    "player_name": _name(pl.get("player")),
                    "position_name": _name(pl.get("position")),
                    "teammate": pl["teammate"],
                    "x": _xy(pl["location"], 0),
                    "y": _xy(pl["location"], 1),
                })
    return {
        "events": pd.DataFrame(events),
        "passes": pd.DataFrame(passes),
        "carries": pd.DataFrame(carries),
        "shots": pd.DataFrame(shots),
        "shot_freeze_frames": pd.DataFrame(ff),
    }


_DETAIL_KEYS = {
    "duel", "goalkeeper", "clearance", "interception", "dribble", "foul_committed",
    "foul_won", "ball_receipt", "ball_recovery", "block", "substitution", "bad_behaviour",
    "50_50", "miscontrol", "injury_stoppage", "half_start", "half_end", "player_off",
    "tactics",
}


def _details(e: dict) -> str | None:
    d = {k: v for k, v in e.items() if k in _DETAIL_KEYS}
    return json.dumps(d) if d else None


def flatten_360(match_id: int, raw: list[dict]) -> pd.DataFrame:
    rows = []
    for fr in raw:
        for pl in fr["freeze_frame"]:
            rows.append({
                "match_id": match_id,
                "event_id": fr["event_uuid"],
                "teammate": pl["teammate"],
                "actor": pl["actor"],
                "keeper": pl["keeper"],
                "x": pl["location"][0],
                "y": pl["location"][1],
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------- build


_INT_COLS = {"jersey_number", "spell_order", "match_week"}


def _tidy(df: pd.DataFrame) -> pd.DataFrame:
    """Integer ids stay integers even when some rows have none (pandas would use float)."""
    for col in df.columns:
        is_int_col = col.endswith(("_id", "_period")) or col in _INT_COLS
        if is_int_col and pd.api.types.is_float_dtype(df[col]):
            df[col] = df[col].astype("Int64")
    return df


def _create(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame, append: bool = False):
    con.register("_df", _tidy(df))
    if append:
        con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM _df")
    else:
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM _df")
    con.unregister("_df")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def build(
    raw_dir: Path = RAW_DIR,
    db_path: Path = DB_PATH,
    match_ids: set[int] | None = None,
) -> Path:
    """(Re)build the warehouse from every cached match (or only `match_ids`)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    matches = pd.concat(
        [flatten_matches(_read(p)) for p in sorted((raw_dir / "matches").glob("*/*.json"))],
        ignore_index=True,
    )
    cached = {int(p.stem) for p in (raw_dir / "events").glob("*.json")}
    matches = matches[matches["match_id"].isin(cached)]
    if match_ids is not None:
        matches = matches[matches["match_id"].isin(match_ids)]
    matches = matches.drop_duplicates("match_id").sort_values("match_id").reset_index(drop=True)
    if matches.empty:
        raise SystemExit(f"no cached matches in {raw_dir}: run `python -m fdl download` first")

    con = duckdb.connect(str(db_path))
    comps = flatten_competitions(_read(raw_dir / "competitions.json"))
    keys = matches[["competition_id", "season_id"]].drop_duplicates()
    _create(con, "competitions", comps.merge(keys))
    _create(con, "matches", matches)
    con.execute("CREATE TABLE frames_360 (match_id BIGINT, event_id VARCHAR, teammate BOOLEAN, "
                "actor BOOLEAN, keeper BOOLEAN, x DOUBLE, y DOUBLE)")

    # Event tables are small enough to concatenate (column types are then inferred
    # from every match at once); 360 frames are large, so they go in match by match.
    parts: dict[str, list[pd.DataFrame]] = {}
    for i, mid in enumerate(matches["match_id"], start=1):
        parts.setdefault("lineups", []).append(
            flatten_lineups(mid, _read(raw_dir / f"lineups/{mid}.json")))
        for table, df in flatten_events(mid, _read(raw_dir / f"events/{mid}.json")).items():
            parts.setdefault(table, []).append(df)
        p360 = raw_dir / f"three-sixty/{mid}.json"
        if p360.exists():
            _create(con, "frames_360", flatten_360(mid, _read(p360)), append=True)
        print(f"[{i}/{len(matches)}] match {mid}", flush=True)

    for table, dfs in parts.items():
        _create(con, table, pd.concat(dfs, ignore_index=True))
    con.execute("ALTER TABLE events ALTER details TYPE JSON")
    con.close()
    return db_path


def connect(db_path: Path = DB_PATH, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    if not db_path.exists():
        raise SystemExit(f"{db_path} not found: run `python -m fdl build` first")
    return duckdb.connect(str(db_path), read_only=read_only)
