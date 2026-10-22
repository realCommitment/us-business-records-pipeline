# Product spec: Retiring Business Owners (all US states)

Written 2026-10-17 from the Substack post "Did AI Solve the Hardest Part of Buying a Business?" (Angus Sewell McCann, 2026-10-13), for Texas. Revised the same day for every US state, at the owner's direction:

- Follow a strict ETL. Scrape every source, store the files exactly as published, then transform.
- Pull all the businesses, not only PPP borrowers. The last step finds as many businesses as possible and merges the records that are the same business.
- The primary measures are **industry** and **years in business**.
- Secondary: enough detail to look the business up on Google Maps, and a flag for whether it is **likely open, likely closed, or unknown**.
- Do no business filtering. "30 years in business" was only an example. Every cut is business logic for a future consumer.

The owner delegated the plan instead of running the interview. Every decision below is therefore a default to veto. Phase 1b's open scope questions were settled the way YC partners advise: the smallest slice that gives the most businesses better data comes first. Facts about every source and the toolchain were verified on 2026-10-17 and are recorded in `docs/data-sources.md`.

## Goal

A local Airflow pipeline runs every day and rebuilds one file, `include/data/marts/businesses.parquet`. It holds **one row per business found in any source**, with records that describe the same business merged into one row. The sources are:

- SBA PPP loans
- ten free state business registries: TX, FL, NY, PA, VA, CO, IA, CT, OR and DC
- Texas sales-tax permits
- DOL Form 5500 pension filings
- SBA 7(a) and 504 loans
- SAM.gov federal contractor registrations
- the FMCSA motor-carrier census

Every row carries four groups of columns:

1. **Industry:** a NAICS code with the Census sector, group and title, plus which source gave it.
2. **Years in business:** complete years since the oldest dated record of the business, plus which record that was.
3. **Lookup details for Google Maps:** a trading name, a physical address and a phone where any source has them, plus every name seen.
4. **Open status:** `likely_open`, `likely_closed` or `unknown`, with the evidence for it.

Every other detail the sources give is carried too: officers, plan signers, loan amounts, employees reported and registry status. Detail varies by state and by source. A business seen only in one registry has little more than a name, an address and a registration date.

The ETL does no business filtering. Phase 2 starts from businesses a consumer selects. It adds Google reviews and website text, an LLM read of those for signs the owner still runs the business, and starter letters.

The pipeline's job is to be correct, cheap to re-run, and loud when something breaks.

## Users and what they can do

- One user, the repo owner, on this machine. There is no second user, no login, and no web app.
- After phase 1b the owner can:
  - start the stack with `astro dev start`
  - see `retiring_owners` run green every day
  - query `include/data/marts/businesses.parquet` from the host with DuckDB. For example, Texas businesses likely still open with 30 or more years of evidence, with what Google Maps needs:
    ```
    uv run python -c "import duckdb; print(duckdb.sql(\"select lookup_name, lookup_address, lookup_city, lookup_zip5, phone, naics_title, years_in_business, age_source, open_evidence from 'include/data/marts/businesses.parquet' where state = 'TX' and years_in_business >= 30 and open_status = 'likely_open' order by years_in_business desc limit 20\"))"
    ```
  - re-run the whole DAG with `scripts/smoke.sh`, or one task from the Airflow UI at http://localhost:8080
- A future consumer, such as a notebook, a script or phase 2, reads the same file and owns every filter.
- Phase 1 delivered a Texas shortlist, with dated partitions and two CSVs. Spec 05 retires it, and its last output is archived untouched under `include/data/marts/archive/`.

## Anti-goals

- **No business filtering in the ETL.** That means no minimum age, industry list, size cap, open-status rule, exclusion list, shortlist or ranking. Flags and derived facts are columns.
- **No guessing when merging.** A record joins a business only when exactly one candidate fits. Two rows for one business are acceptable; one row for two businesses is not.
- **The pipeline never edits or deletes a raw file.**
  - A publisher's new version replaces the old one through the conditional download.
  - A stage reads only the files the current listing names, so a stale file stays on disk without being counted.
