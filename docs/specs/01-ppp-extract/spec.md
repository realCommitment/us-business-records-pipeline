# 01-ppp-extract

Daily tasks that download the SBA PPP loan files and stage the Texas loans as one Parquet file.

Bound by `docs/specs/00-product/spec.md` (decisions 4 to 7 and 13) and `docs/data-sources.md` section 1. It builds on what the skeleton provides: `DATA` in `include/pipeline/paths.py`, `connect` and `copy_to_parquet` in `include/pipeline/db.py`, and `scripts/smoke.sh`.

## Goal

The DAG `tx_retiring_owners` finds the 13 PPP CSV files on the SBA FOIA page and downloads each one only when its `ETag` or `Last-Modified` changed. It then rebuilds `include/data/stage/ppp_tx.parquet`: every Texas loan, typed, with a normalized business name and a five-digit ZIP. The first run moves about 4.5 GB. Every later run finishes its downloads in seconds. This spec also introduces the download helper and the name normalization that specs 02 to 04 reuse.

## What the user can do afterwards

```
scripts/smoke.sh 14400
uv run python -c "import duckdb; print(duckdb.sql(\"select count(*) loans, count(distinct norm_name || '|' || zip5) businesses, min(date_approved), max(date_approved) from 'include/data/stage/ppp_tx.parquet'\"))"
```

Running `scripts/smoke.sh` a second time logs `unchanged` for every download, and the stage rebuilds the same counts.

## Anti-goals

- No merging of first-draw and second-draw loans into one business. Spec 04 does that.
- No NAICS or size filter. The stage keeps every Texas loan.
- No resumable downloads. A dropped connection fails the task, and Airflow's retry downloads that file again. Leave the comment `# shortcut: no resume; the SBA server sends Accept-Ranges if a 450 MB restart ever hurts`.
- No hard-coded file list. The page is scraped, and the task fails if it finds fewer than 13 links.

## Files and interfaces

- `include/pipeline/http.py` defines `download_if_changed(url: str, dest: Path) -> bool`. It works in four steps:
  1. HEAD the URL, following redirects, with `Accept-Encoding: identity` and a `User-Agent` that names this project. The GET sends the same headers, so the byte count is exact.
  2. Compare the HEAD's `ETag` and `Last-Modified` with the sidecar file `<dest name>.meta.json`. If `dest` exists and both values match, log `unchanged <name>` and return `False`.
  3. Otherwise stream the GET in 1 MiB chunks to `<dest name>.part`. When `Content-Length` is non-zero, check the byte count against it.
  4. `os.replace` the file onto `dest` and write the sidecar with `url`, `etag`, `last_modified`, `bytes` and `downloaded_at`. Log `downloaded <name> <bytes>` and return `True`.

  It raises on a non-2xx status, on a size mismatch, or when the response has neither `ETag` nor `Last-Modified`, and it removes the `.part` file when it does. Timeouts are 30 s to connect and 300 s to read. There is no retry loop in the code, because Airflow retries the task.
- `include/pipeline/names.py` defines `NAME_MACROS: str`, the DuckDB SQL for two macros. `connect()` in `db.py` now runs it, so every connection has both macros.
  - `norm_name(s)` applies these steps in order:
    1. Uppercase.
    2. Replace `&` with ` AND `.
    3. Delete `'`, `’`, `.` and `/`.
    4. Replace every other character outside `A-Z0-9` with a space.
    5. Collapse repeated spaces and trim.
    6. Keep only the part before the first whole word `DBA`.
    7. Drop a leading `THE `.
    8. Drop trailing entity words. Use one anchored regex with `+`, applied to `' ' || s`, then trim. The words are `INC`, `INCORPORATED`, `CORP`, `CORPORATION`, `CO`, `COMPANY`, `LLC`, `L L C`, `PLLC`, `LLP`, `LP`, `L P`, `LTD`, `LIMITED`, `PC`, `P C`, `PA` and `P A`.
    9. Return NULL for an empty result.
  - `dba_name(s)` applies the same steps to the part after the first `DBA`. It returns NULL when there is no `DBA`.
  - These exact values are the unit test:

    | Input | `norm_name` | `dba_name` |
    | --- | --- | --- |
    | `SUMTER COATINGS, INC.` | `SUMTER COATINGS` | NULL |
    | `Texas Instruments Incorporated` | `TEXAS INSTRUMENTS` | NULL |
    | `SOUTHWEST AIRLINES CO.` | `SOUTHWEST AIRLINES` | NULL |
    | `The Smith Co., L.L.C.` | `SMITH` | NULL |
    | `J & B ELECTRIC CO` | `J AND B ELECTRIC` | NULL |
    | `SMITH-JONES PLUMBING, LLC` | `SMITH JONES PLUMBING` | NULL |
    | `BOB'S A/C INC D/B/A COOL AIR` | `BOBS AC` | `COOL AIR` |
    | `COMPANY STORE INC` | `COMPANY STORE` | NULL |
    | `INC` | NULL | NULL |
    | empty string | NULL | NULL |
