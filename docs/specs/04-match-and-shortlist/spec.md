# 04-match-and-shortlist

Joins the three staged sources into a daily shortlist of long-established Texas businesses, with quality gates.

Bound by `docs/specs/00-product/spec.md` (decisions 7 to 12) and specs 01 to 03. After this spec the DAG runs end to end every day.

## Goal

A `build` task matches each PPP business to its Texas registration in four confidence tiers. It derives the EIN, joins the Form 5500 sponsor row, and computes years in business from the oldest evidence. It writes `marts/matches.parquet` and a dated shortlist partition. A `qc` task fails the DAG when the match rate, uniqueness or age bounds are off. An `export` task writes two CSVs. `shortlist_latest.csv` holds the whole shortlist, sorted by evidence. `shortlist_new_since_previous.csv` holds the rows that were not in the previous partition, and is the file the owner reads each morning.

## What the user can do afterwards

```
scripts/smoke.sh 3600
head -5 include/data/marts/shortlist_latest.csv
wc -l include/data/marts/shortlist_latest.csv include/data/marts/shortlist_new_since_previous.csv
uv run python -c "import duckdb; print(duckdb.sql(\"select match_tier, count(*) from 'include/data/marts/matches.parquet' group by 1 order by 1\"))"
```

Editing `TARGET_NAICS` or `MIN_YEARS` in `include/pipeline/shortlist.py` and running again changes the shortlist without touching SQL.

## Anti-goals

- No scoring model. The sort is `years_in_business desc, ever_defined_benefit desc, jobs_reported desc, business_name`.
- No fuzzy matching across ZIP codes. Tier 3 is blocked on ZIP5 and street number on purpose. Relaxing it is a later decision, made with the tier counts from this spec.
- No override file, no exclusion list and no outreach status.
- No NAICS descriptions in the output. The allowlist in code has a comment for each code.

## Files and interfaces

- `include/pipeline/shortlist.py`
  - `MIN_YEARS = 30`.
  - `TARGET_NAICS` lists 6-digit codes and 3-digit prefixes, each with a one-line comment:
    - Prefix `238`, all specialty trade contractors. This covers plumbing and HVAC (238220), electrical (238210), roofing (238160) and concrete (238110).
    - `561710` pest control, `561720` janitorial, `561730` landscaping, `561740` carpet cleaning, `561790` other building services.
    - `811111` general auto repair, `811121` auto body, `811192` car washes.
    - `811310` commercial machinery repair, `811411` home and garden equipment repair, `811412` appliance repair.
    - `812310` coin laundries, `812320` dry cleaning.
    - `484110`, `484121` and `484122` trucking, `484210` moving.
    - `332710` machine shops.
  - `build(data: Path = DATA, run_date: date | None = None) -> dict[str, object]`. `run_date` defaults to the current UTC date.
    - It runs `include/pipeline/sql/shortlist.sql` with the stage paths and `run_date` bound as parameters, never formatted into the string. `MIN_YEARS` and `TARGET_NAICS` are set with `SET VARIABLE` and read with `getvariable()` (verified in DuckDB 1.5.6, including list prefix matching).
    - It writes `marts/matches.parquet` and `marts/shortlist/run_date=YYYY-MM-DD/shortlist.parquet` through `copy_to_parquet`.
    - It returns `run_date` as ISO text plus counts: PPP businesses, matched, per tier, and shortlisted. The DAG passes `run_date` to `qc` and `export` through XCom, so a run that crosses midnight stays consistent.
  - `qc(run_date: str, data: Path = DATA, min_match_share: float = 0.30, min_rows: int = 100) -> None` checks the files just written:
    - The matched share of PPP businesses is at least `min_match_share`. The denominator excludes sole proprietorships, self-employed individuals and independent contractors.
    - The shortlist has at least `min_rows` rows.
    - `taxpayer_number` is unique in the shortlist.
    - Every shortlist row has `years_in_business >= MIN_YEARS` and a non-null `age_source`.
    - No shortlist row is `nonprofit` or `charged_off`.

    It logs the tier distribution and the matched share.
  - `export(run_date: str, data: Path = DATA) -> dict[str, int]` writes two files through `.part` files and returns both row counts.
    - `marts/shortlist_latest.csv` is the shortlist in the sort order above.
    - `marts/shortlist_new_since_previous.csv` is an anti-join on `taxpayer_number` against the newest partition older than `run_date`. When no older partition exists, every row counts as new.