- **No paid data, and nothing behind a login, a bot wall or terms that forbid bulk use.**
  - States whose registry needs any of these get the national sources only. `docs/data-sources.md` lists each one, with the reason and what would unblock it.
  - A file the owner buys or downloads by hand later becomes one more state module.
- **No scraping of search pages, of Google Maps, or of any site whose terms forbid it.** Phase 2 lookups use the Places API.
- No cloud deployment in this phase, only local Docker. It stays a plain Astro project, so `astro deploy` remains possible later.
- No outreach automation. Nothing sends letters or emails.
- No CRM, no outreach tracking, and no manual override lists.
- No scoring model.
- No pandas, no Spark, and no warehouse. About 50 GB of raw files fit DuckDB on this machine.

## Architecture decisions

1. **Astro CLI 1.46.0 and Astro Runtime 3.3-9, run locally in Docker.** The runtime is Airflow 3.3.2 on Python 3.14.8. The owner asked for Astronomer, and both have linux-arm64 builds (verified on this machine). Local dev uses the LocalExecutor, so tasks run inside the scheduler container. The CLI bind-mounts `dags/`, `include/`, `plugins/` and `tests/` into every Airflow container under `/usr/local/airflow/`.
2. **The Airflow containers run as uid 1000, gid 0.** The image's default user is uid 50000, which gets "Permission denied" writing to the host-owned bind mount (verified). `docker-compose.override.yml` sets `user: "1000:0"`. Verified: that user can write the mount and the logs volume and can run DuckDB, and the host user can delete what it writes. The value is specific to this machine.
3. **One DAG, `retiring_owners`.** Spec 06 renames it from `tx_retiring_owners`.
   - It runs `@daily` at 00:00 UTC with `catchup=False`, `max_active_runs=1` and `is_paused_upon_creation=False`. The last setting matters because a triggered run of a paused DAG stays queued forever (verified in the CLI help).
   - It is one DAG because every source feeds one file. DAGs chained by Assets would stall whenever a static source such as PPP does not change.
4. **Files, not a database, in three layers.** Every write goes to a `.part` file that is then renamed with `os.replace`, so a crash never leaves a half-written file and every task can be re-run. `include/data/` is gitignored and dockerignored.
   - **`include/data/raw/`** holds files exactly as published, one folder per source: `ppp/`, `dol/`, `sba/`, `sam/`, `fmcsa/`, and a two-letter folder per state such as `tx/` or `fl/`. Extracted zip members sit beside their zip.
   - **`include/data/stage/`** holds one typed Parquet file per source with **all its rows**: every loan, every filing, every registry entity whatever its status, every carrier, every state. A stage only cleans: it trims, casts strictly, drops exact source duplicates, and drops rows that cannot be keyed. It never filters on age, status or business type.
   - **`include/data/marts/businesses.parquet`** is the one output.
5. **DuckDB in-process for every transform.** It streams large CSVs, writes Parquet natively, and has `jaro_winkler_similarity`, `try_strptime` and a NULL-skipping `least` built in (verified with 1.5.6).
   - Each connection sets `memory_limit` to 8 GB.
   - Mapped stage tasks run at most three at a time.
   - Staging all 11.47M PPP loans in one connection peaked at 4.3 GB RSS (measured).
   - `build` may write intermediate files under `include/data/marts/_work/`, and may spill to a `temp_directory` there, when one statement would not fit in memory.
6. **Downloads are conditional.** A `.meta.json` file next to each raw file records what was seen, and a run re-downloads only what changed.
   - HTTP sources compare the HEAD's `ETag` and `Last-Modified` with that file (verified on SBA, data.texas.gov, data.ny.gov, data.pa.gov, data.colorado.gov, data.oregon.gov, data.ct.gov, data.transportation.gov and DOL).
   - Four sources cannot be checked that way, and each state or source module handles its own:
     - Iowa sends neither header, so a SHA-256 of the body decides "unchanged".
     - Virginia's S3 links reject HEAD, so a one-byte ranged GET reads the validators.
     - Florida is SFTP, so its size and modification time decide.
     - SAM.gov dates its file names, so a name already on disk with a matching size is unchanged.

   Re-fetching about 50 GB every day would be the pipeline's main failure mode.