- `include/pipeline/ppp.py`:
  - `PAGE = "https://data.sba.gov/dataset/ppp-foia"`. The CKAN API returns 404 for this dataset, so the page HTML is the only listing.
  - `parse_links(html: str) -> list[str]` returns every unique match of `https://data\.sba\.gov/sites/default/files/distribution/[^"' ]+/public_(?:150k_plus|up_to_150k_\d+)_\d+\.csv`, sorted. It raises if there are fewer than 13.
  - `discover(data: Path = DATA) -> list[str]` GETs `PAGE` and calls `parse_links`. It then deletes every `*.csv` and `*.meta.json` in `data/raw/ppp/` that is not in the list, because a republished dataset gets new file names and stale files would be counted twice. It returns the URLs.
  - `download(url: str, data: Path = DATA) -> bool` calls `download_if_changed(url, data / "raw/ppp" / <file name>)`.
  - `stage_tx(data: Path = DATA, min_rows: int = 500_000) -> int` runs one `copy_to_parquet` over `read_csv(data/raw/ppp/*.csv, header=true, all_varchar=true, union_by_name=true)` into `data/stage/ppp_tx.parquet`.
    - If DuckDB rejects the encoding or a row, the task fails. Fix it with the narrowest option that works, for example `encoding='latin-1'`, and record why in the implementation notes. Never use `ignore_errors`.
    - Output columns:
      - `loan_number` (BIGINT)
      - `date_approved` (DATE, parsed from `MM/DD/YYYY`)
      - `processing_method`: `PPP` for a first draw, `PPS` for a second
      - `borrower_name`, `norm_name` and `dba_norm_name`
      - `address`
      - `city`, uppercased and trimmed
      - `state`, as `coalesce(nullif(BorrowerState, ''), ProjectState)`
      - `zip5`, as `left(BorrowerZip, 5)`
      - `county`, from `ProjectCountyName`
      - `loan_status`
      - `initial_approval_amount`, `current_approval_amount` and `forgiveness_amount` (DOUBLE)
      - `jobs_reported` (INTEGER)
      - `naics`, as `nullif(NAICSCode, '')`
      - `business_type`
      - `business_age_description`
      - `nonprofit` (BOOLEAN, `NonProfit = 'Y'`)
    - It keeps only rows where `state = 'TX'`.
    - After writing it asserts that there are at least `min_rows` rows, that no row lacks `zip5` or `norm_name`, and that no row has a non-empty `DateApproved` with a NULL `date_approved`.
    - It logs one line with the loan count and the distinct `(norm_name, zip5)` count, and returns the loan count.
- `dags/tx_retiring_owners.py`: delete the skeleton's `smoke` task and its `_smoke.parquet`. Add three tasks: `ppp_discover`, then `ppp_download.expand(url=...)`, then `ppp_stage`. `ppp_download` gets `max_active_tis_per_dag=3` and `execution_timeout=timedelta(hours=2)`. `ppp_stage` gets an `execution_timeout` of 30 minutes.
- `tests/fixtures/ppp/` holds two CSVs with the real 53-column header and six rows between them:
  - a Texas corporation
  - a Texas sole proprietorship with `D/B/A` in its name
  - a row with a blank `BorrowerState` and `ProjectState` TX
  - a row from another state
  - a quoted name containing a comma
  - a row with a blank `NAICSCode` and a ZIP+4
- `tests/fixtures/ppp/page.html`: a trimmed copy of the real dataset page with its 13 links.
- `tests/unit/test_names.py`: the table above, matched exactly.
- `tests/unit/test_http.py` runs `download_if_changed` against a stdlib `http.server` on 127.0.0.1 in a thread; the socket guard allows loopback. It checks four cases:
  - The first call downloads the file.
  - A second call with an unchanged `ETag` returns `False` and sends no GET.
  - A changed `ETag` downloads the file again.
  - A truncated body raises and leaves the previous file intact.
- `tests/unit/test_ppp.py`:
  - `stage_tx` on the fixtures with `min_rows=1` returns exactly 4 rows. Each has the expected `norm_name`, `zip5`, `state`, `naics` and `nonprofit` for its loan number.
  - `parse_links` on `page.html` returns the 13 URLs in order, and raises on a page with 2 links.

## End-to-end verification

1. With the stack up, run `scripts/smoke.sh 14400` and paste its output. The first run makes 13 downloads of 270 to 450 MB each, three at a time.
2. `ls -l include/data/raw/ppp/` shows 13 CSVs and 13 `.meta.json` files, and `du -sh include/data/raw/ppp` shows about 4.5 GB.
3. Run the DuckDB count above and paste its output. Expect roughly 0.7 to 1.3 million Texas loans. Record the real counts, and set the default `min_rows` to about 70% of the observed count, in the code and in `implementation-notes.md`.
4. Run `scripts/smoke.sh` again. The `ppp_download` task logs show `unchanged` for all 13 files, and the run is green.
5. `mise run check` passes.
