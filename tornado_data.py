"""Fetch and read historical tornado reports from NOAA NCEI Storm Events.

The archive contains one details CSV per year. This module discovers the
published archive files from NOAA's directory listing, downloads only the
requested years, and returns one row per tornado event.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import html
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


ARCHIVE_URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
ARCHIVE_RE = re.compile(
    r"StormEvents_details-ftp_v1\.0_d(?P<year>\d{4})_c(?P<compiled>\d{8})\.csv\.gz"
)

# U.S. Census South region: South Atlantic, East South Central, and West South Central.
REGIONS: dict[str, tuple[str, ...]] = {
    "south": ("DE", "MD", "VA", "WV", "KY", "NC", "SC", "GA", "FL", "AL", "MS", "TN", "AR", "LA", "OK", "TX"),
    "southeast": ("DE", "MD", "VA", "WV", "KY", "NC", "SC", "GA", "FL", "AL", "MS", "TN"),
    "west-south-central": ("AR", "LA", "OK", "TX"),
    "east-south-central": ("KY", "TN", "AL", "MS"),
}

STATE_ABBREVIATIONS = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL",
    "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA",
    "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN",
    "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR",
    "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA",
    "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
}

OUTPUT_FIELDS = (
    "EVENT_ID", "EPISODE_ID", "EVENT_DATE", "BEGIN_DATE_TIME", "STATE", "CZ_NAME", "BEGIN_LOCATION",
    "TOR_F_SCALE", "EPISODE_NARRATIVE", "EVENT_NARRATIVE", "SOURCE_FILE",
)


def _request(url: str, *, timeout: int = 90):
    request = urllib.request.Request(url, headers={"User-Agent": "tornado-seasonality/1.0 (historical research)"})
    return urllib.request.urlopen(request, timeout=timeout)


def _download_with_progress(url: str, destination: Path, filename: str) -> None:
    """Stream one archive file to disk while updating its current progress line."""
    terminal = sys.stderr.isatty()
    last_report = 0.0
    downloaded = 0
    with _request(url, timeout=180) as response, destination.open("wb") as output:
        raw_total = response.headers.get("Content-Length")
        total = int(raw_total) if raw_total and raw_total.isdigit() else None
        sys.stderr.write(f"Downloading {filename}: starting...\r")
        sys.stderr.flush()
        while chunk := response.read(64 * 1024):
            output.write(chunk)
            downloaded += len(chunk)
            now = time.monotonic()
            if terminal:
                amount = f"{downloaded / 1_048_576:.1f} MB"
                if total:
                    percent = min(downloaded / total * 100, 100)
                    message = f"Downloading {filename}: {percent:5.1f}% ({amount} / {total / 1_048_576:.1f} MB)"
                else:
                    message = f"Downloading {filename}: {amount}"
                sys.stderr.write("\r" + message.ljust(120))
                sys.stderr.flush()
            elif now - last_report >= 5:
                amount = f"{downloaded / 1_048_576:.1f} MB"
                if total:
                    message = f"Downloading {filename}: {downloaded / total * 100:.1f}% ({amount} / {total / 1_048_576:.1f} MB)"
                else:
                    message = f"Downloading {filename}: {amount}"
                print(message, file=sys.stderr)
                last_report = now
    if terminal:
        size = destination.stat().st_size / 1_048_576
        sys.stderr.write(f"\rDownloaded {filename}: 100.0% ({size:.1f} MB)".ljust(120) + "\n")
        sys.stderr.flush()
    else:
        print(f"Downloaded {filename}: {downloaded / 1_048_576:.1f} MB", file=sys.stderr)


def available_archive_years() -> list[int]:
    """Return years present in NCEI's public archive directory listing."""
    with _request(ARCHIVE_URL) as response:
        listing = response.read().decode("utf-8", errors="replace")
    return sorted({int(match.group("year")) for match in ARCHIVE_RE.finditer(html.unescape(listing))})


def _archive_files() -> dict[int, str]:
    with _request(ARCHIVE_URL) as response:
        listing = response.read().decode("utf-8", errors="replace")
    files: dict[int, str] = {}
    for match in ARCHIVE_RE.finditer(html.unescape(listing)):
        year = int(match.group("year"))
        name = match.group(0)
        if year not in files or name > files[year]:
            files[year] = name
    return files


def _states_for_region(region: str | None, states: Iterable[str] | None) -> set[str]:
    if states:
        selected = {state.strip().upper() for state in states if state.strip()}
    elif region:
        key = region.strip().lower().replace("_", "-").replace(" ", "-")
        try:
            selected = set(REGIONS[key])
        except KeyError as exc:
            raise ValueError(f"Unknown region {region!r}. Choose one of: {', '.join(REGIONS)}") from exc
    else:
        selected = set()
    if any(not re.fullmatch(r"[A-Z]{2}", state) for state in selected):
        raise ValueError("States must be two-letter postal abbreviations, such as AL, MS, or TX.")
    return selected


