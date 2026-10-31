"""Create a self-contained interactive SVG of tornadoes by week of year."""

from __future__ import annotations

import argparse
import calendar
import html
import math
import statistics
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from tornado_data import load_tornado_csv

WEEK_COUNT = 52
CANONICAL_YEAR = 2021  # Non-leap template gives stable month boundaries and labels.
SVG_NS = "http://www.w3.org/2000/svg"


def _date_from_row(row: dict[str, str]) -> date | None:
    normalized_date = row.get("EVENT_DATE", "").strip()
    if normalized_date:
        try:
            return date.fromisoformat(normalized_date)
        except ValueError:
            pass
    value = row.get("BEGIN_DATE_TIME", "")
    for pattern in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%d-%b-%y %H:%M:%S"):
        try:
            parsed = datetime.strptime(value, pattern).date()
            if "%y" in pattern and row.get("YEAR", "").strip().isdigit():
                parsed = parsed.replace(year=int(row["YEAR"]))
            return parsed
        except ValueError:
            pass
    return None


def _canonical_day(day: date) -> int:
    # Dates are compared by month/day across years. Feb. 29 is folded into
    # Feb. 28, keeping all leap-year records in the same seasonal bucket.
    month, month_day = day.month, day.day
    if month == 2 and month_day == 29:
        month_day = 28
    return (date(CANONICAL_YEAR, month, month_day) - date(CANONICAL_YEAR, 1, 1)).days + 1


