# 06-national-sources

Takes the pipeline to every US state. PPP and Form 5500 are staged nationally. The code splits into `national/` and `states/`, with Texas as the first state module. Spec 05's merge becomes a generic transform that names no state.

Bound by `docs/specs/00-product/spec.md`: decisions 3 to 13 and 16 to 20, the anti-goals, and `docs/data-sources.md` sections 1 to 3 and 5 to 6. It builds on spec 05's `businesses.parquet` and keeps its columns.

## Goal

The DAG is renamed `retiring_owners`. Its sources:

- PPP: all 13 files, every state, all 11.47M loans.
- Form 5500 and 5500-SF: every "Latest" file from form year 2009 to 2025, 34 zips, every filing in every state.

The pipeline code takes the layout every later spec follows:

- plumbing at the top
- `include/pipeline/national/` for sources that cover every state
- `include/pipeline/states/` with one module per state, Texas first, and the `Source` contract every state uses

The transform runs product decision 9's five steps over whatever registries and trade-name sources the contract lists:

- Registry tiers 1 to 3 match only within a record's own state.
- Sponsor tiers 5 to 7 match only within the sponsor's state.
- Leftover groups take every national record.
- Every PPP borrower and every plan sponsor in the country becomes a business or joins one.

Texas registry businesses are unchanged from spec 05, apart from what the older plan years add. Every other state gets businesses from PPP and Form 5500 alone, with industry, years in business, lookup fields and open status wherever those sources give them.

## What the user can do afterwards

```
scripts/smoke.sh 14400
uv run python -c "import duckdb; print(duckdb.sql(\"select state, count(*) businesses, count(naics) with_industry, count(years_in_business) with_years, count(lookup_address) with_address, count(*) filter (where open_status = 'likely_open') likely_open from 'include/data/marts/businesses.parquet' group by 1 order by 2 desc limit 15\"))"
ls include/pipeline/national include/pipeline/states
```

## Anti-goals

- No new state registries. Specs 08, 10, 11 and 12 add them. No SBA, SAM or FMCSA, which are specs 07, 09 and 13.
- No filtering of any kind, as in spec 05.
- No matching across states. Tier 2 joins on the state as well as the city, so SPRINGFIELD in Illinois never matches SPRINGFIELD in Missouri.
- No change to name normalization or to the tier rules.
- No deletion of old stage files. `stage/ppp_tx.parquet`, `stage/dol_5500_tx.parquet`, `stage/tx_franchise.parquet` and `stage/tx_sales_outlets.parquet` are no longer written. The notes list them for the owner to delete.
- No raw file moves. Texas raw files stay in `include/data/raw/tx/`, which is also the contract's folder for Texas, so nothing is downloaded again.

## Files and interfaces

### Layout

- `git mv include/pipeline/ppp.py include/pipeline/national/ppp.py` and the same for `dol.py`; add an empty `national/__init__.py`.
- `include/pipeline/texas.py` is split:
  - Its generic parts go to `include/pipeline/states/__init__.py`: header check, trimmed raw table, typed select, floors, `mdy`.
  - The Texas specifics go to `include/pipeline/states/texas.py`.
- Tests and fixtures mirror the code:
  - `tests/unit/national/test_{ppp,dol}.py` and `tests/fixtures/national/{ppp,dol}/`
  - `tests/unit/states/test_texas.py` and `tests/fixtures/states/texas/`

  Use `git mv` throughout. Test file basenames stay unique.
- `http.py`, `db.py`, `names.py` and `paths.py` stay where they are and learn nothing about states.

### `national/ppp.py`

- `stage(urls: list[str], data: Path = DATA, min_rows: int = 8_000_000) -> int` replaces `stage_tx` and drops the Texas filter.
- It writes `stage/ppp.parquet`.
- Unusable rows lack `zip5`, `norm_name` or `state`. On 2026-10-17 there were 363 of them: 197 without a ZIP, 166 without a name and 28 without a state. They are dropped, and `dropped < 1000` stays.
- The stage keeps every state code, including DC and the territories.

### `national/dol.py`

- `YEARS = range(2009, 2026)`, with the comment `# shortcut: extend the range by hand when DOL publishes the next form year's Latest zip; first filings for plan year N appear around July of N+1`.
- `url()` builds on `https://www.askebsa.dol.gov/FOIA%20Files/`. The bare host's 301 sends a raw space in `Location` (verified).
- `stage(data: Path = DATA, min_rows: int = <calibrated>) -> int` writes `stage/dol_5500_filings.parquet`. It holds every filing, in every state, whose EIN is 9 digits: today's `filings` CTE columns plus `ack_id`, `is_defined_benefit` and `sponsor_dba_name`, typed strictly.
  - Older layouts are strict subsets of 2022 with no renames (verified). The `*_MANUAL_SIGNED_NAME` columns are missing before 2015 to 2018, and the SF location columns before 2012. `union_by_name` reads them as NULL.
  - The stage asserts the floor, calibrated to about 70% of the first run, and that Texas Instruments' EIN `750289970` is present.