def _event_date(row: dict[str, str]) -> date | None:
    # These separate numeric fields are the most reliable representation in
    # the archive, including early years whose timestamp has a two-digit year.
    try:
        year_month = int((row.get("BEGIN_YEARMONTH") or "").strip())
        year = int((row.get("YEAR") or "").strip() or year_month // 100)
        month = year_month % 100
        day = int((row.get("BEGIN_DAY") or "").strip())
        return date(year, month, day)
    except (ValueError, TypeError):
        pass

    raw = row.get("BEGIN_DATE_TIME", "").strip()
    # The archive has used both slash-formatted and DD-MON-YY timestamps.
    for pattern in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%d-%b-%y %H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, pattern).date()
            if "%y" in pattern and row.get("YEAR", "").strip().isdigit():
                parsed = parsed.replace(year=int(row["YEAR"]))
            return parsed
        except ValueError:
            pass
    raw_date = row.get("BEGIN_DATE", "").strip()
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw_date, pattern).date()
        except ValueError:
            pass
    return None


def fetch_tornadoes(
    *,
    start_year: int | None,
    end_year: int | None,
    region: str | None = None,
    states: Iterable[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    cache_dir: str | Path | None = None,
) -> list[dict[str, str]]:
    """Download and filter tornado details for a state region and date range.

    If start_year is None, the first year in the currently published archive
    is used. Region/state filtering is applied to the event's STATE field.
    """
    archive = _archive_files()
    if not archive:
        raise RuntimeError(f"No annual details files were found at {ARCHIVE_URL}")
    first_year = min(archive)
    last_year = max(archive)
    start_year = first_year if start_year is None else start_year
    end_year = last_year if end_year is None else end_year
    if start_year > end_year:
        raise ValueError("start_year must be less than or equal to end_year")
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must be earlier than or equal to end_date")
    selected_states = _states_for_region(region, states)
    cache_dir = Path(cache_dir) if cache_dir is not None else Path(__file__).with_name(".tornado_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    years = [year for year in sorted(archive) if start_year <= year <= end_year]
    if not years:
        raise ValueError(f"No archive years found between {start_year} and {end_year}; available range is {first_year}-{last_year}.")

    results: list[dict[str, str]] = []
    for year in years:
        filename = archive[year]
        url = ARCHIVE_URL + filename
        cached_file = cache_dir / filename
        if cached_file.exists():
            print(f"Reading cached {filename}", file=sys.stderr)
        else:
            partial_file = cached_file.with_suffix(cached_file.suffix + ".part")
            try:
                _download_with_progress(url, partial_file, filename)
                # Do not retain an incomplete or invalid response as a cache hit.
                with gzip.open(partial_file, "rb") as check:
                    check.read(1)
                os.replace(partial_file, cached_file)
            except (OSError, urllib.error.URLError, EOFError) as exc:
                partial_file.unlink(missing_ok=True)
                raise RuntimeError(f"Could not download or validate NOAA file {url}: {exc}") from exc
        with gzip.open(cached_file, "rt", encoding="utf-8-sig", errors="replace", newline="") as text_stream:
            reader = csv.DictReader(text_stream)
            if not reader.fieldnames or "EVENT_TYPE" not in reader.fieldnames:
                raise RuntimeError(f"Unexpected NOAA CSV format in {filename}")
            for raw_row in reader:
                if (raw_row.get("EVENT_TYPE") or "").strip().casefold() != "tornado":
                    continue
                state_name = (raw_row.get("STATE") or "").strip().upper()
                state_abbr = STATE_ABBREVIATIONS.get(state_name, state_name if len(state_name) == 2 else "")
                if selected_states and state_abbr not in selected_states:
                    continue
                event_day = _event_date(raw_row)
                if event_day is None:
                    continue
                if start_date and event_day < start_date:
                    continue
                if end_date and event_day > end_date:
                    continue
                row = {field: (raw_row.get(field) or "").strip() for field in OUTPUT_FIELDS if field != "SOURCE_FILE"}
                row["EVENT_DATE"] = event_day.isoformat()
                row["STATE"] = state_abbr or state_name
                row["SOURCE_FILE"] = filename
                results.append(row)
    results.sort(key=lambda item: (item["EVENT_DATE"], item["STATE"], item["EVENT_ID"]))
    return results


def write_csv(rows: Iterable[dict[str, str]], path: str | Path) -> Path:
    """Write fetched rows to a portable CSV file."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output


def load_tornado_csv(path: str | Path) -> list[dict[str, str]]:
    """Read the normalized CSV written by write_csv()."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", help=f"Named region ({', '.join(REGIONS)})")
    parser.add_argument("--states", nargs="+", help="Two-letter state abbreviations; overrides --region")
    parser.add_argument("--start-year", type=int, help="First archive year; defaults to earliest available")
    parser.add_argument("--end-year", type=int, help="Last archive year; defaults to latest available")
    parser.add_argument("--start-date", type=date.fromisoformat, help="Optional inclusive date, YYYY-MM-DD")
    parser.add_argument("--end-date", type=date.fromisoformat, help="Optional inclusive date, YYYY-MM-DD")
    parser.add_argument("--output", type=Path, default=Path("tornadoes.csv"))
    parser.add_argument("--cache-dir", type=Path, default=Path(__file__).with_name(".tornado_cache"),
                        help="Directory for compressed NOAA annual files (reused on later runs)")
    args = parser.parse_args()
    rows = fetch_tornadoes(start_year=args.start_year, end_year=args.end_year, region=args.region,
                           states=args.states, start_date=args.start_date, end_date=args.end_date,
                           cache_dir=args.cache_dir)
    output = write_csv(rows, args.output)
    print(f"Saved {len(rows):,} tornado records to {output.resolve()}")


if __name__ == "__main__":
    main()
