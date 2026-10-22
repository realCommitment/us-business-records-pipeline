# 12-registries-ia-va

Adds the Iowa and Virginia business registries. Both are free but need their own change detection, and Virginia's corporations come as an Excel file.

Bound by `docs/specs/00-product/spec.md`: decisions 4 to 6, 9, 11 to 13 and 17. Also bound by `docs/data-sources.md` sections 10.4 (VA) and 10.6 (IA). It uses spec 06's contract with module-level `download` and `read`, and spec 09's `include/pipeline/zips.py`.

## Goal

| Module | Source | Rows | Sentinel |
| --- | --- | --- | --- |
| `states/iowa.py` | "Active Iowa Business Entities", data.iowa.gov dataset 554, a zipped CSV. CC BY 4.0. | 348,270 active entities (portal page) | `019862` HY-VEE, INC., 1938-01-03 |
| `states/virginia.py` | State Corporation Commission files on data.virginia.gov: `corp.xlsx`, `llc.csv`, `gp.xlsx`, `officer.csv` | 465,855 corporations, with duplicates; LLCs and partnerships counted on the first run | `00164871` UNIVERSAL CORPORATION, 1918-01-25 |

Iowa's file sends neither `ETag` nor `Last-Modified`. Its module downloads the file in full and keeps the old copy when the SHA-256 matches. Virginia's links redirect to S3 URLs that reject HEAD, so its module reads the validators with a one-byte ranged GET.

Virginia's files are a snapshot: the corporations file is dated 2024-11-14. Its `as_of` carries that date, so the 24-month open-status window ages its "good standing" signal correctly: it stops counting after 2026-11-14.

Every entity in both states becomes a registry business (product decision 9, step 1).

Together the two states have 392,804 PPP loans. After this spec the free registries cover 3,847,441 of 11,468,210 PPP loans (33.5%).

## What the user can do afterwards

```
scripts/smoke.sh 7200
uv run python -c "import duckdb; print(duckdb.sql(\"select state, open_status, count(*) businesses, count(*) filter (where list_contains(sources, 'ppp') and registry_id is not null) ppp_with_registry, count(formed_date) with_formed, count(registry_officers) with_officers from 'include/data/marts/businesses.parquet' where state in ('IA', 'VA') group by all order by all\"))"
```

## Anti-goals

- No contract change for content hashing or ranged GETs. Each lives in its state's module.
- No Virginia merger, amendment, lien, reserved-name or business-trust files.
- No attempt to refresh Virginia's statuses from elsewhere. Staleness is recorded, not fixed.
- No `ignore_errors`.

## Files and interfaces

- **`states/iowa.py`**
  - `URL = "https://data.iowa.gov/api/dataset-download?path=datasets%2F554%2Frows.csv"`. This URL is undocumented: it comes from the portal's download button (`getDownloadUrl`). The old Socrata id `ez5t-3qay` returns 404. The docstring says both.
  - **`download`:**
    1. GET the file to `.part` and compute its SHA-256.
    2. If `raw/ia/ia_business_entities.zip` exists and its sidecar's `sha256` matches, delete the `.part`, log `unchanged ia_business_entities.zip` and return `False`.
    3. Otherwise `os.replace` the file and write the sidecar with `url`, `sha256`, `bytes` and `downloaded_at`.

    This costs one full download per run. On the first run, record the size and time, and whether `Content-Length` is sent.
  - **`read`:** extract the single CSV `active_iowa_business_entities_554_rows.csv` with `zips.extract`. Streaming through `funzip` failed with "zipfile ended prematurely", so unzip the saved file. Then apply the contract's default header check and trimmed read.
  - **Select:**
    - `registry_id = corp_number`, kept as text because of its leading zeros
    - `name = legal_name`, `entity_type = corporation_type`
    - `formed_date = effective_date::DATE`, which is ISO
    - address, city and `zip5` from the `ho_*` (home office) columns, with `address_kind = 'physical'`
    - `active = true` (the active list drops entities administratively dissolved for missed reports), `status = NULL`, `status_date = NULL`, `officers = NULL`
    - extras `ia_registered_agent`, `ia_ra_city`, `ia_ho_country`
  - `dropped=(0, 0)`. Sentinel `("019862", date(1938, 1, 3))`.