7. **Transforms rebuild fully on every run.** They take minutes, and incremental logic would add state for no gain. `businesses.parquet` is a full snapshot with a `run_date` column, replaced in place and ordered by `business_id`, so unchanged input gives a byte-identical file. History and "new since yesterday" are consumer logic.
8. **`run_date` is the UTC date on which `build` runs, not the Airflow logical date.** The raw files are always today's snapshot, so labelling a re-run of an old DAG run with its old date would misdate the data. `years_in_business` and the 24-month open-status window are counted to `run_date`.
9. **Records are merged into businesses in five steps, never by guessing.**
   - **Normalization.** Every name passes through the same regex rules (`NAME_MACROS`): uppercase, `&` becomes AND, punctuation goes, a leading THE goes, trailing entity words such as INC and LLC go, and a DBA is split off. Every address gives a five-digit ZIP and a leading street number.
   - **Match tiers.** A tier accepts a candidate only when exactly one fits. Ambiguous candidates fall through to the next tier or stay unmatched.

     | Tier | Matches | On |
     | --- | --- | --- |
     | 1 | registry entity | normalized name and ZIP5, same state |
     | 2 | registry entity | normalized name and city, same state |
     | 3 | registry entity | Jaro-Winkler ≥ 0.92 within the same ZIP5 and street number |
     | 4 | registered trade name (DBA) | name in the same ZIP5 |
     | 5 to 7 | plan sponsor | the same three rules as tiers 1 to 3 |

   - **The five steps:**
     1. **Registry anchors.** Every registry entity is a business. A trade name joins its entity by registry id. A trade-name taxpayer with no registry entity, such as a Texas sole proprietor, becomes a business of its own.
     2. **Sponsors.** Each Form 5500 sponsor joins a registry business by exact EIN, which works in Texas and Florida. Failing that, it joins by tiers 1 to 3 on its own name and address, but never to a registry entity that carries a different EIN. Otherwise it becomes a business of its own.
     3. **Records.** Every other record joins a business: tiers 1 to 4 first, then tiers 5 to 7 to the business of the matched sponsor. The other records are PPP name-and-ZIP keys, SBA name-and-ZIP keys, SAM entities and FMCSA carriers. Tiers 5 to 7 are computed for every record; a record already joined in tiers 1 to 4 uses them only for step 5.
     4. **Leftovers.** Records that joined nothing are grouped by exact `(norm_name, zip5)`. A group holds at most one record per source; when one source has two records with the same key, those stay separate rows.
     5. **One hop for plans.** A sponsor left on its own merges into the registry business of the records that matched it in tiers 5 to 7, but only when all of them point to that one business.

     Links always point at anchors, never from record to record to record, so one bad link cannot chain two businesses together.
   - Each row carries `match_tier`, the best tier any of its records used, and `sources`, the sorted list of the sources it was seen in.
10. **Federal EINs come from three places.**
    - Texas taxpayer numbers embed the EIN: `1`, then the 9-digit EIN, then a check digit (verified on Texas Instruments and Southwest Airlines).
    - Florida publishes it as the FEI number.
    - Form 5500 is keyed by it.

    An EIN links exactly, so no name matching is needed where one exists.
11. **Years in business come from the oldest evidence, one of the two primary measures.** These dates count:
    - registry formation date
    - Texas first-sales date
    - pension plan effective date
    - SBA loan approval date
    - SAM.gov entity start date
    - FMCSA add date
    - the PPP loan date, the weakest: "existed by 2020"

    `years_in_business` is the number of complete years from the oldest of them to `run_date`, `oldest_evidence_date` is that date, and `age_source` names which record it came from. Every value is a lower bound: the business is at least this old. Known placeholder dates are ignored: 1900-01-01 everywhere, Pennsylvania's 1753-01-01 and Connecticut's 0001-01-03.
12. **Quality gates are tasks, and they check data quality only.**
    - Every stage asserts its exact header, its row floor, its parse failures and a known sentinel row.
    - A `qc` task checks the business file:
      - row floor and `business_id` uniqueness
      - conservation: every staged record lands in exactly one business, and the PPP loans add up to the staged count
      - matched share per registry state
      - state coverage
      - that the open-status and age columns are consistent

      It logs the coverage of the four column groups (industry, years, lookup address, open status) per state.
    - A failed check fails the DAG. Floors are calibrated on the first real run and recorded in that spec's implementation notes.
