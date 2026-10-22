# 09-sam-start-dates implementation notes

## The extract (2026-10-17)

- `sam_discover` lists the keyless endpoint and picks `SAM_PUBLIC_UTF-8_MONTHLY_V2_20261005.ZIP`, the newest UTF-8 monthly file by the date in its name (the listing also holds 20260907 and 20260906 files, and the non-UTF-8 versions).
- `sam_download`: 150,133,435 bytes in 26 seconds, following the 303 to the signed S3 link.
- `sam_stage`: 905,712 records, 868,763 in the US, in about 10 seconds. The count equals the `BOF` line's (`BOF PUBLIC V2 00000000 20261005 0905712 0008359`). **Floor: `min_rows = 630_000`**, about 70%.
- US records: 868,161 have a start date; 247,395 started in 1996 or earlier, 235,278 of them active. Planning measured 235,277; the one more is probably the paired record below, whose first status is `A` (not checked).
- **Sentinel:** UEI `J64CSQTQNRC1`, INTERNATIONAL BUSINESS MACHINES CORPORATION, Armonk NY 10504, start date 1911-06-16, the same day New York's registry gives IBM (spec 08).

## The layout

- **Field positions** are pinned from GSA's "SAM Entity Management Public Extract V2" layout as I know it, and checked field by field against real records of this file: 1 UEI, 3 EFT indicator, 4 CAGE, 6 extract code (`A` active, `E` expired), 9 expiration date, 11 activation date, 12 legal name, 13 DBA name, 16 and 17 physical address, 18 city, 19 state, 20 ZIP, 22 country, 25 entity start date, 28 entity structure, 33 primary NAICS, 35 the NAICS list. Then six 11-field point-of-contact blocks: government business (47 first name, 49 last name), its alternate (58), past performance (69), its alternate (80), electronic business (91 and 93), its alternate (102). The layout document itself is on sam.gov behind JavaScript and was not fetched.
- **A field that holds a pipe is wrapped in NUL bytes**, such as `\x00SEH DESIGN|BUILD\x00` (an entity division name) and `\x00OWNER | CFO\x00` (a contact title). 276 records split into more than 142 fields on a plain `|`. DuckDB's `read_csv` will not take NUL as a quote character (passed as a parameter, it still reports 143 columns), so each line is read whole, pipes inside the NUL-quoted parts are masked, and the line is split. All 905,712 records then have exactly 142 fields, and the stage asserts it.
- **One record carries two registrations**: VLNHKZKSFEF3 (ENGINEERED MACHINED PRODUCTS INC) has status `A~E` and paired dates such as `20250909~20260828`, and its legal name is paired too. The stage keeps the first of each pair and logs the count (`paired=1`); the names are split only when the status is paired, since a name may contain `~`.
- **UEIs are not unique**: 898,204 UEIs on 905,712 records. One entity can hold several registrations, told apart by the EFT indicator (field 3); `(uei, eft_indicator)` is unique. The record id is `uei` plus `-<eft>` when there is one, and the stage keeps `eft_indicator`. Two records of one UEI are one entity, so when they stand apart they share the business id `SAM-<uei>`.

## Results (`smoke__20261017T125621Z`, after the code-review fixes)

