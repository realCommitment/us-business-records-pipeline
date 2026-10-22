# 07-sba-loans implementation notes

## Real data, first full run (2026-10-17)

- `sba_discover` found the six files (`asof_260630`); `sba_download` fetched them, 1,014,104,487 bytes in all, on the first run (`smoke__20261017T101518Z`).
- `sba_stage`: 2,190,482 loans in 1,835,314 `(norm_name, zip5)` borrowers, read in about 2 seconds. DuckDB read the files as UTF-8 with no encoding error, so no encoding option is set. **Floor: `min_rows = 1_530_000`**, about 70% of the first run.
- **22 loans dropped, none for a missing ZIP**: every loan has a `BorrZip` and a `BorrState`. All 22 have a name that normalizes to nothing: `-` (9), `THE COMPANY` (3), `!!`, `LTD Corp`, `INC CORP`, `LLP, LLC.`, `PLLC, INC.` and similar. The unit-test fixture therefore uses a real `-` borrower (Redmond, WA, 2005) as its unusable row, in place of the ZIP-less one the spec describes.
- Loan statuses: 7(a) `P I F` 1,179,345, `EXEMPT` 297,493, `CANCLD` 242,788, `CHGOFF` 220,687, `COMMIT` 21,123; 504 `PIF` 114,444, `EXEMPT` 61,265, `CANCLD` 32,313, `CHGOFF` 12,169, `NOT FUNDED` 8,516, `CLOSED` 339. `sba_charged_off` is `loan_status = 'CHGOFF'`. 58 charged-off 7(a) loans have no `ChargeOffDate`; they set `sba_charged_off` but give no dated closure signal.
- Approval dates run from 1990-10-01 to 2026-06-30, in 62 state codes.

## The build after SBA

- **The first build with SBA ran out of memory** at the 8 GB limit, in `sba_key`. Two changes, the second at the owner's direction on 2026-10-17:
  - SBA loans have no id, so the tiebreak between loans of the same day was the whole row as text, which made every aggregate state carry a long string. `loan_key` is now a `row_number()` over the row as text, computed once with a sort that spills; identical rows are interchangeable.
  - **`build` gets `memory_limit = '24GB'` and every core** (the `threads = 4` cap from spec 06 is gone). The owner asked for more memory and CPU on this 64 GB machine (56 GB usable, about 35 GB free with IntelliJ open). `build` runs only after every stage task has finished, so its 24 GB never overlaps their 8 GB each. The stage tasks keep 8 GB. This departs from product decision 5's "8 GB per connection" for `build` only.
  - With both, `build` takes 1 minute 49 seconds (3 minutes in spec 06 with 4 threads), with a peak RSS of 24,513 MB.
- **The Texas Comptroller republished both files during this session** (Last-Modified 2026-10-17 10:31 and 10:35 GMT). The run downloaded them: 3,487,631 franchise rows (from 3,486,185) and 891,754 outlets (from 890,307). Spec 06's own code at its 8 GB limit ran out of memory on the new Texas data during the comparison below, which confirms that 8 GB had become marginal.

## Results (`smoke__20261017T112443Z`, after the code-review fixes)