13. **Pipeline code is plain Python under `include/pipeline/` and never imports Airflow.** A ruff rule enforces this. The DAG file is a thin layer of `@task` wrappers. Unit tests run on the host with `uv run pytest`, offline, against tiny fixture files that include known malformed rows. DAG integrity is checked in the image with `astro dev parse`. From spec 06 the layout is:
    - **Plumbing:** `http.py`, `db.py`, `names.py`, `paths.py`, and `zips.py` from spec 09. None of it knows any state or source.
    - **`national/`:** `ppp.py`, `dol.py`, `sba.py`, `sam.py` and `fmcsa.py`, the sources that cover every state.
    - **`states/`:**
      - `states/__init__.py` holds the contract, a `Source` per dataset, and the `STATES` list.
      - Each state has one module named in full, such as `states/texas.py` or `states/new_york.py`. Everything about that state lives there: URLs, exact headers, column mapping, quirks, sentinel, floors, and any download or read it needs beyond the default.
    - **The transform:** `businesses.py` and `sql/businesses.sql` name no state.
    - **Tests** mirror the layout: `tests/unit/states/test_<state>.py` and `tests/fixtures/states/<state>/`.
    - **Adding a state** takes one new file, one line in `STATES`, one fixture and one test.
14. **Tooling follows this machine's `setup-repo` standard.** `mise.toml` pins python 3.14, uv and astro 1.46.0, and uv manages a repo-local `.venv`. `orca.yaml` lets worktrees install themselves for unit tests and lint. Only one checkout runs the Astro stack at a time, because ports 8080 and 5432 are fixed. `mise run check` is the one validation command, since `make` is not installed here.
15. **Secrets live only in `.env`**, which the Astro template already gitignores and dockerignores. Phase 1b has none: every source is anonymous. Florida's SFTP login is published by the state for public access, so it is not a secret. Phase 2 adds `GOOGLE_MAPS_API_KEY` and `ANTHROPIC_API_KEY`.
16. **A business is anything seen in any source, with records of the same business merged (decision 9).**
    - `business_id` follows the strongest identity:
      1. **A registry business:** `EIN-<ein>` when the registry carries an EIN, else `<state>-<registry_id>`.
      2. **A sponsor business:** `EIN-<ein>`.
      3. **A leftover group:** `KEY-<zip5>-<norm_name>`.
      4. **A leftover record whose key it shares with another record of its own source:** that source's id, such as `SAM-<uei>` or `DOT-<number>`.
    - Aggregation is deterministic. Amounts and counts are summed, dates take the earliest, and flags are OR-ed. Descriptive fields follow fixed source priorities (decisions 18 and 20), with fixed tiebreaks.
17. **Every detail is carried, and the transform names no state.**
    - **Registry stage files** have common columns:
      - `state`, `registry_id`, `ein`
      - `name`, `norm_name`
      - `address`, `city`, `zip5`, and `address_kind`, which is `physical`, `mailing` or `legal`
      - `entity_type`, `status`, `status_date`, `active`
      - `formed_date`, `naics`, `officers`
      - `as_of`, the publisher's data date
    - **Trade-name stage files** have their own common columns:
      - `state`, `registry_id`, `ein`, `entity_type`
      - `dba_name`, `norm_dba_name`
      - `address`, `city`, `zip5`
      - `first_seen_date`, `naics`, `as_of`
    - **Extras:** a state module may add columns prefixed with its state code, such as `tx_sos_file_number` or `ny_dos_process_name`. The transform passes those through without naming them, so a consumer can see where each detail came from. NULL means that business's sources do not have that detail.
18. **Industry, the other primary measure, takes the first code available in this order:**
    1. PPP: the most frequent code across the business's loans, latest first
    2. Form 5500 business code
    3. SAM primary NAICS
    4. SBA loan NAICS, latest loan
    5. trade-name NAICS (Texas outlets)
    6. registry NAICS (Texas, Connecticut)
    7. FMCSA: `484` (truck transportation) for for-hire carriers only

    `naics_source` names the source. Titles come from the Census 2017 code list in `include/pipeline/naics_2017.csv`. A code from another edition gets the title of its longest known prefix, as in spec 04.
