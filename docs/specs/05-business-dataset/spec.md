# 05-business-dataset

Turns the Texas pipeline into a strict ETL that ends in one file of every Texas business from every Texas source, with records of the same business merged. Each row has industry, years in business, Google Maps lookup fields and an open status, and nothing is filtered.

Bound by `docs/specs/00-product/spec.md`: decisions 4, 7 to 12 and 16 to 20, and the anti-goals "No business filtering in the ETL" and "No guessing when merging". It builds on specs 01 to 04 and reuses their stages, name macros and tier SQL. It is still Texas only; spec 06 goes national and makes the code generic.

## Goal

The DAG `tx_retiring_owners` stops producing a shortlist. Its `build` task writes `include/data/marts/businesses.parquet` instead.

**Rows.** The file has one row per Texas business seen in any of the four Texas inputs, merged with product decision 9's five steps:

| Source | Staged rows | Role |
| --- | --- | --- |
| Franchise registry | 3,486,185 taxpayers | Registry anchors |
| Sales-tax outlets | 890,307 outlets of 705,284 taxpayers | Trade names; taxpayers with no franchise row become their own anchors |
| Form 5500 sponsors | 66,202 | Join an anchor by EIN or name, or stand alone |
| PPP keys | 759,013 | Records that join a business or stand alone |

Expect about 4 million rows: most of them registry-only, and every one kept.

**Columns.** Every row has the product spec's four column groups:

- industry (decision 18)
- years in business (decision 11, with the PPP loan date as the weakest evidence)
- lookup fields (decision 20)
- open status (decision 19)

It also carries every detail the four stages give.

**`qc`** checks data quality only, including that every staged record landed in exactly one business.

**Raw layer.** It becomes append-only:

- `ppp_discover` stops deleting files the SBA page no longer lists.
- `ppp_stage` reads exactly the discovered files.

**Removed.** The shortlist, its CSV exports, the dated partitions, `MIN_YEARS` and `EXCLUDED_NAICS`. The old shortlist becomes a consumer query over the new file.

## What the user can do afterwards

```
scripts/smoke.sh 3600
uv run python -c "import duckdb; print(duckdb.sql(\"select array_to_string(sources, '+') seen_in, count(*) businesses, count(naics) with_industry, count(years_in_business) with_years, count(lookup_address) with_address, count(*) filter (where open_status = 'likely_open') likely_open from 'include/data/marts/businesses.parquet' group by 1 order by 2 desc\"))"
```

The phase 1 shortlist, as a consumer would now write it:

```
uv run python -c "import duckdb; print(duckdb.sql(\"select count(*) from 'include/data/marts/businesses.parquet' where list_contains(sources, 'ppp') and years_in_business >= 30 and not nonprofit and not charged_off and (active or (not list_contains(sources, 'tx_franchise') and entity_type in ('S', 'IS', 'PB', 'PI'))) and not regexp_matches(coalesce(naics, ''), '^(813|814|92)')\"))"
```

It returns about 25,842, the count of the archived 2026-10-17 shortlist.

## Anti-goals

- No other states, no new sources and no new name rules. Spec 06 goes national.
- No filter of any kind in `build`. Registry-only, dissolved, forfeited, young, nonprofit and charged-off businesses are all rows.
- No CSV export, no dated partitions, no "new since previous" and no `_exported` markers. History is consumer logic.
- No code layout change. `national/` and `states/` come in spec 06.
- No change to the four stage files beyond the one PPP column below.
- The pipeline never deletes a raw file. The old marts files are moved to an archive by hand, once.

## Files and interfaces

- **`include/pipeline/ppp.py`**
  - `discover(data: Path = DATA) -> list[str]` returns the URLs from `parse_links`. It no longer deletes anything. Remove the stale-file loop and its log field.
  - `stage_tx(urls: list[str], data: Path = DATA, min_rows: int = 650_000) -> int` reads exactly `[data / "raw/ppp" / <file name of url> for url in urls]`, passed to `read_csv` as a list. It raises `FileNotFoundError` naming a missing file.
  - It gains `loan_status_date` (`LoanStatusDate`, strict `MM/DD/YYYY`), which dates a charge-off for open status.
  - Everything else is unchanged.
