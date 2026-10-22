# 12-registries-ia-va implementation notes

## Setup (2026-10-18)

- **`Dockerfile` installs DuckDB's `excel` extension at build** into `/usr/local/airflow/duckdb_extensions`, and Virginia's connection sets `extension_directory` to it. The container runs as uid 1000 with `HOME=/`, so DuckDB's default folder (`/.duckdb`) is not writable and could not be used. After `astro dev restart`, the scheduler (uid 1000) loads it: `install_path /usr/local/airflow/duckdb_extensions/v1.5.6/linux_arm64/excel.duckdb_extension`. No `openpyxl` was needed. `read_xlsx` reads the 90 MB `corp.xlsx` (465,855 rows) in about 6 seconds.
- **The machine is ARM64** (`linux_arm64`), a VMware guest; the extension is the ARM build.
- **On the host** (unit tests) the extension comes from DuckDB's default folder, `~/.duckdb/extensions`, installed once by the Virginia test.
- **`read_default` moved above the state imports** in `states/__init__.py`, as `raw_path` did in spec 10: Iowa's module imports it, and below the imports it would be a circular import.

## Iowa

- **Download:** 102,683,698 bytes in 16 s. The response has **no `Content-Length`** (and neither `ETag` nor `Last-Modified`), so the size cannot be checked against a header; the SHA-256 alone says whether the file changed. The zip holds one CSV, `active_iowa_business_entities_554_rows.csv`, 102,683,472 bytes, dated 2026-10-17 17:43 inside the zip.
- **348,270 entities, every `corp_number` unique**, the count the portal reports. `effective_date` is ISO throughout, from 1828-06-07 (FORT MADISON LODGE #374, B. P. O. E., as published; the Elks were founded in 1868) to 2026-12-27 (a future effective date, left to the transform's `evidence_date`).
- **`as_of` is the download date**: the sidecar has no `last_modified`, so the contract's rule dates it by `downloaded_at` and logs so. An unchanged file keeps its first download's sidecar, so `as_of` stays the date the content was first seen.
- **ZIPs:** 335,617 home-office ZIPs. 73 rows have a five-digit postal code with a foreign `ho_country` (CAN, GBR, IND and others); a ZIP counts only when the country is `USA` or blank. 95 US ZIPs have four digits (a dropped leading zero, such as `5807`) and get none.
- **Floor `min_rows = 243_000`**, about 70%. Sentinel 019862 HY-VEE, INC., 1938-01-03, home office West Des Moines 50266.

## Virginia

- **The CKAN organization does publish a limited-partnership file**, `lp.xlsx` ("Limited Partnership - definition", 2,263,176 bytes, Last-Modified 2024-11-14), so it is a fourth source, `va_limited_partnerships`. The organization's other files (merger, amendment, PSA, name history, filing details, lien details, reserved names, business trusts) stay out, as the spec says.
- **Validators from the one-byte ranged GETs** (all answer `206` after a 302 to S3): `corp.xlsx` Last-Modified Thu, 14 Nov 2024 19:51:27 GMT; `llc.csv` Mon, 02 Dec 2024 20:29:28; `gp.xlsx` Thu, 14 Nov 2024 19:28:20; `lp.xlsx` Thu, 14 Nov 2024 20:29:16; `officer.csv` Mon, 02 Dec 2024 20:03:51. Each `as_of` is its entity file's date, so Virginia's "good standing" signals stop counting as recent after 2026-11-14 (LLCs 2026-12-02).
- **`llc.csv` and `officer.csv` are cut at Excel's row limit: both have exactly 1,048,575 rows.** The LLC file's latest formation date is 2022-06-16 although its status dates run to 2024-11-24, so LLCs formed after mid-2022 are missing from what Virginia publishes, and so are the officers past the cut. This is the source's limit; the spec rules out refreshing Virginia from elsewhere.
- **Officers cover corporations only:** `officer.csv`'s ids are corporation ids (412,300 corporations have officers; no LLC or partnership does). Titles keep the export's HTML escapes, such as `SVP &amp; COO`, as published.
- **Dates come in three forms.** In the XLSX files `IncorpDate` and `Status Date` are Excel serials (6600 is 1918-01-25), except 46 corporations formed before 1900, which Excel cannot hold as serials and which are ISO text (THE WASHINGTON AND LEE UNIVERSITY 1782-10-07). In `llc.csv` they are `M/D/YYYY` (`9/6/2011`), **not `YYYY-MM-DD` as the spec says**, again with ISO text before 1900. One helper reads all three, strictly. Excel counts the nonexistent 1900-02-29, so a serial below 61 is a day later than the 1899-12-30 epoch gives; 8 corporations have one (3 hold serial 1, 1900-01-01, which the transform's `evidence_date` treats as the placeholder it is).
- **Placeholders:** `1899-02-16` is on 1 LLC's `IncorpDate` (Handy Distribution LLC) and becomes NULL.
- **Duplicates,** removed by keeping the latest `Status Date`, then the whole row as text: corporations 465,855 rows into 444,386 (21,469 dropped; the repeated rows share their status date and differ in other columns), LLCs 1,048,575 into 1,048,051 (524), general partnerships 7,163 into 7,097 (66), limited partnerships 12,627 into 12,264 (363). `dropped` is about 20% either side of each.
- **The four sources' `EntityID`s are not disjoint: 5 ids are in both `corp.xlsx` and `llc.csv`**, and each pair is one entity, a corporation converted to an LLC under the same id with the same incorporation date (03261807 MONTEREY PALE COMPANY and MONTEREY PALE, LLC, 1988-08-22; 04481016 MATH MECHANICAL; 06164370 SDE DESIGN; 11216139 UNIVERSAL PAINTING; S7579578 TwoSum). The spec's assert would fail on them. Instead each source's stage checks every id it shares with another Virginia file and **fails when the two rows have different incorporation dates** (two entities under one id); a shared id with one date is one entity, and the merge makes it one business (`VA-03261807`). A test changes the LLC's date and gets the error.
- **State names are spelled out** ("Virginia", "Maryland", "District Of Columbia"); a name maps to its code, case-insensitively, for the address state and to decide whether a ZIP is a US one. 366 foreign provinces and cities stay as published, with no ZIP. 1,484,138 rows have a ZIP.
- Statuses in the corporation file: ACTIVE 195,553, INACTIVE 234,335, PENDINACT 14,498 (pending inactivation, a closure under the spec's `active = Status = 'ACTIVE'`).
- **Sentinels:** corporations `00164871` UNIVERSAL CORPORATION 1918-01-25; LLCs `00036251` Lumos Telephone of Botetourt LLC 1901-02-23, the oldest active LLC; general partnerships `K0000119` Deloitte LLP 1996-03-06, the oldest active one; limited partnerships `L0005035` GENERAL INVESTORS REALTY ASSOCIATES, A LIMITED PARTNERSHIP 1987-01-21.
- **Floors** (about 70%): corporations 311,000, LLCs 733,000, general partnerships 4,960, limited partnerships 8,580.
- Stage time on the host: about 7 to 8 s per source, most of it reading the other entity files for the shared-id check.

## Results (`smoke__20261018T011847Z`)

- The files were first downloaded by the modules' own `download` on the host, into their raw paths and sidecars, so the run found them unchanged: Iowa by hash (it downloaded the zip again, 102,683,698 bytes, and kept the old copy), Virginia by validators. The run took 728 s.
- **41,379,358 businesses** (spec 11: 39,673,571). `build` 7 min 26 s, peak RSS 37,640 MB at the 32 GB limit.
- **Matched share of non-individual PPP keys:** Iowa 64.6% (34,527 of 53,445), Virginia 72.2% (83,308 of 115,442). **Floors: IA 0.43, VA 0.48** (on all four Virginia sources), about two-thirds of each.
- **Officer coverage:** Virginia 412,300 businesses, all corporations (no LLC or partnership has officers in `officer.csv`); Iowa publishes none.
- PPP keys by tier: 1 885,240; 2 136,548; 3 72,709; 4 15,754; 5 383,528; 6 43,077; 7 59,251; none 7,596,568. Sponsors joined by name 204,476 (spec 11: 174,751), by the hop 3,140.
- **Coverage:** 3,847,345 of 11,467,847 staged PPP loans (33.5%) are in the ten registry states, the spec's figure (planning counted 3,847,441 of 11,468,210 raw loans; the stage drops loans with no usable key). 1,525,519 loans (13.3%) belong to a business with a registry row.
- **The spec's query:**

  | State | open_status | Businesses | PPP with registry | With formed | With officers |
  | --- | --- | --- | --- | --- | --- |
  | IA | likely_closed | 4,068 | 0 | 0 | 0 |
  | IA | likely_open | 353,032 | 34,066 | 348,262 | 0 |
  | IA | unknown | 114,782 | 0 | 0 | 0 |
  | VA | likely_closed | 925,927 | 16,615 | 916,082 | 225,350 |
  | VA | likely_open | 617,067 | 65,160 | 593,587 | 185,900 |
  | VA | unknown | 105,393 | 1,067 | 2,056 | 1,050 |

  Every Iowa registry business is `likely_open` (an active list dated by the download); Iowa's `likely_closed` and `unknown` rows have no Iowa registry row. Virginia's `likely_open` rows count until 2026-11-14, when the snapshot's `as_of` leaves the 24-month window.
- **Spot checks against the raw files:**
  - Iowa `023277` KLYN TIRE & BATTERY, INC. (`ia_business_entities + ppp`, tier 1): ours formed 1961-11-27, 64 years, ZIP 51566. CSV row: DOMESTIC PROFIT, `effective_date` 1961-11-27, home office 1904 WOODFIELD DR, RED OAK IA 51566, USA, agent JAY KLYN.
  - Iowa `006919` CAPITAL CITY EQUIPMENT COMPANY (`dol_5500 + ia_business_entities + ppp`): ours formed 1976-09-13, ZIP 50313. CSV row: DOMESTIC PROFIT, 1976-09-13, 5461 NW 2ND STREET, DES MOINES IA 50313.
  - Virginia `01871888` 1708 Gallery Inc. (`ppp + sam + va_corporations`): ours formed 1978-08-08, PENDINACT, ZIP 23220, officers listed from `officer.csv`. XLSX row: `IncorpDate` 28710 (1978-08-08), PENDINACT ("Annual Registration Fee Past Due ... Not in Good St"), `Status Date` 45537 (2024-09-02), 319 W Broad St, Richmond 23220-4218; six officer rows, titles cut at 15 characters as published (`Treasurer  Offi`). It is `likely_open` because its SAM registration is newer than the closure.
  - Virginia `S0126385` ROSEN & UNDERDOWN, CPAS, PLC (`ppp + va_llcs`): ours formed 1996-02-05, ACTIVE, ZIP 23111. CSV row: ACTIVE, `IncorpDate` 2/5/1996, `Status Date` 12/3/1998.

- **Second run** (`smoke__20261018T013158Z`, before the code-review fixes): Iowa downloaded the zip again and logged `unchanged ia_business_entities.zip` (same SHA-256); Virginia's five files logged `unchanged` from their ranged GETs; `sha256sum include/data/marts/businesses.parquet` is `44372e02c5429442094b73ac51fb518479894cc1b6ff1ef65021540629cc1279` after both runs.

## After the code-review fixes (`smoke__20261018T014522Z`, then `smoke__20261018T020340Z`)

- **41,379,358 businesses**, the same file as before the fixes: `sha256sum include/data/marts/businesses.parquet` is `44372e02c5429442094b73ac51fb518479894cc1b6ff1ef65021540629cc1279` after each run. `build` took 8 min 19 s at a peak RSS of 36,360 MB, then 8 min 31 s at 36,909 MB.
- All 70 downloads log `unchanged`: Iowa by hash, Virginia's five files by validators. The shared-id check ran once per pair of files (6 pairs; only corporations and LLCs share ids, 5 of them).

## Code review (`/code-review high` on the uncommitted diff)

Fixed:
- **`read_xlsx` stops, silently, at the first blank row** (DuckDB's default `stop_at_empty`): a blank row in a re-exported `corp.xlsx` would have dropped everything below it while the `dropped` check still passed. The read sets `stop_at_empty=false`; today's files have no blank row (465,855, 7,163 and 12,627 rows either way), and a blank row would now stage as a row without an id and fail the unique-id check.
- **The shared-id check counted the LLC placeholder date as a different entity**: a converted entity whose LLC row carries 1899-02-16 would have failed both stages. Dates are compared after the placeholder is removed, and only when both are known; a test sets the shared LLC's date to the placeholder.
- **Each pair of files was checked twice**, and every source loaded all four entity files. The earlier file's source now checks each later file once (corporations against the other three, LLCs against the two partnership files, general partnerships against limited ones); the error test now stages corporations.
- **Iowa's missing `Content-Length` became 0**, a fallback that turned off the length check without saying so. It is now checked only when the header is sent, a comment records that the portal sends none, and **the downloaded zip is tested (`ZipFile.testzip`) before it replaces the good copy**, since nothing else would catch a cut-off download; a test serves half the zip and keeps the old file.
- **Iowa's `download` used the module's `URL`, not `file.url`**; it uses the `File` it is given, and the test passes a `File` with the local server's URL.
- **The Dockerfile comment named a state**; it says "the registries published as XLSX". The `RUN` line is unchanged.

Skipped:
- "Virginia's and Iowa's downloads copy `download_if_changed`": the spec's anti-goal puts ranged GETs and content hashing in each state's module, with no contract change.
- "The LLC and partnership sources load `officer.csv`, which only has corporations": the spec gives every Virginia source the shared officer file; only the 5 converted ids could match, and today none does (no LLC or partnership has officers).
- "The floors cite numbers the notes do not hold": the notes now record the run.