19. **Open status is "what is the newest thing we know about this business?"**
    - Every source contributes dated signals.

      | Kind | Signal | Dated by |
      | --- | --- | --- |
      | Activity | a registry record in good standing | the publisher's `as_of` |
      | Activity | a listed Texas sales-tax permit | the publisher's `as_of` |
      | Activity | a Form 5500 received | date received |
      | Activity | an SBA or PPP loan approved | approval date |
      | Activity | an active SAM registration | its activation date |
      | Activity | an active FMCSA carrier | its last MCS-150 update |
      | Closure | a registry record not in good standing | `status_date`, else `as_of` |
      | Closure | an inactive FMCSA carrier | its last MCS-150 update, else `as_of` |
      | Closure | a PPP or SBA loan charged off | the charge-off or loan-status date |

    - The status follows the newest signal:
      - `likely_open` when it is an activity within 24 months of `run_date`.
      - `likely_closed` when it is a closure.
      - `unknown` when it is an older activity, or when there are no signals. A business seen only through a 2021 PPP loan is `unknown`.
    - `open_evidence` names the deciding signal and its date, for example `tx_franchise good standing 2026-10-10` or `form 5500 received 2025-07-01`.
    - Registries that list every entity not formally dissolved, with no annual report enforced (New York, Pennsylvania), leave `active` NULL and give no signal.
    - Google Places' business status in phase 2 is the real check.
20. **Google Maps lookup fields, the secondary measure.**
    - `lookup_name` is the trading name when any source gives one. The order is Texas outlet name, PPP DBA, SAM DBA, FMCSA DBA, then the Form 5500 DBA. Otherwise it is the PPP name, then SAM, FMCSA, registry and sponsor names, in that order.
    - `lookup_address`, `lookup_city`, `lookup_state` and `lookup_zip5` are the first physical address in this order:
      1. FMCSA physical
      2. SAM physical
      3. Texas outlet
      4. PPP borrower
      5. registry with `address_kind = 'physical'`

      Only when there is none do they fall back to Form 5500 and registry `mailing` addresses, and last to `legal` addresses such as New York's address for legal papers. `lookup_address_source` says which.
    - `phone` comes from Form 5500, then FMCSA.
    - `names` lists every distinct name seen, so a consumer can retry a lookup.

## Defaults the owner may veto

- A business is anything seen in any source (decision 16). That includes registry entities with no other record, which are often dormant; `sources` and `open_status` let a consumer drop them.
- `business_id` prefers the registry identity, then the EIN.
- Form 5500 goes back to 2009, the oldest "Latest" file DOL publishes.
- `active` is each publisher's own good standing:

  | State | `active` means |
  | --- | --- |
  | TX | right to transact `A` |
  | FL | status `A` |
  | CO | `Good Standing` |
  | CT | `Active` |
  | DC | `Active - In Good Standing` |
  | VA | `ACTIVE`, as of its 2024 snapshot |
  | OR, IA | listed at all: their active lists drop entities that miss renewals |
  | NY, PA | NULL: their lists hold every entity not formally dissolved |

- The open-status window is 24 months. The industry and lookup source orders are as in decisions 18 and 20.
- The schedule: 00:00 UTC, which is 19:00 Central.
- A loan's state is `BorrowerState`, or `ProjectState` when `BorrowerState` is blank.
- Removed by the 2026-10-17 revision, now consumer logic: `MIN_YEARS = 30`, the NAICS exclusion list (religious and civic organizations, private households, public administration), and the active and nonprofit filters. The owner's earlier veto of the trades-only allowlist stands.

## Riskiest unknowns