- **15,074,603 businesses**; `build` 1 minute 45 seconds, peak RSS 24,444 MB. The whole DAG takes about 3 minutes when nothing downloads.
- The spec's query: 1,827,425 businesses have an SBA loan; 1,442,374 are SBA-only; 1,696,857 are dated by an SBA approval (`age_source = 'sba_loan'`); 1,277,416 take their industry from SBA.
- Top 10 states (with SBA, SBA-only, dated by SBA, industry from SBA): CA 260,529 / 211,030 / 245,107 / 186,492; TX 144,728 / 98,878 / 109,812 / 99,357; NY 113,752 / 89,952 / 106,887 / 78,698; FL 104,826 / 83,777 / 98,165 / 76,815; OH 71,452 / 54,758 / 66,287 / 49,251; IL 61,976 / 48,744 / 58,107 / 43,300; PA 60,483 / 48,473 / 57,071 / 42,898; NJ 54,191 / 44,285 / 51,278 / 39,670; GA 51,778 / 42,194 / 49,277 / 37,274; MI 51,272 / 39,312 / 47,578 / 36,139.
- SBA borrowers by tier: 1 22,016; 2 9,358; 3 1,090; 4 5,467; 5 87,420; 6 19,368; 7 11,208; unmatched 1,679,383 (these join a PPP key's business by key, or become `KEY-` businesses).
- Open status of businesses with SBA: 216,176 likely closed (213,283 of all businesses with a charged-off SBA loan), 207,200 likely open, 1,404,154 unknown.
- **Spot checks against the raw CSVs**, both 30 or more years old and merged with other sources:
  - EIN-561309636, ULTRA-MEK, INC. (NC, `dol_5500 + ppp + sba`): `oldest_evidence_date` 1992-08-24, `sba_loan`. Raw: `FOIA_7a_FY1991_FY1999_asof_260630.csv`, ULTRA-MEK, INC., ZIP 27239, NC, approved 1992-08-24, P I F; a second loan on 1994-05-09.
  - KEY-30305-ACOUSTECH MUSIC PRODUCTIONS I (GA, `ppp + sba`): 1996-05-28, `sba_loan`. Raw: same file, ACOUSTECH MUSIC PRODUCTIONS, I, ZIP 30305, GA, approved 1996-05-28, P I F.
- **Rows that gained nothing from SBA are unchanged.** Because the Texas files changed during the session, spec 06's committed code (with its memory limit raised, in a scratch worktree) was rebuilt on today's stage files as the baseline. Of 13,247,178 businesses without SBA, 13,247,162 are identical in every spec 06 column. The 16 that differ change only in sponsor columns (`plan_link`, `ein`, `phone`, plan fields): SBA borrowers now take part in tiers 5 to 7 against sponsors, so a lone sponsor hops only when the SBA borrowers that fit it agree too (hops went from 1,102 to 1,177). The same effect removes 91 spec 06 sponsor-only rows; the 412 spec 06 PPP-only rows no longer present are in businesses that gained an SBA borrower.
- **Second run** (`smoke__20261017T112730Z`): all 55 downloads (13 PPP, 2 Texas, 34 Form 5500, 6 SBA) log `unchanged`, and `sha256sum include/data/marts/businesses.parquet` is `4a8cd70f28f863fb29521e9410d15ea9d4ba6385f731a660e881d38a3ca6900d` after both runs.

## Decisions the spec did not cover

- **`match_tier` and `match_similarity` now come from every record**, PPP keys and SBA borrowers alike, as product decision 9 says ("the best tier any of its records used"). In spec 06 they came from PPP keys only.
- **An SBA-only business takes the SBA borrower name as its `lookup_name`**, last in the order, so it has a name to look up. It has no lookup address, as the spec says.
- **`age_source = 'sba_loan'` ranks before `ppp_loan` on a tie**, and the SBA approval date passes through `evidence_date` like every other candidate.
- **`sba_first_business_age`** is the `BusinessAge` of the business's earliest loan, ties broken by `loan_key`. **`sba_programs`** is the sorted distinct list of trimmed programs (`7A`, `504`).
- **The SBA activity signal** is the latest approval (`sba loan approved <date>`); the closure is the latest charge-off date (`sba loan charged off <date>`). A charge-off decides only when it is the newest signal, as with PPP.
- **Cancelled and not-funded loans count**: an approval, even one later cancelled, shows the borrower existed on that date. The spec forbids filtering by status.
- **The `qc` floor for businesses with SBA: `min_sba = 1_280_000`**, about 70% of the first run's 1,827,530.

## Code review (`/code-review high` on the uncommitted diff)

Fixed:
- **A PPP key and an SBA borrower with the same `(norm_name, zip5)` could land in two businesses** (1,842 keys on the first run, such as `02633|CHATHAM BOAT`: the PPP key fit sponsor EIN-923624541 in tier 6 while the SBA borrower, at an older address, fit nothing and became `KEY-02633-CHATHAM BOAT`). Step 4 now lets a record that matched nothing join the business that other sources' records with its exact key matched, when they all matched the same one. A record never follows a record of its own source, so two SAM or FMCSA records sharing a key will still stay apart (specs 09 and 13). The fixture's SBA borrower SPRINGFIELD PLUMBING INC at an old Chatham address follows the PPP key into IL-0001.
- **Blank states**: 5 loans had a state of two spaces, which passed `state is not null` and made 5 businesses with no real state (two were SBA bookkeeping rows, "SECONDARY MARKET FEES" and "ASSET SALE START UP COSTS MASTER"). The stage now trims the state to NULL, so they are dropped.
- **`arg_min` and `arg_max` skip NULL values**, so the first loan's age bucket could come from a later loan (2,653 loans have none), and the address, city and state could come from three loans. The place is now one struct from the latest loan, and `sba_first_business_age` uses `arg_min_null`.
- **A future-dated charge-off** (AMG INDUSTRIES, INC., 2026-10-22) could replace a real earlier one and then be filtered out with it; `charge_off_date` now passes through `evidence_date`.
- **No SBA loan conservation**: `qc` now asserts `sum(sba_loan_count)` equals the staged loans.
- `build` logs `sba_keys_by_tier` beside `ppp_keys_by_tier`, and `match_tier` and `match_similarity` come from one struct.

Skipped:
- "24 GB with every core is close to the measured peak": the owner chose it, and DuckDB spills to `marts/_work/tmp` before it fails. The other Astro project on this machine was stopped on 2026-10-17.
- "Number SBA loans at stage time instead of in `build`": performance only; the sort takes seconds.
- The PPP key's `arg_max` per column has the same NULL-skipping pattern as SBA had, but PPP addresses come from one CSV row per loan and changing it is outside this spec.
