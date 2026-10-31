"""Fetch all available historical tornadoes across the American South and chart them."""

from __future__ import annotations

import argparse
from pathlib import Path

from tornado_chart import render_svg
from tornado_data import available_archive_years, fetch_tornadoes, write_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, help="Defaults to the first year NOAA currently has available")
    parser.add_argument("--end-year", type=int, help="Defaults to the latest year NOAA currently has available")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--cache-dir", type=Path, default=Path(__file__).with_name(".tornado_cache"),
                        help="Directory for compressed NOAA annual files reused on later runs")
    args = parser.parse_args()

    years = available_archive_years()
    if not years:
        parser.error("NOAA's archive directory did not list any annual details files.")
    start_year = args.start_year if args.start_year is not None else years[0]
    end_year = args.end_year if args.end_year is not None else years[-1]

    rows = fetch_tornadoes(start_year=start_year, end_year=end_year, region="south", cache_dir=args.cache_dir)
    csv_path = write_csv(rows, args.output_dir / f"south_tornadoes_{start_year}_{end_year}.csv")
    svg_path = render_svg(
        rows,
        args.output_dir / f"south_tornadoes_by_week_{start_year}_{end_year}.svg",
        title=f"American South tornadoes by week ({start_year}-{end_year})",
    )
    print(f"Fetched {len(rows):,} records for the American South ({start_year}-{end_year}).")
    print(f"CSV: {csv_path.resolve()}")
    print(f"SVG: {svg_path.resolve()}")


if __name__ == "__main__":
    main()