- **Merge quality.** Exact normalized names plus a ZIP, city or street number miss businesses that use different names in different records, which gives two rows for one business. They rarely join two different businesses, because of the exactly-one rule. `qc` logs the rates, and each spec's notes record a hand check of a sample.
- **Build size.** About 30M registry entities as anchors, and about 18M records to link: 9.2M PPP keys, about 1.8M SBA keys, 0.9M SAM entities, 4.5M carriers and about 1.5M sponsors. That is far more than the 0.76M x 3.5M Texas join, which took 2 seconds. Decision 5 allows intermediate files and spilling. Each spec records the build's duration and peak memory.
- **Registry-only rows dominate.** Most of the ~30M registry entities have no other record. Many are shells or long dissolved: Colorado alone lists 600k voluntarily dissolved entities. They are kept on purpose, flagged by `sources` and `open_status`.
- **Match rate per new registry.**
  - New York fills the location ZIP on 8% of rows and the DOS process ZIP on 98% (measured). The process address is often a lawyer or an agent.
  - Pennsylvania's address may be the registered office.
  - Rates are calibrated per state. A low rate means more unmerged rows, never a wrong date.
- **Undocumented endpoints.** SAM.gov's keyless download and Iowa's download URL come from the portals' own buttons and may change without notice. The tasks fail loudly when they do.
- **Florida's size.** About 13M fixed-width records, roughly 18 GB unzipped, come in a Deflate64 zip that Python cannot read. The image needs `unzip` (`packages.txt`).
- **Stale and self-reported dates.**
  - Virginia's data is a 2024 snapshot, so its statuses may be stale; its `as_of` says so.
  - SAM.gov start dates are self-reported.
  - The FMCSA add date is when a carrier joined the USDOT system, a lower bound on its age.
- **Open status is coarse.** The 24-month rule cannot see a business that closed last month and still shows good standing. That is why `open_evidence` is shown and phase 2 checks Places.
- **Charter date is not founding date.** Decision 11 mitigates this, but some old businesses will still look young. Accept.
- **Portal throttling.** HEAD requests and full downloads worked without a token on data.texas.gov. If another portal returns HTTP 429, the fallback is a free Socrata app token for that portal.
- **The machine has to be on.** Docker starts at boot (verified), and every Astro service has `restart: unless-stopped`, so the stack returns after a reboot unless `astro dev stop` was run. With `catchup=False`, the scheduler runs the most recent missed day once and skips older ones. Accept for "local for now".
- **Owner names come from many partial sources.** The file carries every name, labelled by source; none is certain to be the owner.

  | Source | Name it gives | Coverage |
  | --- | --- | --- |
  | Form 5500 | plan signer, an officer and often the owner | 88% of Texas small plans name the sponsor as administrator |
  | New York | CEO | 11% of rows |
  | Pennsylvania | officers, one row each | |
  | Florida | up to six officers | |
  | Oregon | authorized representative | |
  | Virginia | officers file | |
  | Connecticut | principals file | |
  | FMCSA | two company officers | |
  | SAM.gov | points of contact | |
- **Phase 2 cost.** Places lookups are paid per call. Reviews sit in the most expensive SKU, about $25 per 1,000 calls in third-party tables, which is unverified. A consumer filter on industry, years and open status decides how many businesses are looked up.

## Specs

Phase 1 is the Texas pipeline, specs 00 to 04, built. Phase 1b covers all states and all sources and was planned on 2026-10-17. It is ordered by value per session: first the shape on Texas, then national coverage, then cheap national evidence, then the largest free registries, then the long tail. Each line is one `/implement` session. The phase 2 lines are placeholders, to be specified once phase 1b is green.

