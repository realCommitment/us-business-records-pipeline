# C4 Code Level: include/pipeline

## Overview

- **Name**: Data pipeline library (`include/pipeline`)
- **Description**: Python helper modules that download public Texas-business source files (SBA PPP loans, Texas Comptroller franchise and sales-tax exports, DOL Form 5500 filings), stage them as Parquet with strict validation, match PPP borrowers to Texas registrations, and write the daily shortlist and its CSV exports. The SQL logic lives in `sql/shortlist.sql`; the Census NAICS code list is a data asset.
- **Location**: [include/pipeline/](../include/pipeline/)
- **Language**: Python (module code, with `requests`, `duckdb`); DuckDB SQL (embedded SQL strings in `.py` files and `sql/shortlist.sql`); CSV data asset (`naics_2017.csv`).
- **Purpose**: Provide the stage, match, shortlist and export steps that the Airflow DAG (`dags/tx_retiring_owners.py`, outside this directory) imports as `dol`, `ppp`, `shortlist` and `texas`. `include/` does not import Airflow.

### Files in scope

| File | Lines | Role |
| --- | --- | --- |
| [`__init__.py`](../include/pipeline/__init__.py) | 0 | Empty package marker |
| [`db.py`](../include/pipeline/db.py) | 42 | DuckDB connection factory and atomic Parquet/CSV writer |
| [`dol.py`](../include/pipeline/dol.py) | 156 | DOL Form 5500 download, zip extraction, staging |
| [`http.py`](../include/pipeline/http.py) | 67 | Conditional HTTP download with sidecar metadata |
| [`names.py`](../include/pipeline/names.py) | 27 | DuckDB name-normalization macros (`NAME_MACROS`) |
| [`paths.py`](../include/pipeline/paths.py) | 4 | `DATA` root path constant |
| [`ppp.py`](../include/pipeline/ppp.py) | 110 | SBA PPP listing scrape, download, Texas staging |
| [`shortlist.py`](../include/pipeline/shortlist.py) | 156 | Matching/shortlist build, QC assertions, CSV export |
| [`texas.py`](../include/pipeline/texas.py) | 142 | Texas Comptroller open-data download and staging |
| [`sql/shortlist.sql`](../include/pipeline/sql/shortlist.sql) | 196 | Matching tiers, age dating, NAICS labelling, shortlist filter |
| [`naics_2017.csv`](../include/pipeline/naics_2017.csv) | 2,197 (1 header + 2,196 rows) | Data asset: Census 2017 NAICS codes and titles |

## Code Elements

### Module: `db` ([db.py](../include/pipeline/db.py))

#### Functions