- **24,956,761 businesses** (spec 08: 24,411,925). `build` takes 3 minutes 35 seconds, peak RSS 26,235 MB.
- SAM records (868,763 US) by tier: 1 82,148; 2 9,018; 3 2,383; 4 3,782; 5 100,141; 6 8,545; 7 9,500; none 653,246 (these join a same-key PPP or SBA record's business, or stand alone).
- **The spec's query**, top 15 states (with SAM / SAM-only / dated by SAM / address from SAM): CA 81,309 / 53,849 / 79,495 / 81,309; TX 70,364 / 17,158 / 36,789 / 70,364; FL 54,476 / 41,408 / 53,765 / 54,476; VA 39,012 / 28,921 / 38,384 / 39,011; NY 37,530 / 13,840 / 23,070 / 37,530; IL 34,467 / 24,408 / 33,864 / 34,467; GA 31,254 / 24,532 / 30,850 / 31,254; PA 30,146 / 11,266 / 18,903 / 30,146; MD 29,229 / 20,904 / 28,755 / 29,228; OH 24,404 / 16,998 / 23,740 / 24,404; NC 24,030 / 18,083 / 23,634 / 24,030; MI 22,470 / 16,006 / 21,932 / 22,470; CO 19,370 / 4,505 / 8,816 / 19,370; WA 19,327 / 12,947 / 18,926 / 19,327; NJ 18,774 / 12,716 / 18,376 / 18,774.
- **National totals:** 859,275 businesses have a SAM entity, 545,466 of them SAM-only. **240,200 gain a SAM start date 30 or more years old**, which is the oldest evidence for 227,179 of them. **859,271 take their lookup address from SAM** (every SAM business but four with no physical address). 432,782 take their industry from SAM, and 667,454 are `likely_open` because of an active SAM registration.
- **Spot checks.** `https://sam.gov/entity/ENVBFH3MF4X5/coreData` returns a 47 KB JavaScript shell with no entity data, so both were checked against the raw `.dat` line:
  - EIN-820349191, WESTERN LINE BUILDERS INC (NV, `dol_5500 + ppp + sam + sba`): `sam_start_date` 1986-06-01, 40 years. Raw: UEI ENVBFH3MF4X5, status A, WESTERN LINE BUILDERS, INC., Wells NV 89835, field 25 `19860601`, activation 2026-04-08.
  - EIN-951661089, SAN DIEGO CENTER FOR CHILDREN (CA, `dol_5500 + ppp + sam`): 1887-02-23, 139 years. Raw: UEI CYEXKEAMMX55, status A, San Diego CA 92111, field 25 `18870223`.
- **Second run** (`smoke__20261017T130106Z`): all 59 downloads log `unchanged` (SAM: the dated name with its recorded size), and `sha256sum include/data/marts/businesses.parquet` is `bb46a75906b1f97242db4ff6b8835dce28d199bf52617790d3790521755f17f9` after both runs.

## Decisions the spec did not cover

- **`zips.extract` takes a target folder and refuses to replace its own zip.** SAM.gov's inner zip has the outer zip's exact name, so the first run's extraction wrote the inner zip over the raw download, which breaks "the pipeline never edits a raw file" and would have forced a re-download on every run. The inner zip is now extracted into `raw/sam/<name>.unzipped/`. The next run re-downloaded the damaged file (its size no longer matched the sidecar), so the raw copy is the publisher's again. **For the owner to delete:** the 572 MB `.dat` that first run left in `include/data/raw/sam/` beside the zip; the current one is inside `.unzipped/`.
- **The DBA name gets tiers 1 to 3 too**, as a second pass that counts only when the legal name fits nothing in tiers 1 to 4. The trading name order puts SAM's DBA after the Texas outlet and the PPP DBA, and SAM's legal name after the PPP name.
- **SAM records follow the same-key rule of spec 07** only when they hold their key alone: a key two SAM records share is never followed, so two UEIs stay apart even when a PPP key with that key matched something.
- **A SAM record with no usable name or ZIP** (11 US records) stands alone as `SAM-<uei>`.
- **Only an active registration (`A`) is a signal**; an expired one gives none. When several SAM records join one business, the descriptive SAM columns come from the registration activated last, the start date is the earliest, and the activity signal is the latest activation of an active one.
- **`sam_poc_names`** lists the government and electronic business contacts' names.
- **The `qc` floor for businesses with SAM: `min_sam = 600_000`**, about 70% of the first run's 859,273.
- **The unit-test fixture is a `.dat` text file**, not the zip the spec describes; the test zips it twice, with the inner zip under the outer zip's name, as SAM.gov does. Its `BOF` count is set to the fixture's 5 records; the mismatch test sets it to 6.

## Code review (`/code-review high` on the uncommitted diff)

Fixed:
- **A UEI with several registrations was treated like two UEIs sharing a key** (6,373 UEIs, 13,878 US records): it never took the `KEY-` id and never followed a same-key PPP or SBA record, so one entity could be two rows. The key count now counts distinct own ids (`SAM-<uei>`), not records. The fixture's YUMA FENCE CO, one UEI with two registrations, joins its PPP key.
- **A DBA-name registry match could override an exact legal-name sponsor match** in tiers 5 to 7. The DBA's tiers now count only when the legal name fits nothing in tiers 1 to 7.
- **A SAM download without `Content-Length` was accepted unchecked**, and a truncated file would then have read as unchanged for the whole month. The header is now required.
- **The sentinel check compared a list of start dates** and would fail once IBM's UEI holds a second registration; it compares the distinct dates. The stage also asserts that `(uei, eft_indicator)` is unique.
- **`zips.extract` used a member name unchecked**; a name that resolves outside the target folder now raises.
- The lookup comment in `businesses.sql` now names SAM first.

Skipped:
- "`sam.download` copies `download_if_changed`'s GET and sidecar code": maintenance; the two differ in how they decide "unchanged".
- "`qc` repeats the SAM record key and the US filter": maintenance.
- "Each month keeps a 150 MB inner zip and a 572 MB `.dat` beside the raw zip": derived files, regenerated from the raw zip; the spec keeps every month's raw file.
