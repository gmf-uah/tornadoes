View American South data at https://gmf-uah.github.io/tornadoes

# Tornado seasonality tools

These scripts use the NOAA NCEI Storm Events annual details archive. The archive currently begins in 1950; the South runner discovers the first and last years available when it runs. It counts each NOAA tornado event record once. Records include the event and episode IDs, date, state, beginning location, EF/F scale, and available narrative fields.

The South region is the U.S. Census South: DE, MD, VA, WV, KY, NC, SC, GA, FL, AL, MS, TN, AR, LA, OK, and TX. NOAA's downloadable annual files are large compressed datasets, so the first run downloads each selected year from NCEI.

## Run the full South history

```powershell
python south_tornado_seasonality.py
```

This writes a normalized CSV and an interactive, self-contained SVG into `output/`. Open the SVG in a modern browser. Hover or keyboard-focus a bar for the week, total count in the request, and annual mean and median. The chart uses a linear scale with 1-2-5-style “nice” y-axis ticks. Annual mean and median use complete calendar years; the current partial year is excluded. Compressed NOAA annual files are kept in `.tornado_cache` and reused on later runs, so an interrupted run can resume without downloading completed years again.

## Fetch another region or timeframe

```powershell
python tornado_data.py --region southeast --start-year 1990 --end-year 2020 --output southeast.csv
python tornado_chart.py southeast.csv --output southeast.svg --title "Southeast tornadoes, 1990–2020"
```

Supported named regions are `south`, `southeast`, `east-south-central`, and `west-south-central`. Supply `--states AL MS TN` instead of `--region` to choose state abbreviations directly. Start/end years are inclusive and can be paired with optional inclusive `--start-date YYYY-MM-DD` and `--end-date YYYY-MM-DD` bounds.

The chart always has 52 seven-day bins anchored on January 1 in a non-leap calendar template. Feb. 29 reports are grouped with Feb. 28; the final bin absorbs the remaining year-end date. Month names sit under brackets marking calendar month boundaries. The SVG contains the data and interaction logic, so it works offline after generation.

Source: [NOAA NCEI Storm Events CSV archive](https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/).
