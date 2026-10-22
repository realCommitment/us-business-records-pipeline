# 07-sba-loans

Stages every SBA 7(a) and 504 loan since fiscal 1991. Each SBA borrower joins the business it belongs to, or becomes a business of its own, bringing an industry code, a loan date that proves the business existed then, and charge-offs as a closure signal.

Bound by `docs/specs/00-product/spec.md`: decisions 4 to 9, 11, 12 and 16 to 19, and `docs/data-sources.md` section 7. It reuses `download_if_changed`, `connect`, `copy_to_parquet`, the name macros and the `parse_links` pattern of `national/ppp.py`.

## Goal

The DAG gains an SBA chain:

1. **Discover** the six FOIA CSVs on `https://data.sba.gov/dataset/7a-504-foia`:
   - 7(a): FY1991 to FY1999, FY2000 to FY2009, FY2010 to FY2019, and FY2020 to Present
   - 504: FY1991 to FY2009, and FY2010 to Present
2. **Download** each file when its `ETag` changes. Together they are about 1.0 GB.
3. **Stage** every loan, typed, into `stage/sba_loans.parquet`.

**In the transform**, loans group into SBA borrowers by `(norm_name, zip5)`. Each borrower is a record in product decision 9:

- It joins a registry business through tiers 1 to 4, or a sponsor's business through tiers 5 to 7.
- Otherwise it joins the leftover group with the same key, usually a PPP key.
- Otherwise it becomes a `KEY-` business of its own.

**What a business gains:**

- `sba_loan_count`, `sba_total_approved`, `sba_first_loan_date`, `sba_last_loan_date`
- `sba_first_business_age`, the age bucket the borrower reported on its first loan
- `sba_programs`
- `sba_charged_off`
- an industry code (decision 18, after PPP, Form 5500 and SAM)
- the `sba_loan` age candidate
- an activity signal, the approval, and a closure signal, the charge-off date

**Size of the gain.** Planning measured the two 1990s files alone: 13,988 PPP keys had a loan approved 30 or more years before 2026-10-17, and 11,102 of them were in states with no free registry. Borrowers without PPP add more businesses, many of them closed since; the charge-offs and `open_status` show which.

## What the user can do afterwards

```
scripts/smoke.sh 7200
uv run python -c "import duckdb; print(duckdb.sql(\"select count(*) filter (where list_contains(sources, 'sba')) with_sba, count(*) filter (where sources = ['sba']) sba_only, count(*) filter (where age_source = 'sba_loan') dated_by_sba, count(*) filter (where naics_source = 'sba') industry_from_sba from 'include/data/marts/businesses.parquet'\"))"
```

## Anti-goals

- No fuzzy matching beyond the product spec's tiers.
- No use of `BusinessAge` buckets to push a date further back. `sba_first_business_age` is carried as a column only.
- No filtering by program, loan status or fiscal year. All six files, every row.
- No lookup address from SBA. Its addresses date from the loan, often decades ago. `names` gains the borrower names.
- No deletion of raw files when SBA republishes. A new release gets a new `asof` suffix, and the stage reads only the discovered list.

## Files and interfaces

- **`include/pipeline/national/sba.py`**
  - `PAGE = "https://data.sba.gov/dataset/7a-504-foia"`.
  - `LINK` matches `https://data\.sba\.gov/sites/default/files/uploaded_resources/FOIA_(7a|504)_FY\d{4}_(?:FY\d{4}|Present)_asof_\d+\.csv`.
  - `parse_links(html) -> list[str]` returns the sorted unique matches. It raises when there are fewer than 6. It also raises when one series, the name without its `_asof_<n>` suffix, appears in two releases.
  - `discover(data) -> list[str]` GETs `PAGE` and calls `parse_links`. It deletes nothing.
  - `download(url, data) -> bool` calls `download_if_changed(url, data / "raw/sba" / <file name>)`.
  - `stage(urls, data, min_rows=<calibrated>) -> int` reads exactly the listed files with `read_csv(header=true, all_varchar=true, union_by_name=true)`. The 7(a) and 504 headers differ; both are in `docs/data-sources.md`. It writes one row per loan with these columns:
    - `program`, trimmed: the 7(a) files say `' 7A'`
    - `borrower_name`, `norm_name`, `dba_norm_name`
    - `address`, `city` (uppercased), `state`, `zip5`
    - `approval_date` (ISO, strict) and `approval_fy`
    - `gross_approval` (DECIMAL)
    - `naics`
    - `business_type`, `business_age`
    - `loan_status`, `paid_in_full_date`, `charge_off_date`
    - `jobs_supported`
    - `franchise_name`
    - `lender_name`, as `coalesce(BankName, CDC_Name)`
    - `source_file`

    Rows without `zip5`, `norm_name` or `state` are dropped and counted, and the stage fails at 1,000 or more; the 1990s files had 6 such rows. The stage asserts its floor and a sentinel: COPYTRON, INC., ZIP 21771, approved 1990-10-01. If DuckDB rejects the encoding, use the narrowest fix and record why, never `ignore_errors`.
- **`sql/businesses.sql`**
  - An `sba` CTE groups `sba_loans` by `(norm_name, zip5)` into borrower records. Each record carries:
    - `state`, `city` and `street_no` from its latest loan
    - its counts, totals and first and last dates
    - `sba_first_business_age`, from the earliest loan with a deterministic tiebreak
    - `sba_programs`
    - `sba_charged_off` and its latest `charge_off_date`
    - `naics` from its latest loan
  - These records enter step 3 next to the PPP keys, with the same tiers, and step 4's leftover grouping. Step 4 now meets more than one source: a group holds at most one record per source, and a key shared by two SBA records cannot happen because the key is the grouping.
  - `sources` gains `sba`. Industry, years, open status and `names` gain SBA as in the goal. A charge-off counts as a closure signal only when it is the business's newest signal.
- **`qc`:** conservation counts SBA borrower keys too. It also checks at least a calibrated floor of businesses with `sba` in `sources`, about 70% of the first run.
- **DAG:** `sba_discover`, then `sba_download.expand` with `max_active_tis_per_dag=3`, then `sba_stage(urls)`. Add it to the stages `build` waits on.
- **Tests:**
  - `tests/fixtures/national/sba/` holds a trimmed page with the six real links, a 7(a) CSV and a 504 CSV with the real headers. Rows include COPYTRON, INC. and a borrower without a ZIP.
  - `tests/unit/national/test_sba.py` checks that:
    - `parse_links` returns six links
    - `parse_links` raises on two releases of one series
    - `stage` types the rows and drops the ZIP-less one
  - The businesses fixtures gain:
    - a PPP-only business in a no-registry state that also had a 1990 SBA loan under the same key: one business, `sources = ['ppp', 'sba']`, `age_source = 'sba_loan'`
    - an SBA-only borrower charged off in 2009: `likely_closed`
    - an SBA borrower that joins an IL registry business in tier 1

## End-to-end verification

1. Run `scripts/smoke.sh 7200` and paste its output. The first run downloads about 1.0 GB.
2. Paste the DuckDB query above, and the same counts grouped by `state` for the top 10 states.
3. Spot-check two businesses dated by `sba_loan` against their rows in the raw CSV: same name, ZIP and approval date.
4. Every row of spec 06's file that gained nothing from SBA is unchanged. Compare with a copy saved before the run, and paste the counts of changed and unchanged rows.
5. A second run logs `unchanged` for all six files, and the business file's `sha256sum` is identical.
6. `mise run check` passes.
