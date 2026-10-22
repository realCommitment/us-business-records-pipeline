# 03-dol-5500-extract implementation notes

## Real data, first full run (2026-10-17)

- 8 zips, 591 MB in total, downloaded two at a time. The DOL server reset the connection on 2 of them (`F_5500_SF_2023`, `F_5500_2024`; `ConnectionResetError(104)`). Both downloaded on Airflow's first retry, as the no-resume design intends, and no `.part` file was left behind. The whole run took 9m47s.
- `dol_5500_tx.parquet` has 66,202 Texas sponsor EINs, inside the spec's expected 50,000 to 70,000. 58,559 of them have a signer: 51,738 from an administrator who is the sponsor, 6,821 signed by the sponsor, and 7,643 with none. 2,955 have had a defined-benefit plan. By the latest filing's form, 13,884 are Form 5500 and 52,318 are 5500-SF; 42,625 of the latest filings are for form year 2025.
- `min_rows` defaults to 46,000, about 70% of the observed count.
- The oldest `earliest_plan_eff_date` is 1900-01-01, KITE'S CLEANERS, INC.'s profit-sharing plan, which is almost certainly a placeholder. It is the only one; the next oldest is 1900-11-10, a San Antonio firemen's relief fund, and then several from the 1920s. The stage keeps dates as published, and spec 04 decides what to do with implausible ages.
- Texas Instruments (750289970) has 5 plans and `ever_defined_benefit` true. Its latest filing, form year 2025, has no sponsor signature and no administrator signature that counts.

## Decisions the spec did not cover

- **Strict casts, checked before writing**, as in specs 01 and 02. Dates are ISO, so `plan_eff_date::DATE` and the other casts fail the stage on a malformed value instead of producing NULL. The floor, uniqueness and Texas Instruments checks run on a temp table before `copy_to_parquet` replaces the stage file.
- **`ACK_ID` breaks ties.** Two filings from one sponsor received on the same day for the same plan year, such as a 401(k) and a defined-benefit plan, would otherwise be picked arbitrarily, and `is_defined_benefit` or the signer could change from run to run. `ACK_ID` starts with the submission timestamp, so `ack_id desc` keeps the last one submitted. It is used for the tiebreak only and is not in the output.
- **The spec's `full` CTE is named `full_5500`**, because `FULL` is a reserved word in SQL.
- **No `nullif(x, '')` on every field.** DuckDB's `read_csv` already reads empty fields, quoted or not, as NULL (verified during spec 01).
- **The real files are clean.** On a 38 MB sample of the 2024 5500-SF CSV (51,376 lines), the data is valid UTF-8 and pure ASCII, with CRLF line endings and no newlines inside fields. Text is quoted; numbers and blanks are not.
- **Fixture headers are the real 2024 header lines**, 191 columns for 5500-SF and 140 for 5500. They were inflated from the first 256 KB of each zip, because the `_layout.txt` files describe fields but are not header rows. Two fixture rows are the real first rows of the 2024 5500-SF file (NORTH TEXAS COMPRESSION, INC. and EXCOLO CONSTRUCTION). The Texas defined-benefit sponsor is Texas Instruments, because the stage's sentinel check needs EIN 750289970 to be present.
- **`extract` logs `extracted <file>`** each time it writes a CSV, so a second run's logs show that nothing was extracted again.
- **Form 5500's DBA comes from `SPONS_DFE_DBA_NAME`.** The spec assumed the full form has no DBA and asked for NULL, but all four Form 5500 files (2022 to 2025) have the column. 1,458 staged sponsors now carry a DBA name.

## Code review (`/code-review high` on the uncommitted diff)

Fixed:
- Form 5500's `sponsor_dba_name` was hard-coded to NULL although the column exists. See above.

Skipped, with evidence or a reason:
- "Filtering to Texas before the per-EIN window ignores a sponsor's out-of-state filings." The spec defines `filings` as Texas-only and computes the aggregates over those.
- "`union_by_name` would silently NULL a column one year renames." Every column the stage uses exists in all eight files today; the files have 136 to 140 and 184 to 191 columns. A column missing from every file would still fail the bind loudly.
- "Stale zips or CSVs in `raw/dol` would be staged." `YEARS` only grows, and the member names follow one pattern (verified).
- "A late amendment of an old plan year beats the current-year filing." The spec orders by `date_received` on purpose, so the most recent contact details win.
- "A corrupt zip of the right size fails `extract` every day." Downloading it again would fetch the same corrupt bytes from the server. The daily failure is the loud signal.
- "`plan_count` should count plan numbers, not names." The spec defines it by name, and spec 04 does not use it.
- "Text fields are not trimmed." No staged signer, sponsor name or phone has leading or trailing whitespace or is blank (checked on the full stage).
- "The `.part`/`os.replace` pattern is written three times." It is a cleanup with no correctness effect. Each copy is five lines, and a shared helper would add an abstraction the plan did not ask for.
