# 02-tx-comptroller-extract

Daily tasks that download the two Texas Comptroller datasets and stage them with a derived federal EIN.

Bound by `docs/specs/00-product/spec.md` (decisions 4 to 7 and 10 to 12) and `docs/data-sources.md` section 2. It reuses `download_if_changed`, `connect`, `copy_to_parquet` and the name macros.

## Goal

Two more task chains in `tx_retiring_owners` download two exports from data.texas.gov when their `ETag` changes. One is Active Franchise Taxpayers, at 3.5 million rows; the other is Active Sales Tax Permit Holders, at 0.9 million rows. The chains rebuild `include/data/stage/tx_franchise.parquet` and `include/data/stage/tx_sales_outlets.parquet`. Both files carry `ein` derived from the taxpayer number, a normalized name, typed dates and `zip5`. The franchise file supplies the SOS charter date. The outlets file supplies trade names and first-sales dates.

## What the user can do afterwards

```
scripts/smoke.sh 7200
uv run python -c "import duckdb; print(duckdb.sql(\"select taxpayer_number, ein, taxpayer_name, charter_date, right_to_transact from 'include/data/stage/tx_franchise.parquet' where taxpayer_number = '17502899705'\"))"
```

The query prints Texas Instruments with `ein` 750289970 and `charter_date` 1938-12-31. A second run logs `unchanged` for both downloads.

## Anti-goals

- No filtering by status, organization type or NAICS at stage time. Spec 04 filters.
- No Socrata app token, unless the first full download gets HTTP 429. If it does, add `SOCRATA_APP_TOKEN` to `.env`, send it as `X-App-Token`, and record it in the notes.
- No use of the row-level JSON API in the pipeline. It is for spot checks only.
- No check-digit validation. Only digits 2 to 10 of the taxpayer number are used.

## Files and interfaces

- `include/pipeline/texas.py`:
  - `DATASETS = {"tx_franchise": "9cir-efmm", "tx_sales_outlets": "jrea-zgmq"}`, with export URL `https://data.texas.gov/api/views/{id}/rows.csv?accessType=DOWNLOAD`.
  - `HEADERS`: for each dataset, the exact header row the export serves today, stray spaces included (copy it from `docs/data-sources.md`), and the snake_case names to assign in the same order.
  - `download(name: str, data: Path = DATA) -> bool` calls `download_if_changed(url, data / "raw/tx" / f"{name}.csv")`. The export's HEAD returns `Content-Length: 0`, so the helper's size check does not apply here.
  - `stage(name: str, data: Path = DATA, min_rows: int | None = None) -> int` works in three steps:
    1. Compare the file's first line with the expected header for `name`. If they differ, raise with both headers in the message: a renamed or reordered column must stop the pipeline, not shift data into the wrong field.
    2. Read the file with `read_csv(..., header=true, all_varchar=true, names=[...])`.
    3. Write the result with `copy_to_parquet` to `data/stage/{name}.parquet`.

    Dates are parsed with `try_strptime(x, '%m/%d/%Y')::DATE`. `ein` is `substr(taxpayer_number, 2, 9)` when the number starts with `1`, and NULL otherwise.
    - `tx_franchise` has one row per `taxpayer_number`. Today's export has 31 duplicate numbers in 3,486,216 rows. They are exact or near duplicates that differ only in charter date or status (verified). Keep one row with `qualify row_number() over (partition by taxpayer_number order by (sos_status = 'A') desc, sos_status_date desc nulls last, charter_date) = 1`, and log how many rows were dropped.
    - `tx_franchise` columns: `taxpayer_number`, `ein`, `taxpayer_name`, `norm_name`, `address`, `city` (uppercased and trimmed), `state`, `zip5`, `county_code`, `org_type`, `record_type`, `responsibility_begin_date`, `sos_file_number`, `charter_date`, `sos_status_date`, `sos_status`, `right_to_transact`, `exempt_reason`, and `naics` (`nullif(..., '')`).
    - `tx_sales_outlets` has one row per outlet: 890,307 rows across 705,284 taxpayers. Its columns: `taxpayer_number`, `ein`, `taxpayer_name`, `norm_taxpayer_name`, `org_type`, `outlet_number`, `outlet_name`, `norm_outlet_name`, `outlet_address`, `outlet_city`, `outlet_zip5`, `outlet_naics`, `permit_issue_date`, `first_sales_date`.
    - Assertions:
      - The row floor holds. When `min_rows` is not given, it is 3,000,000 for franchise and 800,000 for outlets.
      - No row has a non-empty raw date that parsed to NULL.
      - Every taxpayer number that starts with `1` yields a 9-digit `ein`.
      - In the franchise stage, `taxpayer_number` is unique, more than 0 and fewer than 1,000 duplicate rows were dropped, and taxpayer `17502899705` is present with charter date 1938-12-31.

      Each dataset logs one summary line.
- `dags/tx_retiring_owners.py`: add `tx_download.expand(name=list(DATASETS))`, then `tx_stage.expand(name=list(DATASETS))`. The chain is independent of the PPP tasks. The download timeout is 2 hours and the stage timeout is 30 minutes.
- `tests/fixtures/tx/tx_franchise.csv` and `tests/fixtures/tx/tx_sales_outlets.csv` use the exact served headers, with five or six rows each. Between them they cover:
  - the Texas Instruments row
  - a taxpayer number starting with `3`
  - a record type `X` row with a blank charter date
  - a duplicated taxpayer number, where one copy has status `A` and the other `F`
  - an outlet whose name differs from its taxpayer name

  Two more fixtures exist only for failure tests: one with a renamed header, and one with a malformed date.
- `tests/unit/test_texas.py`:
  - Staging the fixtures with the floors set to 1 yields the exact `ein`, `charter_date`, `norm_name`, `norm_outlet_name` and NULL values per row. The duplicate resolves to its status `A` copy.
  - The fixture with a renamed header raises.
  - The fixture with a malformed date raises.

## End-to-end verification

1. Run `scripts/smoke.sh 7200` and paste its output. Both `tx_download` tasks log `downloaded` with byte counts, and both `tx_stage` tasks log row counts and the dropped-duplicate count.
2. Paste these three queries and their output into the commit body:
   - the Texas Instruments query above
   - `select right_to_transact, count(*) from 'include/data/stage/tx_franchise.parquet' group by 1 order by 2 desc`
   - `select count(*), count(ein) from 'include/data/stage/tx_sales_outlets.parquet'`
3. Run `scripts/smoke.sh` again. Both downloads log `unchanged`.
4. `mise run check` passes.
