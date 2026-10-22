# 08-registries-ny-pa-co

Adds the New York, Pennsylvania and Colorado business registries as state modules, so businesses in those states get formation dates, statuses and officers.

Bound by `docs/specs/00-product/spec.md`: decisions 4 to 6, 9, 11 to 13 and 17. Also bound by `docs/data-sources.md` sections 10.2 (NY), 10.3 (PA) and 10.5 (CO). It uses spec 06's `states/` contract unchanged: three new modules and three lines in `STATES`.

## Goal

Three more registries go through the contract's default path: Socrata CSV export, `ETag` and `Last-Modified` change detection, and an exact header check. Each module stages all rows and maps them onto `REGISTRY_COLUMNS` plus extras prefixed with its state code.

- Every entity becomes a registry business (product decision 9, step 1), so these states gain millions of rows. Most are registry-only.
- PPP keys, SBA borrowers and plan sponsors in these states now join those businesses instead of standing alone, and gain formation dates, statuses and officers.
- Together the three states have 1,269,486 PPP loans.

| Module | Dataset | Rows (2026-10-17) | Sentinel |
| --- | --- | --- | --- |
| `states/new_york.py` | data.ny.gov `n9v6-gdp6`, "Active Corporations: Beginning 1800" | 4,299,620 entities, active only | `30059` INTERNATIONAL BUSINESS MACHINES CORPORATION, 1911-06-16 |
| `states/pennsylvania.py` | data.pa.gov `xvd7-5r2c` | 4,174,730 rows (one per officer), 2,376,226 filings, current only | `0000399042` D. G. Yuengling and Son, Incorporated, 1914-04-09 |
| `states/colorado.py` | data.colorado.gov `4ykn-tg5h`, "Business Entities in Colorado" | 3,124,011 entities, all statuses | `19871009071` THE MANITOU AND PIKE'S PEAK RAILWAY COMPANY, 1888-11-17 |

## What the user can do afterwards

```
scripts/smoke.sh 14400
uv run python -c "import duckdb; print(duckdb.sql(\"select state, count(*) businesses, count(*) filter (where len(sources) = 1 and registry_id is not null) registry_only, count(*) filter (where list_contains(sources, 'ppp') and registry_id is not null) ppp_with_registry, count(formed_date) with_formed, count(registry_officers) with_officers, count(*) filter (where open_status = 'likely_open') likely_open from 'include/data/marts/businesses.parquet' where state in ('NY', 'PA', 'CO') group by 1\"))"
```

## Anti-goals

- No status filter at stage. Colorado keeps all 15 statuses. Every row also takes part in matching, because a business dissolved after its 2020 PPP loan is still the right match. A dissolved namesake can make a live one ambiguous, which loses a match but never makes a wrong one. If that pushes a state below its floor, record the numbers; do not change the transform.
- No use of New York's "All Filings" (`63wc-4exh`) or "Status History" (`3gg2-jgnp`) datasets. Each has 21M rows; they are a later spec if inactive New York entities are ever needed.
- No geocoding. The Pennsylvania `Georeferenced Latitude & Longitude` column is carried as an extra, unparsed.
- No change to `states/__init__.py`, the transform or the tiers. If a module needs something the contract lacks, stop and write it down; that would be a spec change.

## Files and interfaces

Each module has the same shape as `states/texas.py`: a docstring with the publisher, URL, licence and refresh, then `SOURCES` holding one registry `Source` with one `File`. The exact headers are in `docs/data-sources.md`. Columns get snake_case names in header order.

- **`states/new_york.py`**, `File("ny_corporations.csv", "https://data.ny.gov/api/views/n9v6-gdp6/rows.csv?accessType=DOWNLOAD", …)`.
  - The select maps:
    - `registry_id = dos_id`
    - `name = current_entity_name`
    - `formed_date = mdy(initial_dos_filing_date)`
    - `entity_type`
    - `status = NULL`, `status_date = NULL`
    - `active = NULL`. The list holds every entity not formally dissolved, and New York enforces no annual report, so being listed is no evidence of operating (product decision 19).
    - `naics = NULL`
    - `officers = ['CEO: ' || ceo_name]` when `ceo_name` is set, else NULL. CEO names fill 471,965 rows.
  - **Address:** the location fields when `location_zip` is set, with `address_kind = 'physical'` (350,078 rows). Otherwise the DOS process fields, with `address_kind = 'legal'` (4,218,127 rows have a process ZIP). `zip5` is the first five characters when they are digits, else NULL.
  - Extras: `ny_county`, `ny_jurisdiction`, `ny_dos_process_name`, `ny_registered_agent_name`, `ny_location_name`, `ny_ceo_address`.
  - `min_rows` is about 70% of the first run; `dropped=(0, 0)`; sentinel `("30059", date(1911, 6, 16))`.