- The per-EIN pick moves to the transform's `sponsors` CTE: the latest filing by `date_received`, `plan_year_begin`, `ack_id`, plus `plan_count`, `earliest_plan_eff_date`, `ever_defined_benefit` and the latest `date_received`. A sponsor's state, address and phone are its latest filing's.

### `states/__init__.py`, the contract

```python
@dataclass(frozen=True)
class File:
    name: str                 # raw file name under raw/<state lowercased>/
    url: str
    header: str               # first line exactly as served, stray spaces included
    columns: tuple[str, ...]  # our names for those columns, in order

@dataclass(frozen=True)
class Source:
    name: str                 # stage file name, e.g. "tx_franchise"
    state: str                # two-letter code
    kind: Literal["registry", "dba"]
    files: tuple[File, ...]   # each becomes a temp table named after the file stem
    select: str               # SQL over those tables producing the stage rows
    min_rows: int
    dropped: tuple[int, int]  # allowed (first file's raw rows - staged rows), inclusive
    sentinel: tuple[str, date] | None  # registry_id and formed_date that must be staged
    min_match_share: float = 0.30
    download: Callable[[File, Path], bool] | None = None  # default: download_if_changed
    read: Callable[[duckdb.DuckDBPyConnection, File, Path], None] | None = None  # default below
```

- **`REGISTRY_COLUMNS`:**
  - `state`, `registry_id`, `ein`
  - `name`, `norm_name`
  - `address`, `city` (uppercased), `zip5`
  - `address_kind`: `physical`, `mailing` or `legal`
  - `entity_type`, `status`, `status_date`
  - `active`: the publisher's own good standing, or NULL where it does not track standing
  - `formed_date`, `naics`
  - `officers`: `VARCHAR[]` of `"TITLE: NAME"` strings, or NULL
  - `as_of`
- **`DBA_COLUMNS`:** `state`, `registry_id`, `ein`, `entity_type`, `dba_name`, `norm_dba_name`, `address`, `city`, `zip5`, `first_seen_date`, `active`, `naics`, `as_of`.
- **`as_of`** is the publisher's data date. `stage` fills it from the first file's sidecar `last_modified`, or from `downloaded_at` when there is none.
- **Extras:** any other column a source outputs must start with its state code in lowercase and an underscore, such as `tx_sos_file_number`. Two sources of one state may not output the same extra name.
- **`STATES = (texas,)`**, then:
  - `SOURCES = {s.name: s for m in STATES for s in m.SOURCES}`, which must have unique names.
  - `FILES`, which maps each file name to `(state, File)`. Several sources of one state may share one `File`, which is then downloaded once, as Virginia's officers file will be. Two different `File`s may not share a name. Downloads map over files; stages map over sources.
- **`download(file_name: str, data: Path = DATA) -> bool`** calls the source's `download`, or `download_if_changed(url, data / "raw" / state.lower() / name)`.
- **Default `read`:**
  1. Compare the file's first line, read as `utf-8-sig`, with `File.header`. Raise `ValueError` showing the served and expected lines when they differ.
  2. Create a temp table named after the file stem: `select nullif(trim(columns(*), e' \t\r\n'), '') from read_csv(?, header=true, all_varchar=true, names=?)`.
- **`stage(name: str, data: Path = DATA, min_rows: int | None = None) -> int`:**
  1. Reads every file.
  2. Runs `select` into a temp table `staged`, and adds `as_of`.
  3. Asserts, before writing, as today:
     - the floor
     - the dropped range
     - `ein` is NULL or 9 digits
     - extras are prefixed with the state code
     - `address_kind` is one of the three values
     - for registries: exactly `REGISTRY_COLUMNS` plus extras, a unique `registry_id`, and the sentinel's `formed_date`
     - for trade names: `DBA_COLUMNS` plus extras
  4. Writes `stage/registry/<name>.parquet` or `stage/dba/<name>.parquet`.
- **`stage_paths(kind: str, data: Path = DATA) -> list[str]`** lists the stage files the transform reads.
- **`mdy(col)`** moves here from `texas.py`.

### `states/texas.py`

