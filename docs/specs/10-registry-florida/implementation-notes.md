# 10-registry-florida implementation notes

## Setup (2026-10-17)

- **`packages.txt` gains `unzip`.** After `astro dev restart`, `docker exec <scheduler> unzip -v` reports `UnZip 6.00 of 20 April 2009, by Debian` and `USE_DEFLATE64 (PKZIP 4.x Deflate64(tm) supported)`. The restart printed a new UI address (`retiringbuinsinessowners.localhost:6563`); `localhost:8080` still answers, so `scripts/smoke.sh` is unchanged.
- **Host key.** `ssh-keyscan sftp.floridados.gov` returns RSA, ECDSA and Ed25519 keys (server `SSH-2.0-VShell_5_0_0_3938`). The container's libssh2 1.11.1 negotiates the ECDSA key, whose SHA-256 is `TPtpEBn4t/fjdWpecrIQ0BgLXRAqj9wjDkoCNIggZEE=`; `--hostpubsha256` takes it with the base64 padding. With either other fingerprint, curl refuses: "Denied establishing ssh session: mismatch sha256 fingerprint".

## Download

- **`curl --head` prints nothing over SFTP**, so it cannot give the size and time the spec expected. Two small calls replace it:
  - the directory listing, which gives the exact size (`----------    1 nobody   nobody   1793034019 Oct 07 11:45 cordata.zip`) but a date without a year;
  - a one-byte read (`--range 0-0 --remote-time`), which sets the probe file's time to the server's modification time: 2026-10-07 15:45:22 UTC.

  The sidecar stores both (`bytes`, and `last_modified` in HTTP date form so the contract's `as_of` reads it), and the file downloads only when either differs or the file on disk has another size.
- **The first download: 1,793,034,019 bytes in 35 minutes 19 seconds** (about 0.85 MB/s over SFTP). `state_download` has a 2-hour timeout.
- **`as_of` is the SFTP modification time, 2026-10-07**, so Florida's activity signals are as old as the quarterly file.

## Read and stage

- **Members:** `unzip -Z1` lists exactly `cordata0.txt` to `cordata9.txt`, 1,872,625,902 to 1,873,075,806 bytes each, 18.7 GB in all. Extracting them with `unzip -p` took about 2 minutes. A member newer than the zip is not extracted again.
- **Records end in CRLF**, not LF as `docs/data-sources.md` says; DuckDB drops the line ending, and every line is exactly 1,440 characters. The view reads the members in Latin-1 as one column per line with no quoting; its paths are inlined because a view cannot take a prepared parameter.
- **`read` gets the raw file's path**, as the contract's default `read` does. Spec 06's notes say `read` takes the data directory; that is true of `download` only.
- **`fl_corporations`: 12,987,601 records, no repeated document number** (`dropped = (0, 0)` stands), staged in about 3.5 minutes with a peak RSS of 10.3 GB; Florida's read spills under `stage/_tmp_fl`. **Floor: `min_rows = 9_090_000`**, about 70%.
- **Statuses:** `I` 9,168,902 records (9,164,447 with a last transaction date, median 2014-09-26), `A` 3,818,699 (1,021,451 with one). For an inactive record the last transaction date is the date of its last filing, which for most is the dissolution or revocation; the fixture's RIPLEY AND COMPANY (formed 1876) went inactive with a last transaction on 1996-08-23. That was not checked against the Division's site, which blocks scripts.
- **Filing types:** FLAL 6,611,958, DOMP 5,189,062, DOMNP 510,480, FORP 303,076, FORL 264,593, DOMLP 72,393 and smaller ones.
- **Sentinel:** 444750, RAYMOND JAMES FINANCIAL, INC., formed 1974-01-24, FEI 591517485, six officers. `read` checks the FEI, because the contract's sentinel holds only a formed date.

## EINs: an FEI counts only when one document alone carries it

- 7,579,108 records (58.4%) carry a 9-digit FEI, but 144,923 FEIs are on more than one document. Among them are placeholders (999999999 on 411 records, 123456789 on 196, 111111111 on 146) and numbers shared by unrelated companies: 542129332 on 459 medical practices, 381798424 on a tile company, a gutter company and a construction consultancy, 941687665 on 187 family partnerships, most likely the EIN of a filing service, a parent or a trust company.
- Under decision 16 every registry row with the same EIN becomes one business, which would merge unrelated companies, against the anti-goal "one row for two businesses is not acceptable". So **Florida keeps the FEI as the EIN only when exactly one document carries it**: 7,268,207 records, 56.0%, every one unique. A genuine pair, such as a corporation later re-registered as an LLC, stays two rows, the acceptable direction.

## Fitting the build in memory (2026-10-17 and 18)

- **The first build with Florida ran out of memory** at the 24 GB limit ("could not allocate block of size 256.0 KiB (22.3 GiB/22.3 GiB used)", run `smoke__20261017T141435Z`), and again at 32 GB ("failed to pin block ... 29.7 GiB/29.8 GiB used", `smoke__20261017T222301Z`), both about 2 minutes in. Memory pressure on the host also stopped the run's watcher once; the cause was 13 GB of my own comparison files in `/tmp`, which is RAM on this machine, since deleted.
- **A per-statement profile at 40 GB** (on the host, the same SQL and stage files) found the peaks in three statements, not in the tier joins (17.7 GiB at most): `reg_agg` 39.3 GiB in 33 s, `picked` 37.3 GiB in 45 s and `businesses` 34.5 GiB in 45 s. Florida's candidate pairs for tier 3 are many (103.6M PPP-to-registry pairs, 20.4M of them at one St. Petersburg address with 158,462 entities) but cost time, not memory.
- **Two changes, no change in output:**
  - `reg_agg` aggregated all 26.3M registry rows with about 40 string and list picks, though only 23,432 businesses have more than one registry row (a shared EIN). A business with one row now passes through as it is, and only the others are aggregated: 16.2 GiB. Checked on the profile database: the new table equals the old one in every row and column (2 rows differed only through the run date I set, a Texas formed date of 2026-10-18).
  - `picked` drove its eleven joins from `select distinct business_id from members` and joined `src` to it; `src` already has exactly one row per business, so it drives the joins now. `picked` and `businesses` then fit at 24 GB (22.8 GiB each, spilling).
- **`build` keeps 32 GB** (the comment and `memory_limit` in `businesses.py`), for the registries of specs 11 to 13. The VM now has 61 GB; the owner gave it more memory from the host on 2026-10-18.

## Results (`smoke__20261017T231304Z`)

- The run took 515 s with no download. `fl_corporations` staged 12,987,601 rows in 2 min 34 s, with extraction skipped (members newer than the zip). On disk: the zip 1.8 GB and the ten members 18.7 GB.
- **`build`: 4 min 39 s, peak RSS 38,854 MB** at the 32 GB limit, **37,431,961 businesses** (spec 09: 24,956,761).
- **Florida's matched share of non-individual PPP keys: 71.8%** (290,175 of 404,401), the highest of the five registries; **`min_match_share = 0.48`**, about two-thirds of it, as for spec 08. New York moved from 212,722 to 212,708 matched keys (14 keys now fit a Florida registry business or sponsor first); Texas, Pennsylvania and Colorado are unchanged.
- **Sponsors** (spec 09 then spec 10): by EIN 51,376 then **196,587**, by name 143,261 then **142,026**, by the hop 2,397 then **2,725**, alone 1,429,547 then 1,285,243. Florida's FEIs bring the EIN joins.
- PPP keys by tier: 1 702,134; 2 120,378; 3 57,196; 4 15,754; 5 412,681; 6 46,161; 7 62,848; none 7,775,523.
- **The spec's first query fails as written** in DuckDB 1.5.6: `old` is a reserved word ("syntax error at or near "old""). With `as old` and nothing else changed:

  | open_status | businesses | with_ppp | with_ein | with_plan | with_officers | old |
  | --- | --- | --- | --- | --- | --- | --- |
  | likely_open | 3,836,987 | 237,426 | 2,904,275 | 113,009 | 3,787,373 | 147,713 |
  | likely_closed | 9,186,722 | 136,163 | 4,328,893 | 24,454 | 8,621,986 | 2,032,140 |
  | unknown | 466,969 | 411,492 | 27,824 | 24,211 | 26,425 | 14,129 |

- **The second query** prints 444750, RAYMOND JAMES FINANCIAL, INC., EIN 591517485, formed 1974-01-24, status A, and its six officers (`Chie: Konefal Richard` first).
- **Spot checks** against the raw record (`grep -a '^<doc> ' include/data/raw/fl/cordata*.txt`, cut at the module's offsets):
  - `EIN-590950068`, CHRIST THE KING EVANGELICAL LUTHERAN CHURCH OF MIAMI FLORIDA (`fl_corporations + ppp`, tier 1): ours formed 1961-12-25, 64 years, status A, ZIP 33156, officers `Pres: GONAS SAM`, `VP,: BEISENHERZ JON`. Raw 703369: status A, DOMNP, 11295 SW 57th Avenue, Miami FL 33156-5011, filed 12251961, FEI 590950068, first officer `Pres` GONAS SAM.
  - `EIN-596046075`, WEST VOLUSIA HUMANE SOCIETY INC (`fl_corporations + ppp`, tier 1): ours formed 1970-08-05, 56 years, status A, ZIP 32720, officer `Exec: Figueroa Victoria`. Raw 718956: status A, DOMNP, 800 HUMANE SOCIETY RD, DELAND FL 32720, filed 08051970, FEI 596046075, last transaction 05082018, first officer `Exec` Figueroa Victoria.

- **Second run** (`smoke__20261017T232255Z`, before the code-review fixes): all 60 downloads log `unchanged`, `cordata.zip` among them; no member was extracted again; `sha256sum include/data/marts/businesses.parquet` is `02777125bb9cb14d21a9095854cbe196bb512103122e14804e869b034444540b` after both runs.

## Outside Florida, compared with spec 09's file

Rows hashed on spec 09's columns, joined on `business_id`. Outside Florida, 23,909,439 rows are unchanged, 92,097 changed, 238 are gone (237 in New York) and 1,016 are new. Every change comes from Florida's FEIs: an EIN is national (decision 16), so a record in another state with the same EIN now joins the Florida entity.
- **61,269 businesses of another state gained a Florida registry row and are now `FL`**: mostly sponsors and Texas taxpayers that are Florida foreign corporations. A business's `state` comes from its registry row first.
- **23,424 gained a Florida row and kept their state**, such as 7,755 `tx_franchise` into `fl_corporations + tx_franchise`. When a business has registry rows in two states, `state` and the registry columns come from the row with the smallest `(registry_id, source)`, a rule from spec 06 that first matters now.
- 6,515 lost or swapped a source, such as 1,018 New York businesses whose Form 5500 sponsor joins a Florida entity by EIN instead of the New York one by name (an EIN beats a name), and 889 changed in other columns only.

## After the code-review fixes (`smoke__20261017T234407Z`, then `smoke__20261017T235310Z`)

- **37,431,961 businesses**, the same count; `build` took 5 min 15 s at a peak RSS of 36,367 MB (the second run 5 min 2 s, 36,135 MB). Matched shares and sponsor counts are as above. `fl_address_line_2` is set on 3,038,896 records; the EINs are the same 7,268,207.
- Both runs log `unchanged` for all 60 downloads and extract no member; `sha256sum include/data/marts/businesses.parquet` is `b610f5d2e355b930eb2f6cff1386d24e16b3924f2dd49dbea18cc0a1ff864795` after each.

## Code review (`/code-review high` on the uncommitted diff)

Fixed:
- **A blank line in a member passed the width check**: DuckDB reads it as NULL, and `NULL != 1440` is not true. The check uses `is distinct from`; a test adds a blank line.
- **A missing sentinel raised `TypeError`** (`list() filter` over no rows is NULL) instead of naming the file and the FEI. It is `coalesce`d to `[]`.
- **curl's error text was dropped**: `check=True` with captured output raised with the exit status only, so a changed host key or login would not say so. The error now carries curl's message.
- **A placeholder FEI held by one document would have become an EIN**: 999999999 and 123456789 are left out today only because many documents share them. One digit nine times and 123456789 are now excluded outright; none is an EIN today, so this changes nothing now. A test sets a fixture FEI to 999999999.
- **Principal address line 2 was not staged** (bytes 263 to 304: suite, unit or floor). It is the extra `fl_address_line_2`, as Pennsylvania's `pa_address_line_2`.
- **The FEI window carried the whole 1,440-character line**: the fields are now cut in the CTE and the window runs over them.
- **The comment in `businesses.sql` named a state**; it no longer does.
- **`reg_agg`'s two branches could drift apart silently** under `union all by name` (a column missing in one branch is NULL for it). The union is positional, so a column count that differs fails.

Skipped:
- "32 GB is close to the free memory": the build's peak was measured (38,854 MB RSS) on the VM's 61 GB, with every run since passing.
- "The view over 18.7 GB is scanned three times": time only; the stage takes 2.5 minutes.

## Decisions the spec did not cover

- **Dates before 1822**, when Florida became a territory, are typos and become NULL: 8 formed dates such as 1609-11-17, and some status dates such as 1670-07-16. Dates after `run_date` (16 formed dates, status dates up to 9968) are left to the transform's `evidence_date`, as for every state.
- **Officer names** keep the published "last first middle" order with the padding collapsed: `Chie: Konefal Richard`. The title field is 4 characters, so long titles are cut (`Chie` for chief executive officer, as published).
- **`fl_mailing_address`** is the whole mailing block (address lines, city, state and ZIP), trimmed.
- **The unit-test fixture** is three real records (Raymond James, the inactive RIPLEY AND COMPANY, and EAST COAST LUMBER & SUPPLY COMPANY) in a standard-deflate zip as `cordata0.txt` to `cordata2.txt`, with empty `cordata3.txt` to `cordata9.txt` so the member check holds.