- **`states/virginia.py`**
  - **Files.** The URLs come from the CKAN listing in `docs/data-sources.md`.
    - `corp.xlsx`: 90,239,379 bytes
    - `llc.csv`: 420,668,445 bytes, starting with a BOM
    - `gp.xlsx`: 1,203,163 bytes
    - `officer.csv`: 63,191,470 bytes

    Check the CKAN organization `state-corporate-commission` on the first run for a limited-partnership file. Add it if one exists, and record either way.
  - **`download`:**
    1. Read `ETag` and `Last-Modified` with `GET` and `Range: bytes=0-0`, following redirects. HEAD answers 403 on the presigned S3 target.
    2. Compare them with the sidecar.
    3. Download in full when they differ.
  - **`read`, XLSX:** prefer DuckDB's `excel` extension (`read_xlsx`). Install it at image build into a directory the uid-1000 user can read, and set `extension_directory` to it on the Virginia connection only. If that cannot work in the container, add `openpyxl` to the dependencies and record why.
  - **Sources.** There are three registry sources, `va_corporations`, `va_llcs` and `va_partnerships`. Each has its entity `File` plus the shared `officer.csv` `File` (spec 06 lets sources of one state share a file). Each select:
    - Trims padding, including the leading tab on `EntityID`.
    - Sets `registry_id = EntityID` and takes the name, `Street1`, `City` and `Zip`, with `address_kind = 'physical'` (the principal office).
    - Sets `entity_type` to `corporation`, `llc` or `general_partnership`.
    - Sets `status = Status`, `status_date = Status Date` and `active = Status = 'ACTIVE'`.
    - Sets `formed_date` from `IncorpDate`. It is an Excel serial in XLSX: `date '1899-12-30' + serial`, so 6600 is 1918-01-25. It is `YYYY-MM-DD` in the CSV. Placeholders such as `1899-02-16` on LLCs are counted and nulled, and recorded.
    - Sets `officers` to officers grouped by `EntityID`, as `OfficerTitle || ': ' || first || ' ' || last`.
    - Adds extras `va_industry_code` (an SCC code, not NAICS), `va_incorp_state`, `va_status_reason` and `va_registered_agent`. The contract fills `as_of` from the file's `Last-Modified`.
  - Corporations have duplicates. Dedupe deterministically by latest `Status Date`, record the count, and set `dropped` from it.
  - Assert in the stage that the `EntityID`s of the three sources are disjoint. Otherwise one business would aggregate two entities.
  - The corporations sentinel is `("00164871", date(1918, 1, 25))`. Choose the LLC and partnership sentinels from the first run.
- **`states/__init__.py`:** `STATES` gains `iowa` and `virginia`.
- **Tests:**
  - Fixtures use the real headers: a tiny zip for Iowa; and for Virginia a small `corp.xlsx` with the sentinel row (Excel serial date), an `llc.csv` with a BOM, and an `officer.csv`.
  - Each test asserts the staged rows. Iowa's `download` is tested against a local `http.server` for the changed and unchanged paths, as `test_http.py` does.

## End-to-end verification

1. Run `scripts/smoke.sh 7200` and paste its output. Record Iowa's download size and time, and Virginia's file dates from the ranged GETs.
2. Paste the query above. Record each state's matched share, calibrated floor and officer coverage.
3. Spot-check two old businesses per state against the raw files and paste both sides. Use the Iowa CSV row by `corp_number`, and the Virginia rows by `EntityID`.
4. A second run logs `unchanged` for Iowa (hash) and for Virginia (validators), and the file's `sha256sum` is identical.
5. `mise run check` passes.
