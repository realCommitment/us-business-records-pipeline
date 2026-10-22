# 04-match-and-shortlist implementation notes

## Real data, first full run (2026-10-17)

- `build` takes about 2 seconds over 759,013 PPP businesses, 3,486,185 registrations, 890,307 outlets and 66,202 plan sponsors. The whole DAG run takes about 36 seconds when nothing has to download.
- Matches by tier: tier 1 154,368, tier 2 40,401, tier 3 11,976, tier 4 15,784. That is 222,529 matched (29.3% of all PPP businesses), and 536,484 unmatched.
- The qc matched share, which leaves out sole proprietorships, self-employed individuals and independent contractors, is 58.0% (209,714 of 361,773). That is well above the product spec's 30% "fix normalization first" line.
- **Every industry, at the owner's request.** The trades-only allowlist cut about 26,700 qualifying businesses down to 3,623. It is gone; see the decision below.
- The shortlist has 25,842 businesses. 3,810 are 50 or older, 5,138 have a plan signer and a phone, and 158 have had a defined-benefit plan. The largest sectors are Construction 3,245, Retail Trade 3,154, Professional, Scientific, and Technical Services 3,093, Manufacturing 2,909, Wholesale Trade 2,207 and Health Care 2,069. The largest industry groups are Offices of Physicians 979, Restaurants and Other Eating Places 963, Building Equipment Contractors 952, Legal Services 711 and Automotive Repair and Maintenance 678.
- **Thresholds stay at the spec's defaults: `min_match_share = 0.30`, `min_rows = 100`.** The 0.30 is the product spec's own normalization line, not a fraction of today's 0.58. `min_rows` stays low because the owner tunes `MIN_YEARS` and `TARGET_NAICS`. A floor near today's 25,842 would fail the run after a legitimate tightening, and the match-share check already catches a broken match.

## Decisions the spec did not cover

- **`matches.parquet` holds every PPP business**, matched or not; unmatched ones have a NULL `match_tier`. `qc` needs the denominator of the matched share from the file it checks. The spec's tier query then also shows the unmatched count, which is the number to watch while tuning normalization.
- **Every pick is deterministic.** Two builds over identical input shortlisted 3,653 and 3,646 businesses, and 6,575 `matches` rows differed. The causes:
  - `arg_max` with tied keys, `any_value` and `mode` resolve ties by thread timing.
  - A DOUBLE `sum` differs in the last bits from run to run (30310.56 against 30310.559999999998).
  - Two PPP businesses tied on total and name, for example one company in two ZIPs matched to one taxpayer.

  The fixes:
  - The address, city, county and business type come from the latest loan, keyed `(date_approved, loan_number)`.
  - `business_name` is the longest name, then alphabetical.
  - `naics` is `mode(... order by date_approved desc, loan_number desc)`.
  - `dba_norm_name` is `min()`.
  - The outlet NAICS is the mode ordered by first sales date and outlet number.
  - `ppp_total_approved` is summed as `DECIMAL(18, 2)`.
  - The shortlist pick is ordered by `ppp_total_approved desc, norm_name, zip5`.

  After the fixes, four builds produced identical `matches` and shortlists, and a second same-day DAG run wrote a byte-identical `shortlist_latest.csv`.
- **1900-01-01 is ignored as an age date.** It appears exactly five times across the three sources, always as a placeholder. Four are pre-1900 nonprofits whose responsibility, charter and status dates are all 1900-01-01. The fifth is KITE'S CLEANERS, INC.'s profit-sharing plan "effective" 1900-01-01, which put a company chartered in 1975 at the top of the shortlist at 126 years old. The `age` CTE wraps each source in `nullif(..., date '1900-01-01')`. Real early dates such as 1843-03-17 and 1907-07-11 are kept. The fixtures cover it with PAPA HVAC INC, which has a 1900 plan date and a 1990 charter and is dated 36 years by its charter.
- **"Previous" means the newest exported partition.** `export` writes an empty `_exported` marker into the partition folder after both CSVs are written, and the anti-join baseline is the newest older partition that has one. Under the spec's literal rule, a run that failed `qc` would have left its partition as the next day's baseline, so businesses new that day would never appear as new. A build that died mid-write would have left an empty folder that broke every later export. `export` also refuses a `run_date` older than one already exported, so clearing an old run's export cannot overwrite the morning file with older data. Tested in `test_export_skips_unexported_runs_and_never_goes_back`.
- **The CSV sort ends in `taxpayer_number`**, which is unique, so tied rows always come out in the same order. The partition is not sorted; only the CSVs are.
- **The EIN comes from the stage files' `ein` column** (`texas.EIN`). Form 5500 is joined once, inside the `age` CTE, which carries the sponsor columns to the final select.
- **All industries; an exclusion list replaces the allowlist.** On 2026-10-17 the owner asked to cover every type of business, vetoing the product spec's trades-only default (recorded there). `TARGET_NAICS` is replaced by `EXCLUDED_NAICS`, which removes only what is not a business anyone can buy:
  - `813`: religious, grantmaking, civic, professional and labor organizations
  - `814`: private households
  - `92`: public administration

  The church fixture shows why the list is needed: churches are not always flagged nonprofit on their PPP loan. A business with no NAICS code at all is kept. You still tune the list with two constants, `MIN_YEARS` and `EXCLUDED_NAICS`. Licensed practices (law, medicine, dentistry) are included, although Texas lets only licensed professionals own them.