- [x] `00-skeleton` — `astro dev start` comes up, and `scripts/smoke.sh` runs `tx_retiring_owners`, whose one task writes `include/data/stage/_smoke.parquet` owned by uid 1000. `mise run check` runs pre-commit (ruff and strict mypy), the first unit test and `astro dev parse`. The Commands section of CLAUDE.md is filled in.
- [x] `01-ppp-extract` — The DAG finds the 13 SBA PPP CSVs, downloads only the changed ones into `include/data/raw/ppp/`, and writes `include/data/stage/ppp_tx.parquet` with every Texas loan, typed, plus `norm_name` and `zip5`. A second run logs `unchanged` for all 13 files.
- [x] `02-tx-comptroller-extract` — Downloads Active Franchise Taxpayers and Active Sales Tax Permit Holders when their ETag changes, and writes `stage/tx_franchise.parquet` and `stage/tx_sales_outlets.parquet` with a derived `ein`. Taxpayer 17502899705 (Texas Instruments) shows EIN 750289970 and charter date 1938-12-31.
- [x] `03-dol-5500-extract` — Downloads the Form 5500 and 5500-SF "Latest" zips for 2022 to 2025 when they change, and writes `stage/dol_5500_tx.parquet`. It has one row per Texas sponsor EIN, with the latest filing's signer, phone, participant counts and plan codes, plus the earliest plan effective date.
- [x] `04-match-and-shortlist` — Joins the three stages in four match tiers and writes `marts/matches.parquet`, a dated shortlist partition, `marts/shortlist_latest.csv` and `marts/shortlist_new_since_previous.csv`. A `qc` task fails the run on a low match rate or on duplicates. After this spec the DAG runs end to end every day. Spec 05 retires the shortlist.
- [x] `05-business-dataset` — Texas becomes a strict ETL ending in `marts/businesses.parquet`: every business from every Texas source, merged in decision 9's five steps, with industry, years in business, lookup fields and open status, and no filter. `ppp_discover` stops deleting raw files, and the shortlist and CSV exports are gone. About 4 million Texas businesses result. A consumer query over the file reproduces the old 25,842-row shortlist, with any differences explained.
- [x] `06-national-sources` — PPP for all states and Form 5500 for 2009 to 2025, all states. The code moves into `national/` and `states/`, with Texas as the first state module, and the transform becomes generic. The DAG is renamed `retiring_owners`. Every PPP borrower and plan sponsor in the country becomes a business, in at least 51 states and DC, and Texas results are unchanged.
- [x] `07-sba-loans` — All six SBA 7(a) and 504 FOIA files, FY1991 to the present, staged per loan. SBA borrowers join or become businesses, with industry, an approval date as age evidence, and charge-offs as a closure signal.
- [x] `08-registries-ny-pa-co` — New York, Pennsylvania and Colorado registries as state modules: every entity becomes or joins a business. The sentinels are IBM (30059, 1911-06-16), D. G. Yuengling and Son (0000399042, 1914-04-09) and the Manitou and Pike's Peak Railway (19871009071, 1888-11-17).
- [x] `09-sam-start-dates` — The SAM.gov monthly public entity extract, staged in full. Entities join or become businesses, adding UEI, NAICS, start date, physical address and points of contact.
- [x] `10-registry-florida` — Florida's quarterly corporate file, read over SFTP and fixed-width, with the FEI number as EIN and up to six officers. The sentinel is Raymond James Financial (444750, 1974-01-24, EIN 591517485).
- [x] `11-registries-or-ct-dc` — Oregon, Connecticut (with its principals file) and DC registries. The sentinels are Pendleton Woolen Mills (1333616, 1909-02-16), Stanley Black & Decker (0074441, 1901-06-04) and Washington Gas Light (571294, 1957-03-25).
- [x] `12-registries-ia-va` — Iowa (SHA-256 change check, zipped CSV) and Virginia (ranged-GET change check, XLSX and CSV files from a 2024 snapshot, officers file). The sentinels are Hy-Vee (019862, 1938-01-03) and Universal Corporation (00164871, 1918-01-25).
- [x] `13-fmcsa-carriers` — The FMCSA Company Census, all 4.5M carriers. Carriers join or become businesses, adding USDOT number, status, add date, officers, fleet size, phone and a physical address.
- [ ] `14-places-enrichment` — For each business in a list of `business_id` a consumer selects, a Google Places API (New) text search returns the place id, website, rating, review count, business status and up to 5 reviews. It searches with `lookup_name` and the lookup address, retries with the other `names`, and records which query matched. Each business is fetched once and cached under `include/data/enrich/`.
- [ ] `15-website-text` — Fetches the homepage and about or team pages for businesses that have a website, and stores the text. It respects robots.txt.
- [ ] `16-owner-signals` — Claude Haiku reads each business's reviews and website text and returns a structured record. The record says whether the owner still does the work, whether a successor is mentioned, whether retirement is mentioned, and a guess at the owner's name, each with a quoted evidence snippet. Output goes to `marts/owner_signals`.
- [ ] `17-letters` — Drafts starter letters, one Markdown file each, for businesses a consumer selects. The owner edits, signs and posts them.
