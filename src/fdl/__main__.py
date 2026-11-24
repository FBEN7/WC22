"""Command line: python -m fdl {download,build,quality}."""

from __future__ import annotations

import argparse

from fdl.config import DEFAULT_SEASONS, FIXTURE_MATCHES


def _season(s: str) -> tuple[int, int]:
    comp, season = s.split(":")
    return int(comp), int(season)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="fdl")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="download StatsBomb Open Data into data/raw")
    d.add_argument("--season", type=_season, action="append",
                   help="competition_id:season_id, repeatable "
                        "(default: WC 2018 & 2022, Euro 2020 & 2024, Copa America 2024, "
                        "AFCON 2023)")
    d.add_argument("--fixtures", action="store_true", help="only the 3 test-suite matches")
    d.add_argument("--max-matches", type=int, help="per season, for a quick start")
    d.add_argument("--with-360", action="store_true",
                   help="also download 360 freeze frames where available (~2 GB more)")

    sub.add_parser("build", help="(re)build data/warehouse.duckdb from data/raw")
    sub.add_parser("quality", help="run the M1 data-quality checks on the warehouse")
    sub.add_parser("report", help="pressing analysis: figures and tables in reports/pressing/")

    args = ap.parse_args(argv)
    if args.cmd == "download":
        from fdl.ingest import download

        if args.fixtures:
            download(match_ids=FIXTURE_MATCHES, with_360=True)  # the tests use them
        else:
            download(seasons=args.season or DEFAULT_SEASONS,
                     max_matches=args.max_matches, with_360=args.with_360)
    elif args.cmd == "build":
        from fdl.warehouse import build

        print(f"warehouse: {build()}")
    elif args.cmd == "quality":
        from fdl.quality import run_all
        from fdl.warehouse import connect

        with connect() as con:
            print(run_all(con).to_string(index=False))
    elif args.cmd == "report":
        from fdl.pressing import REPORT_DIR, report
        from fdl.warehouse import connect

        with connect() as con:
            report(con)
        print(f"written to {REPORT_DIR}")


if __name__ == "__main__":
    main()