- `include/pipeline/sql/shortlist.sql` defines these CTEs, in order:
  - `ppp_biz` groups `ppp_tx` by `(norm_name, zip5)` and computes:
    - `business_name`, the longest `borrower_name`
    - `dba_norm_name`, any non-null value
    - `address`, `city` and `county`
    - `naics`, the most common value
    - `business_type` and `business_age_description`
    - `nonprofit`, as `bool_or`
    - `charged_off`, as `bool_or(loan_status = 'Charged Off')`
    - `jobs_reported`, the maximum
    - `ppp_loan_count` and `ppp_total_approved`, the sum of `current_approval_amount`
    - `ppp_first_loan_date`, the earliest date
    - `street_no`, as `nullif(regexp_extract(address, '^\s*(\d+)', 1), '')`. The `nullif` matters. A PO box yields an empty string (verified), and an empty string would match every PO box in the ZIP.
  - `fr` is `tx_franchise` with `street_no` derived the same way. It is not filtered here.
  - `outlets` is `tx_sales_outlets` with `street_no`.
  - The four tiers:
    - `t1` joins `fr` on `norm_name` and `zip5`.
    - `t2` joins `fr` on `norm_name` and `city`.
    - `t3` joins `fr` on `zip5` and `street_no` where `jaro_winkler_similarity(ppp.norm_name, fr.norm_name) >= 0.92`.
    - `t4` joins `outlets` on `outlet_zip5 = zip5`, where `norm_outlet_name` equals `norm_name` or `dba_norm_name`. It then left-joins `fr` on `taxpayer_number`. When there is no `fr` row, it keeps the outlet's taxpayer number and org type with a NULL charter date. This is the sole-proprietor path.
  - Each tier keeps only the PPP businesses with exactly one distinct candidate, using `qualify count(distinct taxpayer_number) over (partition by norm_name, zip5) = 1`. DuckDB supports this (verified).
  - `best` is the `union all` of the tiers, keeping the lowest tier for each PPP business. `match_similarity` is 1.0 for tiers 1, 2 and 4, and the Jaro-Winkler value for tier 3.
  - `age` is computed per `taxpayer_number`:
    - `charter_date`
    - `first_sales_date`, the earliest across that taxpayer's outlets
    - `plan_eff_date`, `dol.earliest_plan_eff_date` joined on `ein`
    - `oldest`, as `least(charter_date, first_sales_date, plan_eff_date)`. DuckDB's `least` skips NULLs (verified).
    - `years_in_business`, as `date_sub('year', oldest, run_date)`, which counts complete years. Do not use `date_diff`, which counts year boundaries: it gives 36 instead of 35 from 1990-12-31 to 2026-01-01 (verified).
    - `age_source`: `'charter'`, `'first_sales'` or `'plan'`, the first of those whose date equals `oldest`.
  - `matches` is `best` plus `age`, left-joined to `dol_5500_tx` on `ein`. `naics_final` is `coalesce(ppp.naics, fr.naics, outlet_naics, dol.business_code)`. `dba_name` is the matched outlet name for tier 4, and otherwise `dba_norm_name`.
  - `shortlist` filters `matches` to rows where:
    - `naics_final` is in `TARGET_NAICS`, by exact code or by prefix
    - `years_in_business >= MIN_YEARS`
    - neither `nonprofit` nor `charged_off` is set
    - `right_to_transact = 'A'`, or the match has no franchise row (the tier-4 sole-proprietor path)

    It then keeps one row per `taxpayer_number`, the one with the largest `ppp_total_approved`.
  - Output columns, in this order: `business_name`, `dba_name`, `address`, `city`, `zip5`, `county`, `naics`, `jobs_reported`, `business_type`, `ppp_loan_count`, `ppp_total_approved`, `ppp_first_loan_date`, `match_tier`, `match_similarity`, `taxpayer_number`, `ein`, `sos_file_number`, `org_type`, `charter_date`, `first_sales_date`, `plan_eff_date`, `years_in_business`, `age_source`, `plan_signer_name`, `plan_signer_source`, `plan_phone`, `plan_name`, `pension_codes`, `ever_defined_benefit`, `active_participants`, `plan_last_filed`, `run_date`.
- `dags/tx_retiring_owners.py`: `[ppp_stage, tx_stage, dol_stage] >> build >> qc >> export`. `build` gets an `execution_timeout` of 30 minutes.
- `tests/fixtures/shortlist/make_fixtures.py` writes tiny versions of the four stage Parquet files into `tmp_path` from inline rows. The rows cover these cases:
  - a tier-1 match that is 40 years old, with a defined-benefit plan and a sponsor signer
  - a tier-2 match in a different ZIP
  - a tier-3 near-name match on the same street number
  - two PPP businesses at PO boxes in one ZIP, which must not match each other's taxpayers
  - a tier-4 DBA match to a sole proprietor with a 1985 first-sales date and no charter
  - a name that matches two taxpayers in one city, which must stay unmatched
  - a business with no match
  - a nonprofit
  - a charged-off loan
  - a 10-year-old business
  - two PPP name variants that resolve to the same taxpayer
- `tests/unit/test_shortlist.py`:
  - `build` with `run_date=2026-10-17` returns exact tier counts. The shortlist contains exactly the expected taxpayer numbers, with the expected `years_in_business`, `age_source`, `match_tier` and `plan_signer_name`.
  - `export` on two consecutive run dates, where the second adds one row, writes a one-row `shortlist_new_since_previous.csv`.
  - `qc` raises on a fixture where one taxpayer number appears twice.

## End-to-end verification

1. With all three stages present, run `scripts/smoke.sh 3600` and paste its output. `build`, `qc` and `export` go green.
2. Paste into the commit body:
   - the `build` counts line
   - the `head -5` of `shortlist_latest.csv`
   - the `wc -l` of both CSVs
   - the matched share from the `qc` log

   Record the calibrated thresholds in `implementation-notes.md`.
3. Check five shortlist rows by hand against the Comptroller's taxable entity search, https://comptroller.texas.gov/taxes/franchise/account-status/search, and note whether the charter dates agree.
4. Run `scripts/smoke.sh` again on the same day. Both CSVs keep their row counts, because the run overwrites today's partition and compares only against older ones.
5. `mise run check` passes.