- `connect() -> duckdb.DuckDBPyConnection`
  - Description: Opens an in-memory DuckDB connection (`duckdb.connect()`), sets `memory_limit` to `8GB` (comment: up to four stage tasks run at once), and executes `NAME_MACROS` so the `norm_name`, `dba_name`, and related macros exist on every connection.
  - Location: [include/pipeline/db.py:10-16](../include/pipeline/db.py#L10-L16)
  - Dependencies: `duckdb.connect`, `NAME_MACROS` from `names.py`

- `copy_to_parquet(con: duckdb.DuckDBPyConnection, query: str, dest: Path, params: list[object] | None = None, fmt: Literal["parquet", "csv"] = "parquet") -> int`
  - Description: Creates `dest.parent` if needed, runs `COPY (<query>) TO '<dest>.part' (FORMAT <fmt>)` with optional bound `params`, reads the row count returned by `COPY`, then atomically renames the `.part` file over `dest` with `os.replace`. On any `BaseException` the `.part` file is removed and the exception re-raised, so a previous `dest` is left untouched. Single quotes in the path are doubled for the SQL literal.
  - Location: [include/pipeline/db.py:19-42](../include/pipeline/db.py#L19-L42)
  - Dependencies: `os.replace`, `Path.unlink`, `Path.mkdir`, `duckdb.DuckDBPyConnection.execute`

#### Classes

None.

### Module: `paths` ([paths.py](../include/pipeline/paths.py))

#### Constants

- `DATA: Path`
  - Description: `Path(__file__).resolve().parents[1] / "data"`, i.e. `include/data`. Comment notes it is `/usr/local/airflow/include/data` inside the containers.
  - Location: [include/pipeline/paths.py:4](../include/pipeline/paths.py#L4)
  - Dependencies: `pathlib.Path`
  - Used as the default `data` argument in `dol`, `ppp`, `shortlist`, and `texas` functions.

### Module: `http` ([http.py](../include/pipeline/http.py))

#### Constants

- `HEADERS: dict[str, str]`
  - Description: Request headers `{"Accept-Encoding": "identity", "User-Agent": "retiring-business-owners/0.1 (local data pipeline)"}`. Identity encoding keeps the GET byte count equal to `Content-Length`.
  - Location: [include/pipeline/http.py:12-15](../include/pipeline/http.py#L12-L15)
  - Imported by: `ppp.py` (`discover`), `texas.py` does not import it (it defines its own `HEADERS` mapping of column headers; see below).

- `TIMEOUT: tuple[int, int]`
  - Description: `(30, 300)`, connect and read timeouts in seconds.
  - Location: [include/pipeline/http.py:16](../include/pipeline/http.py#L16)
  - Imported by: `ppp.py` (`discover`).

#### Functions

- `download_if_changed(url: str, dest: Path) -> bool`
  - Description: Issues a `HEAD` (following redirects), raises on HTTP error, and records `ETag` and `Last-Modified`. Raises `RuntimeError` if neither header is present. If `dest` and `dest.meta.json` exist and the stored ETag and Last-Modified match and the file size equals the stored `bytes`, it logs `unchanged` and returns `False`. Otherwise it streams `GET` into `dest.part` (1 MiB chunks), raises `RuntimeError` if the byte count differs from a non-zero `Content-Length`, renames to `dest`, then writes `dest.meta.json` (url, etag, last_modified, bytes, downloaded_at) through a `.part` file. Returns `True` after a download. No retry loop; the code comment says Airflow retries the task. On any exception the `.part` file is removed and the exception re-raised.
  - Location: [include/pipeline/http.py:19-67](../include/pipeline/http.py#L19-L67)
  - Dependencies: `requests.head`, `requests.get`, `json`, `os.replace`, `datetime.now(UTC)`, `HEADERS`, `TIMEOUT`

#### Classes

None.

### Module: `names` ([names.py](../include/pipeline/names.py))

This module contains a single constant: a raw string of DuckDB `CREATE OR REPLACE MACRO` statements. The macros are DuckDB SQL, not Python functions.

- `NAME_MACROS: str`
  - Description: Executed by `db.connect()`. Defines five scalar macros:
    - `name_unescape(s)`: uppercases, replaces `&AMP;` with `&`, `&#39;` and `&APOS;` with `'`, and removes other HTML entities (`&#?[A-Z0-9]+;`) to a space.
    - `name_clean(s)`: applies `name_unescape`, turns `&` into ` AND `, removes `'`, `’`, `.`, `/`, replaces other non-alphanumerics with spaces, collapses spaces and trims.
    - `name_finish(s)`: strips a leading `THE`, strips trailing entity words (`INC`, `INCORPORATED`, `CORP`, `CORPORATION`, `CO`, `COMPANY`, `LLC`, `L L C`, `PLLC`, `LLP`, `LP`, `L P`, `LTD`, `LIMITED`, `PC`, `P C`, `PA`, `P A`), and returns `NULL` for an empty result.
    - `dba_name(s)`: the cleaned text after the first `DBA` word, passed through `name_finish`.
    - `norm_name(s)`: the cleaned text before any `DBA`, passed through `name_finish`, falling back to `dba_name(s)` when that part is empty.
  - Location: [include/pipeline/names.py:6-27](../include/pipeline/names.py#L6-L27)
  - Dependencies: none (DuckDB built-ins: `replace`, `upper`, `regexp_replace`, `trim`, `nullif`, `regexp_extract`, `coalesce`)
  - Used by: `db.connect()`; `ppp.STAGE_SQL` (`norm_name`, `dba_name`); `texas.SELECT` (`norm_name`); `tests/unit/test_names.py` (per grep).

### Module: `ppp` ([ppp.py](../include/pipeline/ppp.py))

#### Constants

- `PAGE: str = "https://data.sba.gov/dataset/ppp-foia"`
  - Description: The SBA dataset HTML page. The comment says the CKAN API returns 404 for this dataset, so the page HTML is the only listing.
  - Location: [include/pipeline/ppp.py:14](../include/pipeline/ppp.py#L14)

- `LINK: re.Pattern`
  - Description: Regex matching `https://data.sba.gov/sites/default/files/distribution/<path>/public_(150k_plus|up_to_150k_<n>)_<n>.csv`.
  - Location: [include/pipeline/ppp.py:15-18](../include/pipeline/ppp.py#L15-L18)

- `STAGE_SQL: str`
  - Description: `select` over `read_csv(?, header=true, all_varchar=true, union_by_name=true, encoding='latin-1')` filtered to `state = 'TX'`. Produces `loan_number`, `date_approved` (`strptime '%m/%d/%Y'`), `processing_method`, `borrower_name`, `norm_name`, `dba_norm_name`, `address`, `city` (uppercased/trimmed), `state` (`coalesce(BorrowerState, ProjectState)`), `zip5` (`left(BorrowerZip, 5)`), `county`, `loan_status`, `initial_approval_amount`, `current_approval_amount`, `forgiveness_amount` (DOUBLE), `jobs_reported` (INTEGER), `naics`, `business_type`, `business_age_description`, `nonprofit` (`coalesce(NonProfit = 'Y', false)`). Comment: files are Latin-1 and empty fields read as NULL.
  - Location: [include/pipeline/ppp.py:22-47](../include/pipeline/ppp.py#L22-L47)
  - Dependencies: DuckDB `read_csv`, `strptime`, `norm_name`, `dba_name` macros.

#### Functions

- `parse_links(html: str) -> list[str]`
  - Description: Extracts all `LINK` matches from `html`, de-duplicates and sorts them. Raises `ValueError` if fewer than 13 links are found. Strips the `_<n>.csv` suffix to a "stem" and raises `ValueError` if two URLs share a stem (the same file listed in two releases).
  - Location: [include/pipeline/ppp.py:50-58](../include/pipeline/ppp.py#L50-L58)
  - Dependencies: `re.findall` via `LINK`, `re.sub`

- `discover(data: Path = DATA) -> list[str]`
  - Description: `GET`s `PAGE` (raises on HTTP error), parses links with `parse_links`, and deletes any `*.csv` or `*.meta.json` in `data/raw/ppp` whose file name is not in the current list. Stale files are removed because a republished dataset gets new file names and stale files would be counted twice. Returns the URL list.
  - Location: [include/pipeline/ppp.py:61-79](../include/pipeline/ppp.py#L61-L79)
  - Dependencies: `requests.get`, `HEADERS`, `TIMEOUT`, `parse_links`, `DATA`, `logging`
  - Side effect: unlinks files under `data/raw/ppp`.

- `download(url: str, data: Path = DATA) -> bool`
  - Description: Calls `download_if_changed(url, data / "raw" / "ppp" / <file name>)`. Returns `True` if the file was (re)downloaded.
  - Location: [include/pipeline/ppp.py:82-83](../include/pipeline/ppp.py#L82-L83)
  - Dependencies: `http.download_if_changed`

- `stage_tx(data: Path = DATA, min_rows: int = 650_000) -> int`
  - Description: Opens a DuckDB connection, creates temp table `tx` from `STAGE_SQL` over `data/raw/ppp/*.csv`, counts loans with a usable ZIP and name (`zip5 is not null and norm_name is not null`), the dropped count, and distinct `norm_name|zip5` businesses. Asserts `loans >= min_rows` and `dropped < 1000`. Then `copy_to_parquet` writes the usable rows to `data/stage/ppp_tx.parquet`. Returns the row count. The docstring notes malformed dates or numbers fail the read, so the previous file survives.
  - Location: [include/pipeline/ppp.py:86-110](../include/pipeline/ppp.py#L86-L110)
  - Dependencies: `db.connect`, `db.copy_to_parquet`, `STAGE_SQL`, `DATA`

#### Classes

None.

### Module: `texas` ([texas.py](../include/pipeline/texas.py))

#### Constants

- `DATASETS: dict[str, str]`
  - Description: `{"tx_franchise": "9cir-efmm", "tx_sales_outlets": "jrea-zgmq"}`, Socrata dataset IDs.
  - Location: [include/pipeline/texas.py:11](../include/pipeline/texas.py#L11)

- `URL: str`
  - Description: `"https://data.texas.gov/api/views/{id}/rows.csv?accessType=DOWNLOAD"`, formatted with a dataset ID.
  - Location: [include/pipeline/texas.py:12](../include/pipeline/texas.py#L12)

- `HEADERS: dict[str, tuple[str, list[str]]]`
  - Description: Per dataset, the exact header line the export is expected to serve (stray spaces included) and the column names to assign in that order. Keys: `tx_franchise` (18 columns, from `taxpayer_number` to `naics`) and `tx_sales_outlets` (19 columns, from `taxpayer_number` to `first_sales_date`). Not the same name as `http.HEADERS`.
  - Location: [include/pipeline/texas.py:17-44](../include/pipeline/texas.py#L17-L44)

- `DEFAULT_MIN_ROWS: dict[str, int]`
  - Description: `{"tx_franchise": 3_000_000, "tx_sales_outlets": 800_000}`, the default row floor for each dataset.
  - Location: [include/pipeline/texas.py:46](../include/pipeline/texas.py#L46)

- `EIN: str`
  - Description: SQL `CASE` expression yielding the nine digits after a leading `1` in `taxpayer_number` (else `NULL`). Imported by `tests/fixtures/shortlist/make_fixtures.py`.
  - Location: [include/pipeline/texas.py:48](../include/pipeline/texas.py#L48)

- `SELECT: dict[str, str]`
  - Description: Per-dataset SQL `SELECT` statements over the temp table `raw`.
    - `tx_franchise`: dates parsed with `mdy`; `ein` from `EIN`; `norm_name` from `taxpayer_name`; `city` uppercased; `zip5`. Keeps one row per `taxpayer_number` using `qualify row_number() ... order by (sos_status = 'A') desc, sos_status_date desc nulls last, charter_date, record_type, exempt_reason`.
    - `tx_sales_outlets`: `ein`, `norm_taxpayer_name`, `norm_outlet_name`, `outlet_zip5`, and `permit_issue_date` / `first_sales_date` via `mdy`. No dedup.
  - Location: [include/pipeline/texas.py:56-86](../include/pipeline/texas.py#L56-L86)
  - Dependencies: `EIN`, `mdy`, `norm_name` macro, DuckDB `qualify`

#### Functions

- `mdy(col: str) -> str`
  - Description: Returns the SQL fragment `strptime(<col>, '%m/%d/%Y')::DATE`. Strict, so a malformed date fails the stage.
  - Location: [include/pipeline/texas.py:51-53](../include/pipeline/texas.py#L51-L53)
  - Dependencies: none

- `download(name: str, data: Path = DATA) -> bool`
  - Description: Builds the URL from `DATASETS[name]` and calls `download_if_changed` into `data/raw/tx/<name>.csv`. The export streams without `Content-Length`, so the byte-count check cannot run (comment in code).
  - Location: [include/pipeline/texas.py:89-93](../include/pipeline/texas.py#L89-L93)
  - Dependencies: `http.download_if_changed`, `URL`, `DATASETS`

- `stage(name: str, data: Path = DATA, min_rows: int | None = None) -> int`
  - Description: Reads the first line of `data/raw/tx/<name>.csv` and raises `ValueError` if it differs from the expected header. Creates temp table `raw` by `read_csv(..., all_varchar=true, names=<columns>)`, trimming tab, CR, LF and whitespace from every column and turning empty strings into `NULL`. Builds temp table `staged` from `SELECT[name]`. Asserts row count `>= floor` (`min_rows` or `DEFAULT_MIN_ROWS[name]`) and that every taxpayer number beginning with `1` has a 9-digit EIN. For `tx_franchise` also asserts: unique taxpayer numbers, `0 < dropped < 1000`, and Texas Instruments (`17502899705`) has charter date `1938-12-31`. Then writes `data/stage/<name>.parquet` through `copy_to_parquet` and returns the row count.
  - Location: [include/pipeline/texas.py:96-142](../include/pipeline/texas.py#L96-L142)
  - Dependencies: `db.connect`, `db.copy_to_parquet`, `HEADERS`, `DEFAULT_MIN_ROWS`, `SELECT`, `date` (from `datetime`)

#### Classes

None.

### Module: `dol` ([dol.py](../include/pipeline/dol.py))

#### Constants

- `YEARS: tuple[int, ...] = (2022, 2023, 2024, 2025)`
  - Description: Form years to download. A `shortcut:` comment says to add the next year by hand when DOL publishes its Latest zip.
  - Location: [include/pipeline/dol.py:15](../include/pipeline/dol.py#L15)
  - Used by: `dags/tx_retiring_owners.py:65` (per grep).

- `FORMS: tuple[str, str] = ("F_5500", "F_5500_SF")`
  - Location: [include/pipeline/dol.py:16](../include/pipeline/dol.py#L16)
  - Used by: `dags/tx_retiring_owners.py:65` (per grep).

- `FORM_SQL: str`
  - Description: Template `select` over `read_csv(?, header=true, all_varchar=true, union_by_name=true, filename=true)` that maps form-specific column names to one shape. Placeholders: `ein, name, dba, addr, city, state, zip, phone, business, plan, eff, year_begin, partcp, act_partcp, codes, spons_signed, spons_manual, same, admin_signed, admin_manual, form`. `sponsor_signer` is `coalesce(spons_signed, spons_manual)`. `admin_signer` is kept only when `same = '1'` (the administrator is the sponsor). Adds the literal `form` and `filename`.
  - Location: [include/pipeline/dol.py:53-67](../include/pipeline/dol.py#L53-L67)

- `SF: str`
  - Description: `FORM_SQL` formatted for the Form 5500-SF columns (`SF_SPONS_EIN`, `SF_SPONSOR_NAME`, and so on), with form literal `5500-SF`.
  - Location: [include/pipeline/dol.py:68-78](../include/pipeline/dol.py#L68-L78)

- `FULL: str`
  - Description: `FORM_SQL` formatted for the Form 5500 columns (`SPONS_DFE_EIN`, `SPONSOR_DFE_NAME`, and so on), with form literal `5500`.
  - Location: [include/pipeline/dol.py:79-90](../include/pipeline/dol.py#L79-L90)

- `STAGE_SQL: str` (f-string)
  - Description: `with sf as (SF), full_5500 as (FULL), filings as (...)`. `filings` normalizes names, takes `left(zip, 5)`, casts dates and integers, derives `signer_name` and `signer_source` (`'sponsor'` or `'admin_is_sponsor'`), extracts `form_year` from the file name (`_(\d{4})_latest\.csv$`), and sets `db` when `pension_codes` matches `1[A-I]`. Keeps only `state = 'TX'` rows with a 9-digit EIN. The final select adds `plan_count`, `earliest_plan_eff_date`, `ever_defined_benefit` (window over EIN) and `is_defined_benefit`, then keeps one row per EIN with `qualify row_number() ... order by date_received desc, plan_year_begin desc, ack_id desc = 1`.
  - Location: [include/pipeline/dol.py:95-128](../include/pipeline/dol.py#L95-L128)
  - Dependencies: `SF`, `FULL` (both embedded as subqueries)

#### Functions

- `url(form: str, year: int) -> str`
  - Description: Returns `https://askebsa.dol.gov/FOIA%20Files/<year>/Latest/<form>_<year>_Latest.zip`. A code comment says the host 301-redirects to `www.askebsa.dol.gov`, and the download helper follows redirects.
  - Location: [include/pipeline/dol.py:19-22](../include/pipeline/dol.py#L19-L22)
  - Dependencies: none

- `download(url: str, data: Path = DATA) -> bool`
  - Description: Calls `download_if_changed(url, data / "raw" / "dol" / <zip file name>)`. Note the parameter name `url` shadows the module-level function `url`, inside this function only.
  - Location: [include/pipeline/dol.py:25-26](../include/pipeline/dol.py#L25-L26)
  - Dependencies: `http.download_if_changed`

- `extract(zip_path: Path) -> Path`
  - Description: Opens the zip, requires exactly one member whose name ends in `.csv` (case-insensitive; otherwise `ValueError`), and writes it next to the zip. Returns early if the CSV exists and is newer than the zip. Otherwise copies in 1 MiB chunks to a `.part` file, renames it, and logs `extracted`. Removes the `.part` file on any exception and re-raises.
  - Location: [include/pipeline/dol.py:29-47](../include/pipeline/dol.py#L29-L47)
  - Dependencies: `zipfile.ZipFile`, `shutil.copyfileobj`, `os.replace`, `logging`

- `stage(data: Path = DATA, min_rows: int = 46_000) -> int`
  - Description: Extracts every `*.zip` under `data/raw/dol`, then creates temp table `sponsors` from `STAGE_SQL` with the two glob patterns `f_5500_sf_20??_latest.csv` and `f_5500_20??_latest.csv` (the second is not matched by the first). Queries counts: rows, distinct EINs, rows with a signer, rows with `ever_defined_benefit`, and rows for Texas Instruments EIN `750289970`. Asserts `rows >= min_rows`, `unique == rows`, and `ti == 1`, all before writing. Writes `data/stage/dol_5500_tx.parquet`, logs `dol_stage`, and returns `rows` as `int`.
  - Location: [include/pipeline/dol.py:131-156](../include/pipeline/dol.py#L131-L156)
  - Dependencies: `extract`, `db.connect`, `db.copy_to_parquet`, `STAGE_SQL`

#### Classes

None.

### Module: `shortlist` ([shortlist.py](../include/pipeline/shortlist.py))

#### Constants

- `MIN_YEARS: int = 30`
  - Description: Minimum years in business for a shortlisted business. Passed to SQL as `min_years` and used in `qc`.
  - Location: [include/pipeline/shortlist.py:10](../include/pipeline/shortlist.py#L10)

- `EXCLUDED_NAICS: list[str] = ["813", "814", "92"]`
  - Description: NAICS prefixes excluded from the shortlist: `813` (religious, grantmaking, civic, professional and labor organizations), `814` (private households), `92` (public administration).
  - Location: [include/pipeline/shortlist.py:14-18](../include/pipeline/shortlist.py#L14-L18)

- `SQL: Path`
  - Description: `include/pipeline/sql/shortlist.sql`.
  - Location: [include/pipeline/shortlist.py:20](../include/pipeline/shortlist.py#L20)

- `NAICS_TITLES: Path`
  - Description: `include/pipeline/naics_2017.csv`. The comment gives the Census source URL `https://www.census.gov/naics/2017NAICS/2-6%20digit_2017_Codes.xlsx` (documented, not fetched by this code).
  - Location: [include/pipeline/shortlist.py:21-23](../include/pipeline/shortlist.py#L21-L23)

- `ORDER: str`
  - Description: SQL `order by years_in_business desc, ever_defined_benefit desc, jobs_reported desc, business_name, taxpayer_number`. Used by `export`.
  - Location: [include/pipeline/shortlist.py:24-27](../include/pipeline/shortlist.py#L24-L27)

- `INDIVIDUALS: tuple[str, str, str]`
  - Description: `("Sole Proprietorship", "Self-Employed Individuals", "Independent Contractors")`. Business types excluded from the match-share denominator in `qc`.
  - Location: [include/pipeline/shortlist.py:29-33](../include/pipeline/shortlist.py#L29-L33)

#### Functions

- `partition(data: Path, run_date: str) -> Path`
  - Description: Returns `data/marts/shortlist/run_date=<run_date>/shortlist.parquet`.
  - Location: [include/pipeline/shortlist.py:36-37](../include/pipeline/shortlist.py#L36-L37)
  - Dependencies: none

- `build(data: Path = DATA, run_date: date | None = None) -> dict[str, object]`
  - Description: Defaults `run_date` to today in UTC. Sets DuckDB variables `ppp`, `franchise`, `outlets`, `dol` (stage paths), `run_date`, `min_years`, `excluded_naics`, `naics_titles`. Executes `sql/shortlist.sql` in full. Writes `data/marts/matches.parquet` (all PPP businesses) and the `shortlist` table to `partition(data, run_date)`. Counts `businesses`, `matched`, and `tier_1` through `tier_4` from `matches`, logs `build`, and returns a dict with keys `run_date`, `ppp_businesses`, `matched`, `tier_1`..`tier_4`, `shortlisted`.
  - Location: [include/pipeline/shortlist.py:40-75](../include/pipeline/shortlist.py#L40-L75)
  - Dependencies: `db.connect`, `db.copy_to_parquet`, `sql/shortlist.sql`, `MIN_YEARS`, `EXCLUDED_NAICS`, `NAICS_TITLES`

- `qc(run_date: str, data: Path = DATA, min_match_share: float = 0.30, min_rows: int = 100) -> None`
  - Description: Asserts, against the written files, that: matched share of eligible PPP businesses (excluding `INDIVIDUALS` business types) is `>= min_match_share`; the shortlist has `>= min_rows` rows; taxpayer numbers are unique; no row is younger than `MIN_YEARS`; no row lacks `age_source`; and no row is nonprofit or charged off (checked by joining the shortlist to `matches.parquet` on `taxpayer_number, zip5, business_name`). Logs `qc`. Returns `None`.
  - Location: [include/pipeline/shortlist.py:78-118](../include/pipeline/shortlist.py#L78-L118)
  - Dependencies: `db.connect`, `partition`, `MIN_YEARS`, `INDIVIDUALS`

- `export(run_date: str, data: Path = DATA) -> dict[str, int]`
  - Description: Finds earlier partitions with a `_exported` marker. Raises `ValueError` if a later one than `run_date` is already exported. Writes `data/marts/shortlist_latest.csv` (the full partition, ordered by `ORDER`). Chooses the baseline as the latest earlier exported partition: writes `data/marts/shortlist_new_since_previous.csv` with rows whose `taxpayer_number` is not in that baseline (anti-join), or every row when no earlier export exists. Touches `_exported` in the current partition. Returns `{"latest": <rows>, "new_since_previous": <rows>}`.
  - Location: [include/pipeline/shortlist.py:121-156](../include/pipeline/shortlist.py#L121-L156)
  - Dependencies: `db.connect`, `db.copy_to_parquet`, `partition`, `ORDER`

#### Classes

None.

### SQL: `sql/shortlist.sql` ([shortlist.sql](../include/pipeline/sql/shortlist.sql))

Four DuckDB statements, run by `shortlist.build`. Variables come from `SET VARIABLE` (see `build`).

- **Temp table `matches`** ([lines 6-152](../include/pipeline/sql/shortlist.sql#L6-L152))
  - `ppp_biz`: one row per PPP `(norm_name, zip5)` key. Picks business name (longest), address, city, county, NAICS (`mode`), business type, and similar fields by latest loan. Sums `current_approval_amount` as `DECIMAL(18,2)`. Derives `street_no` from the address.
  - `fr`: Texas franchise rows with `street_no`.
  - `outlets`, `dol`: sales outlet and 5500 sponsor inputs.
  - `t1`: name and ZIP equal to a franchise row, accepted only if exactly one taxpayer number qualifies.
  - `t2`: name and city equal, unique taxpayer only.
  - `t3`: same ZIP and street number, Jaro-Winkler similarity `>= 0.92`, unique taxpayer only.
  - `t4`: outlet name equal to the PPP name or to the PPP DBA name, same ZIP, unique taxpayer only.
  - `best`: the best tier per PPP key, ordered by `match_tier`, then similarity descending, then outlet name.
  - `outlet_agg`: per taxpayer, EIN, first sales date, and mode of outlet NAICS.
  - `age`: per taxpayer, `oldest` is the least of charter date, first sales date and 5500 plan effective date with `1900-01-01` placeholders removed. `years_in_business = date_sub('year', oldest, run_date)`. `age_source` is `charter`, `first_sales`, or `plan`. Joins signer, phone, plan and pension fields from `dol`.
  - Final select: every PPP business (matched or not), with `dba_name`, `naics_final` (coalesced from PPP, franchise, outlets and DOL), `in_franchise`, and the age and plan fields.
- **Temp table `naics`** ([lines 154-156](../include/pipeline/sql/shortlist.sql#L154-L156)): reads `naics_titles` as CSV (`all_varchar`) into `code, title`.
- **Temp macro `naics_sector(c)`** ([lines 158-162](../include/pipeline/sql/shortlist.sql#L158-L162)): maps the first two digits to a sector code. `31`, `32`, `33` to `31-33`; `44`, `45` to `44-45`; `48`, `49` to `48-49`; otherwise the first two digits.
- **Temp table `shortlist`** ([lines 164-196](../include/pipeline/sql/shortlist.sql#L164-L196)): joins `matches` to `naics` on sector, 4-digit group, 3-digit, 5-digit and 6-digit codes to produce `sector`, `industry_group`, and `naics_title` (longest known prefix). Filters: `naics_final` does not start with an excluded prefix; `years_in_business >= min_years`; not nonprofit; not charged off; and either `right_to_transact = 'A'` or (not in franchise and `org_type` in `S`, `IS`, `PB`, `PI`). Keeps one row per `taxpayer_number`, ordered by `ppp_total_approved desc, norm_name, zip5`. Adds `run_date`.

### Data asset: `naics_2017.csv` ([naics_2017.csv](../include/pipeline/naics_2017.csv))

- Header: `code,title`. 2,196 data rows, no duplicate codes, every row has exactly two fields.
- Code lengths: 17 two-digit, 99 three-digit, 311 four-digit, 712 five-digit, 1,057 six-digit.
- Read with `read_csv(..., all_varchar=true)` by `sql/shortlist.sql`. Not parsed by Python code.
- Structure was checked with a CSV parser; individual titles were not reviewed line by line.

### Package markers

- [`include/__init__.py`](../include/__init__.py): empty (0 lines).
- [`include/pipeline/__init__.py`](../include/pipeline/__init__.py): empty (0 lines).

## Dependencies

### Internal Dependencies

- `db.py` imports `names.NAME_MACROS`.
- `dol.py` imports `db` (`connect`, `copy_to_parquet`), `http` (`download_if_changed`), `paths` (`DATA`).
- `ppp.py` imports `db` (`connect`, `copy_to_parquet`), `http` (`HEADERS`, `TIMEOUT`, `download_if_changed`), `paths` (`DATA`).
- `texas.py` imports `db` (`connect`, `copy_to_parquet`), `http` (`download_if_changed`), `paths` (`DATA`).
- `shortlist.py` imports `db` (`connect`, `copy_to_parquet`), `paths` (`DATA`). It does not import `dol`, `ppp` or `texas`; it reads their Parquet outputs by path.
- `http.py`, `paths.py`, `names.py`: no internal imports.
- `sql/shortlist.sql` and `naics_2017.csv` are read by path from `shortlist.py`.
- Consumers outside the directory (per grep): `dags/tx_retiring_owners.py` imports `dol`, `ppp`, `shortlist`, `texas`. `tests/unit/` imports `dol`, `texas`, `ppp`, `shortlist`, `db`, `http`, `names` indirectly. `tests/fixtures/shortlist/make_fixtures.py` imports `db.connect` and `texas.EIN`.

### External Dependencies

Python libraries:

- `duckdb`: in-memory connection, `read_csv`, `COPY ... TO`, macros, `qualify`, `list_filter`, `jaro_winkler_similarity` (`db.py`, `dol.py`, `ppp.py`, `shortlist.py`, `texas.py`).
- `requests`: `head`, `get` (`http.py`, `ppp.py`).

Python standard library: `logging`, `os`, `shutil`, `zipfile`, `pathlib`, `typing.Literal`, `json`, `re`, `datetime` (`UTC`, `date`, `datetime`). `datetime.UTC` requires Python 3.11 or later.

External HTTP data sources (URLs found in code):

| Source | URL pattern in code | Used by | Notes |
| --- | --- | --- | --- |
| SBA PPP FOIA listing page | `https://data.sba.gov/dataset/ppp-foia` | `ppp.PAGE`, `ppp.discover` | HTML scraped for CSV links. CKAN API comment says it returns 404. |
| SBA PPP CSV files | `https://data.sba.gov/sites/default/files/distribution/<...>/public_(150k_plus|up_to_150k_<n>)_<n>.csv` | `ppp.LINK` regex, `ppp.download` | Links discovered from the listing page. |
| DOL Form 5500 FOIA zips | `https://askebsa.dol.gov/FOIA%20Files/{year}/Latest/{form}_{year}_Latest.zip` | `dol.url`, `dol.download` | `form` is `F_5500` or `F_5500_SF`. Comment says host 301-redirects to `www.askebsa.dol.gov`. |
| Texas Comptroller franchise export | `https://data.texas.gov/api/views/9cir-efmm/rows.csv?accessType=DOWNLOAD` | `texas.URL`, `texas.download` | Socrata dataset `9cir-efmm`. Streamed without `Content-Length`. |
| Texas Comptroller sales outlets export | `https://data.texas.gov/api/views/jrea-zgmq/rows.csv?accessType=DOWNLOAD` | `texas.URL`, `texas.download` | Socrata dataset `jrea-zgmq`. |
| Census NAICS 2017 code list | `https://www.census.gov/naics/2017NAICS/2-6%20digit_2017_Codes.xlsx` | Comment in `shortlist.py` only | Source of `naics_2017.csv`. Not fetched by this code. |

Local filesystem inputs and outputs (under `include/data/`, from `paths.DATA`):

- Raw: `raw/ppp/*.csv`, `raw/ppp/*.meta.json`, `raw/dol/*.zip`, `raw/dol/*.csv`, `raw/dol/*.meta.json`, `raw/tx/<name>.csv`, `raw/tx/<name>.csv.meta.json`.
- Stage: `stage/ppp_tx.parquet`, `stage/tx_franchise.parquet`, `stage/tx_sales_outlets.parquet`, `stage/dol_5500_tx.parquet`.
- Marts: `marts/matches.parquet`, `marts/shortlist/run_date=<date>/shortlist.parquet`, `marts/shortlist/run_date=<date>/_exported`, `marts/shortlist_latest.csv`, `marts/shortlist_new_since_previous.csv`.

## Relationships

Module dependency graph for `include/pipeline` (solid arrows are Python imports; dashed arrows are file reads by path; the DAG is outside this directory and shown for context):

```mermaid
---
title: Module Relationships for include/pipeline
---
flowchart TB
    subgraph External
        duckdb[(duckdb)]
        requests[(requests)]
        sba[SBA PPP pages and CSVs]
        dol_web[DOL 5500 FOIA zips]
        tx_web[Texas Comptroller CSV exports]
    end

    subgraph pipeline
        paths[paths.py<br/>DATA]
        http[http.py<br/>download_if_changed]
        names[names.py<br/>NAME_MACROS]
        db[db.py<br/>connect, copy_to_parquet]
        ppp[ppp.py<br/>discover, download, stage_tx]
        dol[dol.py<br/>url, download, extract, stage]
        texas[texas.py<br/>download, stage]
        shortlist[shortlist.py<br/>build, qc, export]
        sql[(sql/shortlist.sql)]
        naics[(naics_2017.csv)]
    end

    dag[dags/tx_retiring_owners.py]

    dag --> dol
    dag --> ppp
    dag --> texas
    dag --> shortlist

    db --> names
    http --> requests
    db --> duckdb
    ppp --> http
    ppp --> db
    ppp --> paths
    dol --> http
    dol --> db
    dol --> paths
    texas --> http
    texas --> db
    texas --> paths
    shortlist --> db
    shortlist --> paths
    shortlist -.reads.-> sql
    shortlist -.reads.-> naics

    ppp -.HTTPS.-> sba
    dol -.HTTPS.-> dol_web
    texas -.HTTPS.-> tx_web

    ppp -.writes stage/ppp_tx.parquet.-> shortlist
    dol -.writes stage/dol_5500_tx.parquet.-> shortlist
    texas -.writes stage/tx_*.parquet.-> shortlist
```

## Notes

- **Python version**: `datetime.UTC` needs Python 3.11 or later. The committed `__pycache__` files are for CPython 3.14.
- **Validation pattern**: each `stage` function writes its Parquet file only after assertions pass, and `copy_to_parquet` writes through a `.part` file, so a bad read does not replace the previous output.
- **Side effects**: `ppp.discover` deletes stale raw files; `dol.extract` writes CSVs next to the zips; `shortlist.export` writes an `_exported` marker in the partition.
- **Hard-coded values**: `dol.YEARS` and `dol.FORMS` are edited by hand (shortcut comment in `dol.py`). `texas.HEADERS` pins the exact export header line; a change stops the stage. `shortlist.EXCLUDED_NAICS`, `MIN_YEARS` and `INDIVIDUALS` are constants.
- **Known limits in code comments**: `http.download_if_changed` has no resume and no retry loop (`shortcut:` comment; the SBA server may support `Accept-Ranges`). The Texas export has no `Content-Length`, so the byte-count check does not apply.
- **Test coverage pointers** (per grep, not analyzed here): `tests/unit/test_dol.py`, `test_texas.py`, `test_names.py`, `test_db.py`, `test_ppp.py`, `test_http.py`, `test_shortlist.py`.
- **Not documented in detail**: the body of `naics_2017.csv` was validated programmatically (row count, two fields per row, no duplicate codes) rather than read line by line.