- A docstring naming the publisher (Texas Comptroller of Public Accounts, data.texas.gov), both dataset ids, the weekly refresh and `docs/data-sources.md` section 2.
- The `EIN` expression, as today.
- **`tx_franchise`**, a registry with one `File`: today's header and columns, `raw/tx/tx_franchise.csv`.
  - The select keeps today's typed CTE and dedupe, and outputs:
    - `state = 'TX'`
    - `registry_id = taxpayer_number`
    - `ein`
    - `name = taxpayer_name`
    - `norm_name`, `address`, `city`, `zip5`
    - `address_kind = 'mailing'`, because the Comptroller's taxpayer address is where tax mail goes
    - `entity_type = org_type`
    - `status = sos_status`, `status_date = sos_status_date`
    - `active = coalesce(right_to_transact = 'A', false)`
    - `formed_date = charter_date`
    - `naics`
    - `officers = NULL::VARCHAR[]`
  - Extras: `tx_sos_file_number`, `tx_record_type`, `tx_right_to_transact`, `tx_responsibility_begin_date`, `tx_exempt_reason`, `tx_county_code`.
  - `min_rows=3_000_000`, `dropped=(1, 999)`, sentinel `("17502899705", date(1938, 12, 31))`.
- **`tx_sales_outlets`**, a trade-name source.
  - The select outputs:
    - `state = 'TX'`
    - `registry_id = taxpayer_number`
    - `ein`
    - `entity_type = org_type`
    - `dba_name = outlet_name`, `norm_dba_name`
    - the outlet address, city and ZIP
    - `first_seen_date = first_sales_date`
    - `active = true`, because the dataset lists active permits only
    - `naics = outlet_naics`
  - Extras: `tx_outlet_number`, `tx_permit_issue_date`, `tx_taxpayer_name`.
  - `min_rows=800_000`, `dropped=(0, 0)`, no sentinel.

### `businesses.py` and `sql/businesses.sql`

- **Variables:** `ppp`, `registry` (a list of paths), `dba` (a list of paths), `filings`, `run_date`, `naics_titles`. The `*_as_of` variables of spec 05 go, because `as_of` is now a column.
- **`reg`** is `read_parquet(getvariable('registry'), union_by_name=true)`, and **`dba`** is built the same way.
- **Spec 05's steps, made generic:**
  - Step 1 builds anchors from every registry row, and from every trade-name taxpayer without a registry row in its state.
  - Step 2 runs over national `sponsors`. EIN matches use exact EIN and the same state. Name tiers 1 to 3 run only against registry rows of the sponsor's state that carry no EIN.
  - Step 3: PPP keys run tiers 1 to 4 against their state's registry and trade names (`f.state = p.state`), and tiers 5 to 7 against sponsors of their state.
  - Steps 4 and 5 are unchanged. Leftover groups are keyed by `(norm_name, zip5)` nationally; a ZIP belongs to one state, with rare exceptions, and the 119 keys that span two states take the latest loan's state.
