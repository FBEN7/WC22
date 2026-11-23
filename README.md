# WC22

An end-to-end event-data project on **StatsBomb Open Data**, built the way a
data provider works: raw JSON → a DuckDB warehouse → automated data-quality
checks → analytical SQL → expected-goals and expected-threat models → a
Streamlit app for non-technical users.

```
StatsBomb Open Data (JSON)
        │  python -m fdl download        cached in data/raw
        ▼
DuckDB warehouse                         python -m fdl build
  matches · lineups · events · passes · carries · shots
  shot_freeze_frames · frames_360
        │
        ├── M1  data-quality checks      src/fdl/quality.py     python -m fdl quality
        ├── M2  analytical SQL           sql/*.sql  (minutes played, passing p90, PPDA)
        ├── M3  xG model                 src/fdl/xg.py  (freeze-frame features, grouped CV)
        ├── M4  expected threat          src/fdl/xt.py
        └── M5  Streamlit app            app/streamlit_app.py
```

> **Status:** work in progress. The training brief, in French, is in [BRIEF.md](BRIEF.md).

| Milestone | Status |
|---|---|
| Foundation: ingest + warehouse + test harness | done |
| M1 Data quality | to do |
| M2 SQL | to do |
| M3 xG | to do |
| M4 xT | to do |
| M5 App | to do (Match centre page done) |
| M6 Findings write-up | to do |

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

python -m fdl download --fixtures  # 3 matches (~30 MB), enough for the tests
pytest                             # unfinished milestones show as SKIPPED "TODO"

python -m fdl download             # World Cup 2022, Euro 2020, Euro 2024 (~2 GB, all with 360 data)
python -m fdl build                # data/warehouse.duckdb
python -m fdl quality              # M1 summary
streamlit run app/streamlit_app.py
```

Other seasons: `python -m fdl download --season 9:281` (Bundesliga 2023/24), then
`python -m fdl build`. `data/raw/competitions.json` lists what is available.

## Data model

All coordinates are StatsBomb's: a 120 × 80 pitch, **every event seen from the
team performing it, attacking towards x = 120**. Period 5 is the penalty
shoot-out. `passes.outcome IS NULL` means the pass was completed.
`events.details` keeps every type-specific field as JSON (query it with
`details->>'$.duel.type.name'`). `lineups` is loaded as delivered, defects
included: M1 finds them.

## Findings

To be written at M6.

## Data

Data provided by [StatsBomb Open Data](https://github.com/statsbomb/open-data).
Read the licence in that repository before publishing anything built on it:
it requires attribution to StatsBomb.