- **`include/pipeline/businesses.py`** replaces `shortlist.py` (`git mv`, then edit):
  - `build(data: Path = DATA, run_date: date | None = None) -> dict[str, object]` sets the stage paths, `run_date` and `naics_titles` as today. It also sets `franchise_as_of` and `outlets_as_of`: the `Last-Modified` dates in `raw/tx/*.meta.json`, which the publisher's data date for open status needs. A sidecar without one raises. It runs `sql/businesses.sql`, writes `marts/businesses.parquet` with `copy_to_parquet`, and returns `run_date` and counts:
    - businesses by `sources` combination
    - sponsors linked by EIN, by name, by the hop, or standing alone
    - PPP keys per tier
    - the coverage of industry, years, lookup address and each open status

    It logs them in one line.
  - `qc(data: Path = DATA, min_rows: int = 2_800_000, min_match_share: float = 0.30) -> None` asserts on the file just written:
    - at least `min_rows` rows. Calibrate to about 70% of the first run and record it.
    - `business_id` is unique
    - **Conservation:**
      - every franchise taxpayer, outlet taxpayer, sponsor EIN and PPP key in the stages appears in exactly one business
      - `sum(ppp_key_count)` equals the distinct PPP keys staged
      - `sum(ppp_loan_count)` equals the PPP rows staged
    - the matched share of PPP keys, joined to a registry or sponsor business in any tier, is at least `min_match_share` among keys whose `business_type` is not in `INDIVIDUALS`, as today
    - `age_source` is NULL exactly when `oldest_evidence_date` is NULL, and `years_in_business >= 0`
    - `open_status` is one of the three values, and `open_evidence` is set whenever it is not `unknown`

    Every message names the file and the numbers.
  - Remove `MIN_YEARS`, `EXCLUDED_NAICS`, `ORDER`, `partition` and `export`. Keep `INDIVIDUALS`.
