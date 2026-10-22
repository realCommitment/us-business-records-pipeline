# 03-dol-5500-extract

Daily tasks that download the DOL Form 5500 and 5500-SF datasets and stage one row per Texas plan sponsor.

Bound by `docs/specs/00-product/spec.md` (decisions 4 to 7 and 10 to 12) and `docs/data-sources.md` section 3. It reuses `download_if_changed`, `connect`, `copy_to_parquet` and the name macros.

## Goal

For form years 2022 to 2025, the DAG downloads eight "Latest" zips, one Form 5500 and one Form 5500-SF zip per year, but only when their `ETag` changes. The zips total about 0.7 GB, or about 3 GB unzipped. The task rebuilds `include/data/stage/dol_5500_tx.parquet`: one row per sponsor EIN with a Texas mailing address, taken from that sponsor's most recently received filing. Each row carries:

- the signer name, when the signer represents the sponsor
- the sponsor phone
- participant counts
- pension plan codes and a defined-benefit flag
- the earliest plan effective date across all of the sponsor's filings

Spec 04 joins this on `ein`.

## What the user can do afterwards

```
scripts/smoke.sh 7200
uv run python -c "import duckdb; print(duckdb.sql(\"select count(*) sponsors, count(*) filter (where ever_defined_benefit) db, count(signer_name) with_signer, min(earliest_plan_eff_date) from 'include/data/stage/dol_5500_tx.parquet'\"))"
```

## Anti-goals

- No classification of welfare plans. Every filing is kept. Spec 04 reads `pension_codes` and the defined-benefit flags.
- No form years before 2022, and no discovery of new years. Use `YEARS = (2022, 2023, 2024, 2025)` with the comment `# shortcut: add the next form year by hand when DOL publishes its Latest zip; first filings for plan year N appear around July of N+1`.
- No schedules (SB, R, H). Only the main forms are read.
- No signer name from a third-party administrator. That signer is a service provider, not the owner.

## Files and interfaces

