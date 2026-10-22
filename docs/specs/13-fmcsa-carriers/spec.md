# 13-fmcsa-carriers

Stages the FMCSA Company Census of every US motor carrier. Each carrier joins the business it belongs to, or becomes a business of its own, bringing an add date, a physical address, a phone, company officers, fleet size and an active or inactive status.

Bound by `docs/specs/00-product/spec.md`: decisions 4 to 9, 11, 12 and 16 to 20, and `docs/data-sources.md` section 9. It follows `national/sba.py` and `national/sam.py`.

## Goal

The DAG gains an FMCSA chain. It downloads the Company Census export from data.transportation.gov (`az4n-8mr2`) when its `ETag` changes, and stages every carrier into `stage/fmcsa_carriers.parquet`. On 2026-10-16 the census had 4,518,028 carriers:

| Status | Carriers |
| --- | --- |
| `A` active | 2,241,706 |
| `I` inactive | 2,274,987 |
| `P` pending | 1,335 |

Planning counted 87,010 active carriers added before 1997. The census is free and anonymous, and refreshed daily.

**In the transform**, each carrier is a record in product decision 9:

- Step 3: it joins through its legal name, or failing that its DBA name, with the same tiers as other records.
- Step 4: it joins the leftover group with its `(norm_name, zip5)`.
- Two carriers sharing a key stay separate rows, `DOT-<number>`.

**What it adds, by column group:**

- **Industry:** `484` (truck transportation) when `CLASSDEF` includes "FOR HIRE". This is last in decision 18's order, because private carriers are businesses of every industry that run their own trucks.
- **Years:** `ADD_DATE`, the `fmcsa_added` candidate. It is a lower bound: the date the carrier entered the USDOT system.
- **Lookup:** the physical address, first in decision 20's order; the DBA as a trading name; the phone, after Form 5500's.
- **Open status:**
  - status `A`: an activity signal dated by the last MCS-150 update
  - status `I`: a closure signal dated the same way, else `as_of`
- **Columns:** `usdot_number`, `fmcsa_status`, `fmcsa_add_date`, `fmcsa_officers` (from `COMPANY_OFFICER_1` and `_2`), `fmcsa_business_org`, `fmcsa_classdef`, `fmcsa_power_units`, `fmcsa_drivers`, `fmcsa_email`.

## What the user can do afterwards

```
scripts/smoke.sh 7200
uv run python -c "import duckdb; print(duckdb.sql(\"select count(*) filter (where list_contains(sources, 'fmcsa')) with_carrier, count(*) filter (where sources = ['fmcsa']) carrier_only, count(fmcsa_officers) with_officers, count(*) filter (where age_source = 'fmcsa_added') dated_by_fmcsa, count(*) filter (where lookup_address_source = 'fmcsa') address_from_fmcsa from 'include/data/marts/businesses.parquet'\"))"
```

## Anti-goals

- No inspection, crash or safety-rating datasets, and no SMS scores. Census only.
- No filter on status, carrier type or country. Inactive and foreign carriers are staged. Only US carriers enter the merge, because a business needs a US state.
- No use of the mailing address for matching or lookup. The physical address is where the business is.

## Files and interfaces

- **`include/pipeline/national/fmcsa.py`**
  - `URL = "https://data.transportation.gov/api/views/az4n-8mr2/rows.csv?accessType=DOWNLOAD"`. HEAD returns `ETag` and `Last-Modified`, with `Content-Length: 0` because the export is streamed (verified).
  - `HEADER` is the exact first line as served, in `docs/data-sources.md` section 9.
  - `download(data) -> bool` calls `download_if_changed(URL, data / "raw/fmcsa/fmcsa_census.csv")`.
  - `stage(data, min_rows=<calibrated>) -> int`
    1. Check the header, then read every row with `all_varchar`.
    2. Stage these columns:
       - `dot_number` (BIGINT)
       - `legal_name`, `norm_name`, `dba_name`, `norm_dba_name`
       - `phy_street`, `phy_city` (uppercased), `phy_state`, `zip5`, `phy_country`
       - `status_code`
       - `add_date` and `mcs150_date`, from `YYYYMMDD`, strict
       - `company_officer_1` and `company_officer_2`, trimmed
       - `business_org_desc`, `carrier_operation`, `classdef`
       - `power_units`, `truck_units`, `total_drivers`
       - `phone`, `email_address`
       - `as_of`, from the sidecar's `Last-Modified`
    3. Assert the floor and that `dot_number` is unique.
    4. Assert a sentinel: USDOT `1`, FEDERAL MOTOR CARRIER SAFETY ADMINISTRATION, added 1974-06-01. It is FMCSA's own record and the first row of the export (verified). It is in DC, so it also exercises the DC path.
- **`sql/businesses.sql`**
  - `fmcsa` records are US carriers. They enter steps 3 and 4 next to PPP, SBA and SAM records. In step 4, a key held by two or more carriers leaves them out of the group, and each becomes `DOT-<number>`.
  - `sources` gains `fmcsa`. Industry, years, lookup, `phone`, open status and `names` gain FMCSA as in the goal.
  - When two carriers join one business, take the earliest add date and the newest status signal, and list both officers.
- **`qc`:** conservation counts every US carrier. It also checks at least a calibrated floor of businesses with `fmcsa` in `sources`.
- **DAG:** `fmcsa_download`, then `fmcsa_stage`. Add it to the stages `build` waits on.
- **Tests:**
  - `tests/fixtures/national/fmcsa/fmcsa_census.csv` has the real header, the USDOT 1 row and four real carriers: an active owner-operator with an officer, an inactive carrier, a DBA-named carrier and a non-US carrier.
  - `tests/unit/national/test_fmcsa.py` asserts the staged rows and checks that a renamed header raises.
  - The businesses fixtures gain:
    - a trucking company joined to a PPP key through its DBA: industry from PPP, age from the add date, lookup address and phone from FMCSA
    - a carrier-only for-hire owner-operator: `KEY-…`, industry `484`, `likely_open`
    - an inactive carrier whose newest signal is its status: `likely_closed`

## End-to-end verification

1. Run `scripts/smoke.sh 7200` and paste its output. Record the download size and time; this is the largest Socrata export after the registries.
2. Paste the query above, and the count of businesses with NAICS starting `484` that gained a carrier.
3. Spot-check two matched carriers against `https://data.transportation.gov/resource/az4n-8mr2.json?dot_number=<n>` and paste both sides.
4. Paste the national open-status counts before and after this spec, so the effect of carrier signals is visible.
5. A second run logs `unchanged` and the file's `sha256sum` is identical.
6. `mise run check` passes.
