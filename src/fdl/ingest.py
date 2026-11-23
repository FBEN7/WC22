"""Download StatsBomb Open Data into a local cache (data/raw), mirroring the repo layout.

    data/raw/competitions.json
    data/raw/matches/{competition_id}/{season_id}.json
    data/raw/events/{match_id}.json
    data/raw/lineups/{match_id}.json
    data/raw/three-sixty/{match_id}.json   (only where 360 data exists)

Files already in the cache are never downloaded again.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from fdl.config import BASE_URL, RAW_DIR

_session = requests.Session()


class NotAvailable(Exception):
    """The file does not exist upstream (HTTP 404)."""


def fetch(rel_path: str, raw_dir: Path = RAW_DIR, retries: int = 4) -> Path:
    """Return the cached path of `rel_path`, downloading it first if needed."""
    dest = raw_dir / rel_path
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{BASE_URL}/{rel_path}"
    for attempt in range(retries):
        try:
            resp = _session.get(url, timeout=60)
            if resp.status_code == 404:
                raise NotAvailable(url)
            resp.raise_for_status()
            json.loads(resp.content)  # refuse to cache a truncated file
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(resp.content)
            tmp.replace(dest)
            return dest
        except NotAvailable:
            raise
        except (requests.RequestException, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def load(rel_path: str, raw_dir: Path = RAW_DIR):
    return json.loads(fetch(rel_path, raw_dir).read_text(encoding="utf-8"))


def season_matches(competition_id: int, season_id: int, raw_dir: Path = RAW_DIR) -> list[dict]:
    return load(f"matches/{competition_id}/{season_id}.json", raw_dir)


def find_season_of(match_ids: Iterable[int], raw_dir: Path = RAW_DIR) -> set[tuple[int, int]]:
    """Seasons (competition_id, season_id) that contain the given matches."""
    wanted, found = set(match_ids), set()
    for comp in load("competitions.json", raw_dir):
        key = (comp["competition_id"], comp["season_id"])
        if not comp.get("match_available_360"):
            continue  # fixture matches all come from 360 seasons; keeps the search short
        ids = {m["match_id"] for m in season_matches(*key, raw_dir)}
        if ids & wanted:
            found.add(key)
            wanted -= ids
        if not wanted:
            break
    if wanted:
        raise ValueError(f"matches not found in StatsBomb Open Data: {sorted(wanted)}")
    return found


def _fetch_match(match_id: int, raw_dir: Path, with_360: bool) -> tuple[int, bool]:
    fetch(f"events/{match_id}.json", raw_dir)
    fetch(f"lineups/{match_id}.json", raw_dir)
    has_360 = False
    if with_360:
        try:
            fetch(f"three-sixty/{match_id}.json", raw_dir)
            has_360 = True
        except NotAvailable:
            pass
    return match_id, has_360


def download(
    seasons: Iterable[tuple[int, int]] = (),
    match_ids: Iterable[int] | None = None,
    max_matches: int | None = None,
    with_360: bool = True,
    raw_dir: Path = RAW_DIR,
    workers: int = 8,
) -> list[int]:
    """Download the given seasons (optionally only some matches). Returns the match ids."""
    seasons = set(seasons)
    if match_ids is not None:
        match_ids = set(match_ids)
        seasons |= find_season_of(match_ids, raw_dir)
    load("competitions.json", raw_dir)

    todo: list[int] = []
    for comp_id, season_id in sorted(seasons):
        ms = sorted(season_matches(comp_id, season_id, raw_dir), key=lambda m: m["match_id"])
        if match_ids is not None:
            ms = [m for m in ms if m["match_id"] in match_ids]
        if max_matches is not None:
            ms = ms[:max_matches]
        todo += [m["match_id"] for m in ms]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (mid, has_360) in enumerate(
            pool.map(lambda m: _fetch_match(m, raw_dir, with_360), todo), start=1
        ):
            print(f"[{i}/{len(todo)}] match {mid}{'' if has_360 else ' (no 360)'}", flush=True)
    return todo