- `include/pipeline/dol.py`:
  - `YEARS`, `FORMS = ("F_5500", "F_5500_SF")`, and `url(form, year)`, which builds `https://askebsa.dol.gov/FOIA%20Files/{year}/Latest/{form}_{year}_Latest.zip`. The host returns a 301 redirect to `www.askebsa.dol.gov`, and the download helper follows it.
  - `download(url: str, data: Path = DATA) -> bool` calls `download_if_changed(url, data / "raw/dol" / <zip name>)`.
  - `extract(zip_path: Path) -> Path` writes the zip's single `.csv` member next to it, through a `.part` file and `os.replace`. Members are lowercase, for example `f_5500_sf_2024_latest.csv`, and sit beside a `_layout.txt` file (verified). It skips the work when the CSV exists and is newer than the zip. It raises when the zip does not contain exactly one CSV.
  - `stage(data: Path = DATA, min_rows: int = 40_000) -> int` extracts every zip, then writes `data/stage/dol_5500_tx.parquet` with one `copy_to_parquet`. The query builds it in four parts:
    - `sf` reads `read_csv(data/raw/dol/f_5500_sf_20??_latest.csv, header=true, all_varchar=true, union_by_name=true, filename=true)` and maps the source columns as follows:
      - `ein` from `SF_SPONS_EIN`
      - `sponsor_name` from `SF_SPONSOR_NAME`, and `sponsor_dba_name` from `SF_SPONSOR_DFE_DBA_NAME`
      - `address`, `city`, `state` and `zip` from `SF_SPONS_US_ADDRESS1`, `SF_SPONS_US_CITY`, `SF_SPONS_US_STATE` and `SF_SPONS_US_ZIP`
      - `phone` from `SF_SPONS_PHONE_NUM`, and `business_code` from `SF_BUSINESS_CODE`
      - `plan_name` from `SF_PLAN_NAME`
      - `plan_eff_date` from `SF_PLAN_EFF_DATE`, and `plan_year_begin` from `SF_PLAN_YEAR_BEGIN_DATE`
      - `date_received` from `DATE_RECEIVED`
      - `participants` from `SF_TOT_PARTCP_BOY_CNT`, and `active_participants` from `SF_TOT_ACT_PARTCP_BOY_CNT`
      - `pension_codes` from `SF_TYPE_PENSION_BNFT_CODE`
      - `signer_name` from `coalesce(SF_SPONS_SIGNED_NAME, SF_SPONS_MANUAL_SIGNED_NAME)`. When both are empty and `SF_ADMIN_NAME_SAME_SPON_IND = '1'`, it falls back to `coalesce(SF_ADMIN_SIGNED_NAME, SF_ADMIN_MANUAL_SIGNED_NAME)`. Wrap every field in `nullif(x, '')`.
      - `signer_source`: `'sponsor'`, `'admin_is_sponsor'` or NULL
      - `form` set to `'5500-SF'`, and `form_year` parsed from `filename`
    - `full` reads `f_5500_20??_latest.csv` into the same shape. That glob excludes the SF files. Its columns are `SPONS_DFE_EIN`, `SPONSOR_DFE_NAME`, a NULL dba, `SPONS_DFE_MAIL_US_*`, `SPONS_DFE_PHONE_NUM`, `BUSINESS_CODE`, `PLAN_NAME`, `PLAN_EFF_DATE`, `FORM_PLAN_YEAR_BEGIN_DATE`, `TOT_PARTCP_BOY_CNT`, `TOT_ACT_PARTCP_BOY_CNT`, `TYPE_PENSION_BNFT_CODE`, `SPONS_SIGNED_NAME` and `SPONS_MANUAL_SIGNED_NAME`. `ADMIN_SIGNED_NAME` and `ADMIN_MANUAL_SIGNED_NAME` are used only when `ADMIN_NAME_SAME_SPON_IND = '1'`. `form` is `'5500'`.
    - `filings` is `sf UNION ALL full`, filtered to `state = 'TX'` and to `ein` matching `^\d{9}$`. The data is clean enough for simple casts and slices:
      - Dates are ISO `YYYY-MM-DD` (verified on 2024), so `try_cast(x AS DATE)` parses them. Signature dates are timestamps with an offset and are not used.
      - ZIPs are 5 or 9 digits with no dash, so `zip5 = left(zip, 5)`.
      - `norm_name = norm_name(sponsor_name)`.
    - The output has one row per `ein`. It takes the filing with the latest `date_received`, with ties broken by the latest `plan_year_begin`, and adds these columns computed over all of that EIN's filings:
      - `plan_count`: the number of distinct plan names
      - `earliest_plan_eff_date`: the earliest plan effective date
      - `ever_defined_benefit`: `bool_or(regexp_matches(pension_codes, '1[A-I]'))`
      - `is_defined_benefit`: the same test on the latest filing only

      Codes are packed in pairs of a digit then a letter, for example `2E2J2K3D`, so the regex cannot match across a code boundary.
    - Assertions:
      - at least `min_rows` sponsors, since one year of 5500-SF alone has 41,514 Texas EINs
      - `ein` is unique
      - no row has a non-empty raw date that parsed to NULL
      - EIN `750289970` (Texas Instruments, which has 5 filings in the 2024 file) is present

      The task logs one summary line.
- `dags/tx_retiring_owners.py`: `dol_download.expand(url=[...8 urls...])`, then `dol_stage`. This chain is independent of the other two. Downloads get a 1 hour timeout and `max_active_tis_per_dag=2`. The stage gets a 30 minute timeout.
- `tests/fixtures/dol/` holds `f_5500_sf_2024_latest.csv` and `f_5500_2024_latest.csv`, which use the full real header rows, copied from the first line of the real 2024 CSVs (or the `_layout.txt` files at the URLs in `docs/data-sources.md`). Their rows are:
  - a Texas defined-benefit sponsor whose own signature name is filled
  - the same EIN again, with an earlier `DATE_RECEIVED` and a different plan effective in 1988
  - a Texas sponsor with only an admin signature and `ADMIN_NAME_SAME_SPON_IND = '1'`
  - a Texas sponsor with only an admin signature and a blank indicator
  - a sponsor outside Texas

  The test zips these CSVs itself.
- `tests/unit/test_dol.py`: staging the fixtures with `min_rows=1` yields exactly the expected EINs. It also checks:
  - The later filing supplies the row, but `earliest_plan_eff_date` is 1988.
  - `is_defined_benefit` is true only for the `1A` sponsor.
  - The admin signer is kept only when the indicator is `1`.
  - The row from outside Texas is absent.
  - `extract` raises on a zip that holds two CSVs.

## End-to-end verification

1. Run `scripts/smoke.sh 7200` and paste its output. All 8 `dol_download` map indexes log `downloaded`, and `dol_stage` logs the sponsor count.
2. Paste the query above into the commit body. Expect about 50,000 to 70,000 sponsors. Record the real count, and set `min_rows` to about 70% of it.
3. Run `scripts/smoke.sh` again. All 8 downloads log `unchanged`, and no CSV is extracted again.
4. `mise run check` passes.