- **`business_id`, aggregation and the four column groups** follow spec 05 and decisions 16 to 20, now from contract columns:
  - **`sources`** holds the source names: registry and trade-name source names, `dol_5500`, `ppp`.
  - **Industry:** PPP, then the sponsor business code, then trade-name NAICS, then registry NAICS.
  - **Years:** `formed`, `first_sales` (the trade name's `first_seen_date`), `plan` and `ppp_loan`.
  - **Lookup:** trade-name address, then PPP address, then a registry `physical` address, then registry and sponsor `mailing` addresses, then `legal` ones. `phone` comes from the sponsor.
  - **Open status:**
    - Activity: a registry row with `active = true`, dated `as_of`; a trade-name row with `active = true`, dated `as_of`; a sponsor's latest `date_received`; the latest PPP approval.
    - Closure: a registry row with `active = false`, dated `status_date`, else `as_of`; a charged-off PPP loan.
    - `active` NULL gives no signal.
  - **Extras:** every extra column of the matched registry and trade-name rows is passed through by pattern (DuckDB `COLUMNS('^[a-z]{2}_')` over a renamed subquery), never by name.
- **`qc`** keeps spec 05's checks, generalized: conservation counts every registry row, trade-name taxpayer, sponsor EIN and PPP key in the stages. It adds:
  - a matched share of PPP keys per registry state, each at least its source's `min_match_share`, from `states.SOURCES`
  - at least `min_states` distinct `state` values, default 51 (50 states and DC); tests pass a smaller number
  - every row has a `state`
  - a coverage log line per state: rows, industry, years, lookup address, and each open status

### DAG and scripts

- `git mv dags/tx_retiring_owners.py dags/retiring_owners.py`. The dag id is `retiring_owners` and the tag is `retiring-owners`. Tasks:
  - `ppp_discover`, then `ppp_download.expand`, then `ppp_stage(urls)`
  - `state_download.expand(file_name=list(states.FILES))`, then `state_stage.expand(name=list(states.SOURCES))`. Both use `max_active_tis_per_dag=3`, and their `map_index_template` shows the file or source name in the UI.
  - `dol_download.expand` over 34 URLs with `max_active_tis_per_dag=2`, then `dol_stage`
  - `[ppp, state, dol stages] >> build >> qc`
- `scripts/smoke.sh`: `dag=retiring_owners`, and the usage line too.
- **`CLAUDE.md`:**
  - The first line describes the national business dataset.
  - The log command uses `dag_id=retiring_owners`.
  - Under "Working here", add: "Everything about one state lives in `include/pipeline/states/<state>.py`; no other file names a state. Adding a state is one new module, one line in `STATES`, a fixture under `tests/fixtures/states/<state>/` and a test in `tests/unit/states/`."
- **`tests/unit/test_layout.py`** enforces that rule. No file under `include/pipeline/`, other than `states/<state>.py` and `naics_2017.csv`, contains a quoted two-letter US state code (`'TX'`, `"FL"` and so on, from a list in the test).

### Tests

- **`tests/unit/national/test_ppp.py`:**
  - Every fixture row is staged, out-of-state rows included.
  - The stale-file and missing-file cases from spec 05.
- **`tests/unit/national/test_dol.py`:** every filing is staged. An out-of-state sponsor is kept, and both filings of the same EIN are kept.
- **`tests/unit/states/test_texas.py`:** today's three tests rewritten on the contract:
  - the common columns, `address_kind`, `as_of` from the fixture sidecar, extras, Texas Instruments' EIN and its 1938-12-31 `formed_date`
  - a renamed header raises
  - a malformed date raises and writes nothing

  Plus one contract test: a source whose select omits `formed_date` fails before writing.
- **`tests/fixtures/businesses/make_fixtures.py`** writes stage files directly:
  - spec 05's Texas cases on the contract's columns
  - a second registry for a fixture state, `IL`, without EINs, which proves the transform names no state
  - `ppp.parquet` with several states
  - `dol_5500_filings.parquet`

  New cases:
  - SPRINGFIELD PLUMBING in IL and in MO. It joins its IL registry business in tier 2, and is a `KEY-` business in MO, which has no registry fixture.
  - A sponsor in OH, which has no registry, that a PPP key joins in tier 5. It is one business: `EIN-…`, `sources = ['dol_5500', 'ppp']`.
  - A tier-6 sponsor in a different ZIP of the same city.
  - A tier-7 near-name sponsor at the same street number.
  - An IL registry business whose PPP key also matches a lone sponsor in tier 5: the hop merges it, with `plan_link = 'hop'`.
  - Two IL registry entities whose PPP keys both match one sponsor in tier 6. The hop does not fire, so there are three businesses.
  - A sponsor with two filings from different years: the latest signer and phone, and the earliest plan date.
- **`tests/unit/test_businesses.py`:**
  - exact counts per source combination and per tier
  - every case above
  - conservation
  - `qc` raises when a registry state's share is below its floor, and when fewer than `min_states` states are present

## End-to-end verification

1. Before starting, copy spec 05's `include/data/marts/businesses.parquet` to the session scratchpad as the Texas baseline.
2. Pause `tx_retiring_owners` so a scheduled run cannot pick up half-moved code: `astro dev run dags pause tx_retiring_owners`. Write the new DAG file last.
3. Run `scripts/smoke.sh 14400` and paste its output. The first run downloads 26 more Form 5500 zips, about 1.6 GB. Record the `build` task's duration and peak memory. If it spills or runs out of memory, apply decision 5 (intermediate files, a `temp_directory`) and record what was used.
4. Paste the per-state query output: at least 51 states. Also paste the national counts by source combination, the `age_source` and `naics_source` mixes, and the open-status counts.
5. Texas regression against the baseline:
   - Every Texas business from spec 05 with a `registry_id` is present under the same `business_id`, with the same `registry_id`, `formed_date` and `match_tier`.
   - Its `years_in_business` is the same or higher. It is higher only where a 2009 to 2021 plan was older.
   - New Texas rows are only sponsors that first appear in the 2009 to 2021 files.
   - Paste the counts of each case.
6. Hand-check 20 random multi-source businesses and 20 random `KEY-` businesses outside Texas, as in spec 05, and record the counts.
7. The Airflow UI lists `retiring_owners` green. `tx_retiring_owners` is no longer active.
8. Run `scripts/smoke.sh 14400` again. Every download logs `unchanged`, and the file's `sha256sum` is identical.
9. `mise run check` passes, including `test_layout.py`.