def weekly_counts(rows: list[dict[str, str]]) -> tuple[list[int], list[list[dict[str, str]]]]:
    counts = [0] * WEEK_COUNT
    events: list[list[dict[str, str]]] = [[] for _ in range(WEEK_COUNT)]
    for row in rows:
        day = _date_from_row(row)
        if day is None:
            continue
        index = min((_canonical_day(day) - 1) // 7, WEEK_COUNT - 1)
        counts[index] += 1
        events[index].append(row)
    return counts, events


def weekly_annual_stats(rows: list[dict[str, str]]) -> tuple[list[float], list[float], int, int]:
    """Return mean and median week counts across complete calendar years."""
    counts_by_year: dict[int, list[int]] = {}
    for row in rows:
        day = _date_from_row(row)
        if day is None:
            continue
        year_counts = counts_by_year.setdefault(day.year, [0] * WEEK_COUNT)
        week_index = min((_canonical_day(day) - 1) // 7, WEEK_COUNT - 1)
        year_counts[week_index] += 1

    if not counts_by_year:
        return [0.0] * WEEK_COUNT, [0.0] * WEEK_COUNT, 0, 0

    first_year = min(counts_by_year)
    last_observed_year = max(counts_by_year)
    # NOAA's current calendar-year file is incomplete. Exclude it from the
    # per-year summaries; keep it in the request's total weekly counts.
    last_complete_year = min(last_observed_year, date.today().year - 1)
    if last_complete_year < first_year:
        years = sorted(counts_by_year)
    else:
        years = list(range(first_year, last_complete_year + 1))

    means, medians = [], []
    for week_index in range(WEEK_COUNT):
        annual_values = [counts_by_year.get(year, [0] * WEEK_COUNT)[week_index] for year in years]
        means.append(statistics.mean(annual_values))
        medians.append(statistics.median(annual_values))
    return means, medians, years[0], years[-1]


def _nice_axis(max_value: int, target_intervals: int = 5) -> tuple[int, list[int]]:
    """Choose 1-2-5-style tick spacing and a rounded-up axis maximum."""
    if max_value <= 0:
        return 1, [0, 1]
    raw_step = max_value / target_intervals
    magnitude = 10 ** math.floor(math.log10(raw_step))
    fraction = raw_step / magnitude
    nice_fraction = next((step for step in (1, 2, 5, 10) if fraction <= step), 10)
    tick_step = nice_fraction * magnitude
    axis_max = math.ceil(max_value / tick_step) * tick_step
    tick_count = int(round(axis_max / tick_step))
    ticks = [int(round(i * tick_step)) for i in range(tick_count + 1)]
    return int(axis_max), ticks


def _number_label(value: int | float) -> str:
    """Format counts with thousands separators and at most one decimal."""
    rounded = round(value, 1)
    if rounded.is_integer():
        return f"{int(rounded):,}"
    return f"{rounded:,.1f}"


def _week_label(index: int) -> str:
    start = date(CANONICAL_YEAR, 1, 1).toordinal() + index * 7
    extra_final_day = 1 if index == WEEK_COUNT - 1 else 0
    end = min(start + 6 + extra_final_day, date(CANONICAL_YEAR, 12, 31).toordinal())
    start_day, end_day = date.fromordinal(start), date.fromordinal(end)
    if start_day.month == end_day.month:
        return f"{start_day.strftime('%b')} {start_day.day:02d}-{end_day.day:02d}"
    return f"{start_day.strftime('%b %d')}-{end_day.strftime('%b %d')}"


def _month_boundaries() -> list[tuple[str, float, float]]:
    total = 365
    cursor = 0
    segments = []
    for month in range(1, 13):
        length = calendar.monthrange(CANONICAL_YEAR, month)[1]
        left = cursor / total * WEEK_COUNT
        cursor += length
        right = cursor / total * WEEK_COUNT
        segments.append((calendar.month_abbr[month], left, right))
    return segments


def render_svg(rows: list[dict[str, str]], output: str | Path, *, title: str = "Tornadoes by week of year") -> Path:
    counts, event_rows = weekly_counts(rows)
    max_count = max(counts, default=0)
    axis_max, tick_values = _nice_axis(max_count)
    plot_max = max(axis_max, 1)
    annual_means, annual_medians, first_annual_year, last_annual_year = weekly_annual_stats(rows)
    width, height = 1200, 560
    left, right, top, bottom = 76, 28, 72, 132
    plot_w, plot_h = width - left - right, height - top - bottom
    out = [f'<svg xmlns="{SVG_NS}" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {width} {height}" role="img" aria-labelledby="chartTitle chartDesc">']
    out += ['<title id="chartTitle">' + html.escape(title) + '</title>',
            '<desc id="chartDesc">52 bars show tornado reports by week of the calendar year. Hover or focus a bar for its week and count.</desc>',
            '<style>text{font-family:system-ui,-apple-system,Segoe UI,sans-serif;fill:#263238}.axis{stroke:#697579;stroke-width:1}.grid{stroke:#dbe3e5;stroke-width:1}.bar{fill:#287c8e;transition:fill .12s,opacity .12s}.week-group.active .bar{fill:#e76f51;stroke:#183e46;stroke-width:1.5}.hit-area{fill:transparent;pointer-events:all}.week-group{cursor:pointer}.month-bracket{stroke:#50646a;stroke-width:1.2;fill:none}.month-label{font-size:12px;font-weight:600}.tick{font-size:11px;fill:#526267}.tooltip{display:none;pointer-events:none}.tooltip.visible{display:block}.tooltip rect{fill:#172b32;rx:5}.tooltip text{fill:#fff;font-size:12px}.small{font-size:11px;fill:#54666a}</style>']
    out.append(f'<text x="{left}" y="32" font-size="20" font-weight="700">{html.escape(title)}</text>')

    for tick in tick_values:
        y = top + plot_h * (1 - tick / plot_max)
        out.append(f'<line class="grid" x1="{left}" x2="{width-right}" y1="{y:.2f}" y2="{y:.2f}"/>')
        out.append(f'<text class="tick" x="{left-10}" y="{y+4:.2f}" text-anchor="end">{tick:,}</text>')
    out.append(f'<line class="axis" x1="{left}" x2="{left}" y1="{top}" y2="{top+plot_h}"/><line class="axis" x1="{left}" x2="{width-right}" y1="{top+plot_h}" y2="{top+plot_h}"/>')
    out.append(f'<text transform="translate(22 {top+plot_h/2}) rotate(-90)" text-anchor="middle" font-size="13">Number of tornadoes</text>')

    bar_w = plot_w / WEEK_COUNT
    tooltip_elements: list[str] = []
    for index, count in enumerate(counts):
        x = left + index * bar_w + 2
        bar_height = plot_h * count / plot_max
        y = top + plot_h - bar_height
        label = _week_label(index)
        tooltip_x = min(max(x + bar_w / 2 - 96, left), width - right - 196)
        cell_x = left + index * bar_w
        details = f"Week {index+1}: {label} - {_number_label(count)} tornado{'es' if count != 1 else ''}"
        out.append(f'<g class="week-group" data-index="{index}" tabindex="0" role="group" aria-label="{html.escape(details, quote=True)}">')
        out.append(f'<rect class="hit-area" x="{cell_x:.2f}" y="{top}" width="{bar_w:.2f}" height="{plot_h}"/>')
        out.append(f'<rect class="bar" data-count="{count}" x="{x:.2f}" y="{y:.2f}" width="{max(bar_w-4, 1):.2f}" height="{max(bar_height, 0.8):.2f}" rx="1.5"/>')
        tooltip_y = max(top + 2, y - 82)
        out.append('</g>')
        tooltip_elements.append(
            f'<g id="tooltip-{index}" class="tooltip" transform="translate({tooltip_x:.2f},{tooltip_y:.2f})"><rect width="196" height="72"/><text x="8" y="16">{html.escape(label)}</text><text x="8" y="32">{_number_label(count)} tornado{"es" if count != 1 else ""}</text><text x="8" y="48">Annual mean: {_number_label(annual_means[index])}</text><text x="8" y="64">Annual median: {_number_label(annual_medians[index])}</text></g>'
        )

    # Brackets and labels align to the actual month boundaries in the 365-day template.
    bracket_y, label_y = top + plot_h + 18, top + plot_h + 43
    for month, start, end in _month_boundaries():
        x1, x2 = left + plot_w * start / WEEK_COUNT, left + plot_w * end / WEEK_COUNT
        out.append(f'<path class="month-bracket" d="M{x1:.2f},{bracket_y+5} V{bracket_y} H{x2:.2f} V{bracket_y+5}"/>')
        out.append(f'<text class="month-label" x="{(x1+x2)/2:.2f}" y="{label_y}" text-anchor="middle">{month}</text>')
    out.append(f'<text class="small" x="{left}" y="{height-28}">Annual mean/median use complete years {first_annual_year}-{last_annual_year}.</text>')
    out.append(f'<text class="small" x="{left}" y="{height-12}">52 seven-day bins anchored on Jan 1; Feb 29 is grouped with Feb 28.</text>')
    out.append(f'<text class="small" x="{width-right}" y="{height-12}" text-anchor="end">Maximum observed: {max_count:,} per week</text>')
    # This overlay is emitted after every bar and axis element so no bar can
    # paint over a visible tooltip.
    out.append('<g id="tooltipOverlay" aria-hidden="true">' + "".join(tooltip_elements) + "</g>")
    out.append('''<script><![CDATA[
      (function(){
        const svg=document.documentElement;
        svg.querySelectorAll('.week-group').forEach(group=>{
          const tooltip=document.getElementById('tooltip-'+group.getAttribute('data-index'));
          const show=()=>{tooltip.classList.add('visible');group.classList.add('active');};
          const hide=()=>{tooltip.classList.remove('visible');group.classList.remove('active');};
          group.addEventListener('mouseenter',show);
          group.addEventListener('mouseleave',hide);
          group.addEventListener('focus',show);
          group.addEventListener('blur',hide);
        });
      })();
    ]]></script>''')
    out.append('</svg>')
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(out), encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="Normalized tornado CSV from tornado_data.py")
    parser.add_argument("--output", type=Path, default=Path("tornadoes_by_week.svg"))
    parser.add_argument("--title", default="Tornadoes by week of year")
    args = parser.parse_args()
    rows = load_tornado_csv(args.csv)
    path = render_svg(rows, args.output, title=args.title)
    print(f"Saved interactive SVG to {path.resolve()}")


if __name__ == "__main__":
    main()