- **`states/pennsylvania.py`**, `File("pa_corporations.csv", "https://data.pa.gov/api/views/xvd7-5r2c/rows.csv?accessType=DOWNLOAD", …)`.
  - **One row per officer.** The select groups by `filing_number`, which keeps its leading zeros, into one row per filing:
    - Name, address and type come from a deterministic pick, for example `min()` over `(address_line_1, city, zip)`. Record whether they ever differ within a filing.
    - `officers` is the sorted distinct list of `governor_principal_officer || ': ' || first || ' ' || last` from rows that have a name. The party types are President 813,679, Governor 808,915, Organizer 413,997, Treasurer, Secretary, Vice President, General Partner, Incorporator, Member, Owner and others; 960,148 rows have none.
  - **`formed_date`** is `mdy(creation_date)`. The placeholder `1753-01-01`, on 30,976 rows, becomes NULL. `1933-09-30` covers 968 filings, is not a spike, and is kept as a real date.
  - **`zip5`** is the leading five digits, or NULL for values such as `0    -0`.
  - `entity_type` comes from `type_of_business_registration`. `status` and `status_date` are NULL.
  - `active = NULL`. Current registrations are listed until Pennsylvania's new annual-report rule starts dissolving non-filers in 2027, so being listed is no evidence of operating.
  - `address_kind = 'legal'` by default. Hand-check 20 rows on the first run; if most are a place of business rather than a registered office, switch to `'physical'` and record the count.
  - Extras: `pa_county_name`, `pa_address_line_2`, `pa_geo`.
  - `dropped` is the raw rows minus the filings: 1,798,504 on 2026-10-17. Set the range to about ±20% of the first run.
  - Sentinel `("0000399042", date(1914, 4, 9))`.
  - The address may be the registered office rather than the place of business. Calibrate `min_match_share` on the first run and record it, with the measured share.
- **`states/colorado.py`**, `File("co_business_entities.csv", "https://data.colorado.gov/api/views/4ykn-tg5h/rows.csv?accessType=DOWNLOAD", …)`.
  - The select maps:
    - `registry_id = entityid`. Pre-1987 entities carry a `1987…` prefix.
    - `name = entityname`
    - the principal address, city and ZIP, with `address_kind = 'physical'`
    - `status = entitystatus`, `status_date = NULL` (there is no such column, so a closure is dated by `as_of`)
    - `active = entitystatus = 'Good Standing'`. A `Delinquent` entity, one that missed its periodic report, therefore counts as a closure signal. That is the publisher's own judgment, and the 24-month rule does the rest.
    - `entity_type = entitytype`
    - `formed_date = mdy(entityformdate)`
    - `officers = NULL`. The registered agent is not an officer.
  - Extras: `co_jurisdiction_of_formation`, `co_agent_name` (first and last, or the organization), `co_mailing_zip`.
  - Statuses on 2026-10-17:

    | Status | Rows |
    | --- | --- |
    | Delinquent | 1,151,596 |
    | Good Standing | 1,032,449 |
    | Voluntarily Dissolved | 600,854 |
    | Administratively Dissolved | 157,832 |
    | Withdrawn | 80,525 |
    | Noncompliant | 32,428 |
    | Revoked | 20,687 |
    | Judicially Dissolved | 15,926 |
    | Exists | 15,659 |
    | Merged | 10,164 |
    | Converted | 4,838 |
    | Registered Agent Resigned | 663 |
    | Effectiveness Prevented | 228 |
    | Dissolved (Term Expired) | 144 |
    | Consolidated | 18 |

    Record what `Exists` covers, and whether it should count as `active`.
  - `dropped=(0, 0)` unless the first run finds duplicate ids. Then dedupe deterministically and record it.
  - Sentinel `("19871009071", date(1888, 11, 17))`.
- **`states/__init__.py`:** `STATES` gains `new_york`, `pennsylvania` and `colorado`, in that order.
- **Tests:** `tests/fixtures/states/{new_york,pennsylvania,colorado}/` each hold a CSV with the exact real header, the sentinel row and three or four real rows copied from the export. Pennsylvania's fixture has one filing on several officer rows and one `1753-01-01` row. New York's has one row with a location ZIP and one without. Colorado's has a dissolved entity. `tests/unit/states/test_{new_york,pennsylvania,colorado}.py` assert the staged rows exactly, and assert that a renamed header raises.

## End-to-end verification

1. Run `scripts/smoke.sh 14400` and paste its output. The first run downloads the three exports, each 1 to 2 GB, through Socrata's streamed CSV. Record each one's size and duration in the notes. If a portal answers HTTP 429, follow the product spec's throttling note.
2. Paste the DuckDB query above. For each state, record the matched share of PPP keys among non-individual businesses, the tier mix, the `age_source` mix, the open-status mix and the calibrated `min_match_share`. Record `build`'s duration and peak memory, which grow with roughly 10 million more anchors.
3. Spot-check two old businesses per state (30 or more years, joined in tier 1 or 2) against the row API, and paste both sides:
   - New York: `https://data.ny.gov/resource/n9v6-gdp6.json?dos_id=<id>`
   - Pennsylvania: `https://data.pa.gov/resource/xvd7-5r2c.json?filing_number=<id>`
   - Colorado: `https://data.colorado.gov/resource/4ykn-tg5h.json?entityid=<id>`
4. Compare with spec 07's file, saved to the scratchpad before the run:
   - Outside NY, PA and CO, every row is unchanged.
   - Inside them, every former PPP, SBA or sponsor business either joined a registry business or is unchanged.
   - Paste the counts.
5. A second run logs `unchanged` for the three exports, and the file's `sha256sum` is identical.
6. `mise run check` passes.