- **Official industry names come from the Census Bureau.** At the owner's request, which overrides the spec's anti-goal "No NAICS descriptions in the output", the export has three new columns: `sector` (2-digit), `industry_group` (4-digit) and `naics_title` (6-digit, or the longest known prefix for codes from older editions).
  - The names come from `include/pipeline/naics_2017.csv`, 2,196 codes converted once from the Census 2-6 digit 2017 file.
  - 2017 is the edition the data uses: 99.1% of Texas PPP codes match it exactly, against 90.0% for 2022; the sales-tax outlet codes match 98.6% against 61.0%.
  - Manufacturing, Retail and Transportation are listed as `31-33`, `44-45` and `48-49`, so a small macro maps their two-digit prefixes.
  - In today's export, 99.7% of rows have a sector, and the 67 without one have no code at all.
- **The `outlets` CTE has no `street_no`.** No tier uses one for outlets; tier 4 matches on ZIP and name.
- **Tier 4 is two equi-joins joined by `union all`** instead of one join on `name = norm_name or name = dba_norm_name`, so both stay hash joins.
- **`copy_to_parquet` takes `fmt="csv"`** for the two exports, so the CSVs go through the same `.part`-and-rename path as every Parquet file. DuckDB writes a CSV header by default (verified).
- **The DAG passes `build`'s `run_date` to `qc` and `export` as `built["run_date"]`.** Airflow infers `multiple_outputs` from the `dict[str, object]` return type.
- **The no-franchise-row path is limited to owners who owe no franchise tax.** The spec lets a tier-4 match through when it has no franchise row, meaning the sole-proprietor path. On the first run, 138 shortlist rows took that path. 122 were what it was meant for: 112 individual sole owners and 10 general partnerships. The other 16 were corporations, limited partnerships or LLCs (CT 13, PL 2, CL 1) with no row in the Active Franchise Taxpayers list, such as NORRIS MACHINE WORKS, INC. Entities that owe franchise tax should appear there while active, so those are probably inactive. The rule therefore admits only org types `S`, `IS`, `PB` and `PI` without a franchise row. That removed exactly those 16 rows (3,639 to 3,623) and added none. The fixture QUEBEC MACHINE WORKS INC, a corporation's outlet with no franchise row, stays out of the shortlist; under the old rule the test fails with 9 shortlisted instead of 8.

## Spec step 3: the charter-date check

The spec asks for five shortlist rows to be checked by hand in the Comptroller's taxable entity search. That page is a JavaScript front end to `api.comptroller.texas.gov`, which answers HTTP 403 without an API key, and this session had no browser. Instead, five rows (two from tier 1, then one each from tiers 2, 3 and 4) were compared with the publisher's typed records from the data.texas.gov row-level JSON API. All five agree on charter date, right to transact and earliest first-sales date:

| Tier | Business | Taxpayer | Ours | data.texas.gov |
| --- | --- | --- | --- | --- |
| 1 | TEXAS GRAPHIC RESOURCE, INC | 17502242104 | charter 1907-07-11, 119 y | charter 1907-07-11, rtt A |
| 1 | PRONTO PLUMBERS INC | 17408465601 | charter 1921-05-09, 105 y | charter 1921-05-09, rtt A |
| 2 | LITTLE PROFIT SPRINKLER AND LANDSCAPE | 10161505176 | charter 1986-03-11, 40 y | charter 1986-03-11, rtt A |
| 3 | GULFLANDS TRANSPORT INC. | 13200143785 | charter 1996-01-12, 30 y | charter 1996-01-12, rtt A |
| 4 | BERNARDO TRUCKING | 17425157629 | individual sole owner, first sales 1992-06-15, 34 y | no franchise row; earliest outlet BERNARDO TRUCKING (IS), first sales 1992-06-15 |

These five taxpayer numbers are ready for the by-hand check in the Comptroller's search. The tier-4 row was first NORRIS MACHINE WORKS, INC., which agreed too but left the shortlist under the no-franchise rule above.

## Code review (`/code-review high` on the uncommitted diff)

Fixed:
- A partition from a run that failed `qc` became the next day's baseline, and an empty partition folder from a crash broke every later export. Both are fixed by the `_exported` marker.
- Re-running an old export overwrote `shortlist_latest.csv` with older data. It now raises.
- `qc` divided by zero on an empty `matches` file. The share is now 0, so the assertion message explains the failure.
- The CSV sort could tie on `business_name`. `taxpayer_number` is now the last key.
- The EIN was derived again in three places. It now comes from the staged `ein`, and Form 5500 is joined once.
- The sort was defined both in the SQL and in `ORDER`. Only `ORDER` remains.
- `fmt` was a free string interpolated into COPY. It is now `Literal["parquet", "csv"]`, so mypy catches a typo. The function keeps the spec's name, `copy_to_parquet`.

Skipped:
- "`run_date` comes from the wall clock, not the logical date." That is product decision 8: the raw files are always today's snapshot, so an old logical date would misdate the data.