- **`include/pipeline/sql/businesses.sql`** replaces `shortlist.sql` (`git mv`, then edit). It keeps `ppp_biz`, `fr`, `outlets`, `dol`, the NAICS tables and the tier joins as building blocks, and runs decision 9's steps:
  1. **Anchors.**
     - Every franchise row is a registry business: `business_id` is `EIN-<ein>`, else `TX-<taxpayer_number>`.
     - Outlets attach to it by taxpayer number.
     - An outlet taxpayer with no franchise row becomes a registry business of its own, with the same id rule and the outlet's org type.
  2. **Sponsors** (`dol`, one per EIN), in this order:
     - EIN equal to an anchor's EIN: `plan_link = 'ein'`.
     - Else tiers 1 to 3 against franchise rows **without** an EIN, using the sponsor's `norm_name`, `zip5`, upper-cased city and street number: `plan_link = 'name'`.
     - Else a business of its own, `EIN-<ein>`.
  3. **PPP keys.**
     - Tiers 1 to 4 as today, giving an anchor.
     - Else tiers 5 to 7 against all sponsors (5: `norm_name` and `zip5`; 6: `norm_name` and city; 7: Jaro-Winkler ≥ 0.92 within `zip5` and street number), giving the sponsor's business.
     - Every tier keeps the exactly-one rule. Tiers 5 to 7 are computed for every key.
  4. **Leftover PPP keys** become `KEY-<zip5>-<norm_name>` businesses.
  5. **Hop.** A sponsor that stood alone after step 2 merges into registry business R when every PPP key matching it in tiers 5 to 7 is in R: `plan_link = 'hop'`.

  Then aggregate per `business_id` (decision 16), and compute:
  - **`sources`**, the sorted distinct list of `tx_franchise`, `tx_sales_outlets`, `dol_5500` and `ppp`.
  - **`names`**: every distinct name (franchise, outlet, sponsor, sponsor DBA, PPP).
  - **PPP aggregates as in spec 04's `ppp_biz`, summed across keys:** `ppp_names`, `ppp_key_count`, `ppp_loan_count`, `ppp_total_approved` (`DECIMAL(18, 2)`), `ppp_first_loan_date`, `ppp_last_loan_date`, `jobs_reported` (maximum), `nonprofit` and `charged_off` (`bool_or`), `business_type` and `business_age_description` from the key with the largest total.
  - **`match_tier`**, the best tier of its PPP keys, and `match_similarity` from that key.
  - **Industry** (decision 18, Texas sources): PPP, then the Form 5500 business code, then the outlet NAICS mode, then the franchise NAICS. Add `naics_source` and the Census titles as today.
  - **Years** (decision 11): `least()` over the franchise charter date as `formed_date`, the earliest outlet first-sales date, the earliest plan effective date and `ppp_first_loan_date`, each through `nullif(…, date '1900-01-01')`. Then `oldest_evidence_date`, `age_source` (`formed`, `first_sales`, `plan`, `ppp_loan`) and `years_in_business`.
  - **Lookup** (decision 20, Texas sources):
    - `lookup_name` is the outlet name (the tier-4 outlet, else the taxpayer's lowest outlet number), else the PPP DBA, else the sponsor DBA, else the PPP name, the franchise name, then the sponsor name.
    - The address is the outlet's address, else the PPP address, else the franchise address (`mailing`), else the sponsor's mailing address. Add `lookup_address_source`.
    - `phone` is the sponsor phone.
  - **Open status** (decision 19, Texas signals):
    - Activity signals: franchise right to transact `A`, dated `franchise_as_of`; a listed outlet, dated `outlets_as_of`; a Form 5500 received; the latest PPP approval.
    - Closure signals: a franchise row not `A`, dated `sos_status_date`, else `franchise_as_of`; a charged-off PPP loan, dated `loan_status_date`.
    - The newest signal decides, with a 24-month window to `run_date`.
    - `open_evidence` is its description and date, such as `tx_franchise right to transact A 2026-10-10`.

  The final select has no `where` and ends in `order by business_id`.

  Output columns, in this order:

  | Group | Columns |
  | --- | --- |
  | Identity | `business_id`, `state`, `sources`, `registry_id`, `ein`, `names` |
  | Lookup | `lookup_name`, `lookup_address`, `lookup_city`, `lookup_state`, `lookup_zip5`, `lookup_address_source`, `phone` |
  | Industry | `naics`, `naics_source`, `sector`, `industry_group`, `naics_title` |
  | Age | `years_in_business`, `oldest_evidence_date`, `age_source`, `formed_date`, `first_sales_date`, `plan_eff_date`, `ppp_first_loan_date` |
  | Open status | `open_status`, `open_evidence`, `registry_status`, `active` |
  | PPP | `ppp_names`, `ppp_key_count`, `ppp_loan_count`, `ppp_total_approved`, `ppp_last_loan_date`, `jobs_reported`, `business_type`, `business_age_description`, `nonprofit`, `charged_off` |
  | Match | `match_tier`, `match_similarity`, `plan_link` |
  | Registry | `entity_type`, `tx_sos_file_number`, `tx_right_to_transact`, `tx_sos_status_date` |
  | Outlets | `outlet_names`, `outlet_count` |
  | Plan | `plan_signer_name`, `plan_signer_source`, `plan_name`, `pension_codes`, `ever_defined_benefit`, `active_participants`, `plan_last_filed` |
  | Run | `run_date` |

  These are the national names spec 06 keeps.
- **`dags/tx_retiring_owners.py`**
  - `urls = ppp_discover()`, then `ppp_download.expand(url=urls) >> ppp_stage(urls)`.
  - `[ppp_staged, tx_staged, dol_staged] >> build() >> qc()`.
  - The `export` task goes.
- **`CLAUDE.md`**: the first line says the pipeline builds a daily dataset of Texas businesses with industry, years in business and open status. No "shortlist".
- **`tests/fixtures/businesses/make_fixtures.py`** replaces `tests/fixtures/shortlist/make_fixtures.py` (`git mv`). It keeps every existing case and adds these:
  - a franchise entity with no other record, right to transact `A`: `likely_open`
  - a forfeited entity (`N`) with no other record: `likely_closed`, dated by its status date
  - an outlet-only sole proprietor with no PPP: its own business, `likely_open`, dated by first sales, with the outlet address as lookup
  - a sponsor-only business: `EIN-…`, age from the plan, industry from the business code, phone set
  - a sponsor linked by EIN; a sponsor linked by name to a franchise row without an EIN; and a sponsor whose name matches a franchise row carrying a **different** EIN, which stays its own business
  - a PPP key matched only through tier 5 to a sponsor
  - a hop case
  - a PPP-only business: `KEY-…`, `age_source = 'ppp_loan'`, `unknown`
  - a charged-off PPP-only business: `likely_closed`
  - an outlet DBA used as `lookup_name` over the legal name
- **`tests/unit/test_businesses.py`** replaces `test_shortlist.py`. It asserts:
  - `build`'s exact counts
  - every case above, column by column
  - conservation
  - that the consumer query returns exactly the nine taxpayer numbers spec 04's test expected
  - that `qc` passes with `min_rows=1`, and raises on a duplicated `business_id`, on a removed PPP key and on a removed franchise taxpayer
- **`tests/unit/test_ppp.py`:**
  - `stage_tx` ignores an extra `public_up_to_150k_99_240930.csv` in `raw/ppp/`, and raises on a missing listed file
  - `loan_status_date` is typed

## Before the first run (by hand, once)

1. Copy `include/data/marts/matches.parquet` and `include/data/marts/shortlist/run_date=2026-10-17/shortlist.parquet` to the session scratchpad as the regression baseline.
2. Move, untouched, `matches.parquet`, the `shortlist/` folder, `shortlist_latest.csv` and `shortlist_new_since_previous.csv` into `include/data/marts/archive/2026-10-17-texas/`. Record the move in the notes.

## End-to-end verification

1. Run `scripts/smoke.sh 3600` and paste its output. Every task is green and there is no `export` task. Record `build`'s duration and peak memory from its log.
2. Paste both DuckDB commands above.
3. Regression against the baseline:
   - Every taxpayer in the archived shortlist is the `registry_id` of exactly one business, with the same `formed_date` and `years_in_business`.
   - The consumer query's count matches 25,842, or every difference is listed with its cause.
4. **Hand-check merges.** Take 20 random businesses that merged at least two sources, and 20 random `KEY-` businesses. For each, say whether the merge, or the lack of one, is right. Record the counts in the notes as the first measure of merge quality.
5. `ls include/data/raw/ppp/` still shows 13 CSVs and 13 sidecars. The `ppp_discover` log line has no `removed=` field.
6. Run `scripts/smoke.sh 3600` again. Every download logs `unchanged`, and `sha256sum include/data/marts/businesses.parquet` is identical.
7. `mise run check` passes.
