# 05-business-dataset implementation notes

## Real data, first full run (2026-10-17)

- `build` writes 4,284,708 businesses in 15 seconds, with a peak RSS of 9,168 MB (logged by `build` as `peak_rss_mb`). The whole DAG run takes about 52 seconds when nothing has to download. The peak is above the 8 GB `memory_limit`, because DuckDB's limit does not cover every allocation; this machine has 56 GB.
- Businesses by source combination:

  | Sources | Businesses |
  | --- | --- |
  | tx_franchise | 2,897,838 |
  | ppp | 530,888 |
  | tx_franchise + tx_sales_outlets | 357,945 |
  | tx_sales_outlets | 244,023 |
  | ppp + tx_franchise | 105,462 |
  | ppp + tx_franchise + tx_sales_outlets | 76,861 |
  | dol_5500 + ppp + tx_franchise | 14,207 |
  | dol_5500 + tx_franchise | 13,582 |
  | dol_5500 + ppp + tx_franchise + tx_sales_outlets | 13,398 |
  | dol_5500 | 13,334 |
  | dol_5500 + tx_franchise + tx_sales_outlets | 6,892 |
  | ppp + tx_sales_outlets | 5,812 |
  | dol_5500 + ppp | 4,113 |
  | dol_5500 + tx_sales_outlets | 246 |
  | dol_5500 + ppp + tx_sales_outlets | 107 |

- Sponsors (66,202): 17,064 joined by EIN, 30,807 by name, 884 by the hop, 17,447 alone.
- PPP keys (759,013) by tier: 1: 154,368; 2: 40,401; 3: 11,976; 4: 15,784 (exactly spec 04's counts); 5: 3,810; 6: 828; 7: 958; unmatched 530,888.
- Coverage, after the code-review fixes below: industry 1,856,443; years 4,052,762; lookup address 4,284,708 (every row); likely_open 3,191,802; likely_closed 555,281; unknown 537,625.
- `qc` matched share: 59.4% (214,854 of 361,773 non-individual PPP keys), against spec 04's 58.0%; tiers 5 to 7 add the difference.
- **`qc` floor: `min_rows = 3_000_000`**, about 70% of the first run's 4,284,708.

## Regression against the archived shortlist

The baseline is in the session scratchpad (`baseline05/`), copied before the move below.

- Every one of the 25,842 archived taxpayers is the `registry_id` of exactly one business, with the same `formed_date` (25,842 of 25,842).
- `years_in_business` is the same for 25,804 and higher for 38. All 38 are now dated by a plan that spec 04 could not see: 36 through a sponsor joined by name (1 to 23 years older) and 2 through the hop.
- The consumer query returns **26,630**, which is 25,842 − 16 + 804:
  - **804 new**, every one with a `registry_id`:
    - 404: a PPP key joined the registry business through tiers 5 to 7 (a sponsor joined by EIN), so the business now has `ppp` in `sources`.
    - 368: a sponsor joined by name, and its plan makes the business 30 or older.
    - 32: a sponsor joined by the hop, with the same effect.
  - **16 gone**, every one now holding two or more PPP keys:
    - 7: a second key was charged off (`charged_off` is OR-ed across keys, decision 16).
    - 2: a second key was flagged nonprofit.
    - 7: the PPP NAICS mode across all the business's loans is now an excluded code (813, 814 or 92).

## Merge quality, first hand check

- **20 random businesses with two or more sources: 20 right.** 14 were registry plus outlets by taxpayer number, an exact link. The rest were PPP keys in tiers 1 and 2, a sponsor by name, and a tier-6 sponsor (DY INVESTMENTS INC.). Each had the same name at the same place.
- **20 random `KEY-` businesses: 17 right, 2 missed merges, 1 ambiguous, 0 wrong.**
  - Right: 13 individuals (sole proprietors, self-employed, contractors) with no registry entity, and 4 companies with no franchise row of that name in their ZIP, such as PANDA ASIAN BUFFET INC.
  - Missed: BANIAN HOTEL LLC (PPP at 78112, franchise mailing address 77407) and 360 INTERNET MARKETING LLC (78759 and 78653). Each has exactly one franchise row with the same name in Texas, at a mailing address in another city. The tiers block on ZIP or city on purpose, so these stay two rows. That is the safe direction.
  - Ambiguous: RISE AND SHINE, LLC has two franchise namesakes, in other cities. Correctly unmerged.

## Decisions the spec did not cover

- **The transform is written over contract-shaped tables.** `businesses.sql` first maps the four Texas stages onto `reg` (registry rows), `dba` (trade-name rows), `spon` (sponsors) and `ppp_key` (records). The columns are the ones spec 06's contract names. Every later step reads only those tables, so spec 06 replaces the mapping, not the merge.
- **The tiers are one table macro.** `tiers(l, r)` runs tiers 1 to 3 between any two tables of `(id, state, norm_name, zip5, city, street_no)`. It serves sponsors against registry rows (step 2), records against registry rows (tiers 1 to 3), and records against sponsors (tiers 5 to 7). Every tier compares the state too, which spec 06 needs.
- **A tier's candidates are businesses, not registry rows.** The exactly-one rule counts distinct `business_id`s. In Texas this is the same as counting taxpayer numbers, because each taxpayer is its own business (EINs are unique among franchise rows, verified: 284,322 EINs on 284,322 rows). Where two rows share an EIN (Florida later), they are one business by decision 16, so they are one candidate.
- **The hop has no EIN guard.** Step 2 never joins a sponsor by name to a registry row carrying a different EIN. The hop can, because the product spec's step 5 does not exclude it. On the first run, 260 of the 884 hops went to a business with an EIN. A sample of 15 showed mostly the same business under a typo'd or transposed EIN (752152117 against 751252117, 910198510 against 900198510, 260424871 against 260424371), so the rule stays as written.
- **`marts/_work/members.parquet` records every staged record and its business**: `business_id`, `source`, `rec_id`, `match_tier`, `plan_link`. `qc`'s conservation check reads it, because the business file alone cannot show where every franchise row, outlet taxpayer and sponsor went. Decision 5 allows `_work/`. A consumer can use it to see which records were merged.
- **PPP record ids are `<zip5>|<norm_name>`**, and the leftover `business_id` is `KEY-<zip5>-<norm_name>`. A source whose records share a key gets `<SOURCE>-<rec_id>` instead (decision 16, case 4); no PPP key can, because the key is the grouping.
- **Open-status ties go to activity.** A forfeited franchise row dated by `as_of` and a listed outlet dated by its `as_of` can both fall on 2026-10-10. The listed permit is direct evidence of trading, so activity wins a tie; the sort is `date desc, activity first, evidence`.
- **Evidence strings:** `tx_franchise good standing <date>` (the product spec's form, not spec 05's `right to transact A`, so spec 06 can stay generic), `tx_franchise not in good standing <date>`, `tx_sales_outlets permit listed <date>`, `form 5500 received <date>`, `ppp loan approved <date>` and `ppp loan charged off <date>`. `open_evidence` is also filled for `unknown` rows whose newest signal is an old activity, so a consumer can see why.
- **`plan_link` is NULL for a sponsor that stands alone**, as for a business with no sponsor; `sources` tells them apart.
- **When a business holds several sponsors** (two EINs joined by name to one registry row), the plan columns, `phone` and `plan_link` come from the one that filed last, keyed `(date_received, ein)`. The plan date is the earliest across them.
- **The lookup outlet** is the outlet a PPP key matched in tier 4, else the lowest outlet number, ordered by length and then text, since outlet numbers are unpadded digits ("2" before "10").
- **`lookup_state` for a franchise mailing address is `TX`**, the registry's state. The stage keeps the mailing address's own state, but the contract in spec 06 has no column for it. A few taxpayers mail from another state.
- **`nonprofit` and `charged_off` are NULL for a business with no PPP loan**, which means "not known". The consumer query requires `ppp` in `sources`, so it is unaffected.
- **`ppp_loan_count` is cast to BIGINT**; DuckDB's sum of counts is a HUGEINT, which Parquet stores as DOUBLE.
- **The fixtures** keep every spec 04 case. The second GULF COAST PAINTING taxpayer number changed from 17466666662 to 17476666662: both old numbers embed EIN 746666666, so they were one business under decision 16, which defeated the case's purpose ("two taxpayers in one city").

## By hand, once

- Before the first run, `include/data/marts/matches.parquet` and `shortlist/run_date=2026-10-17/shortlist.parquet` were copied to the scratchpad. Then `matches.parquet`, `shortlist/`, `shortlist_latest.csv` and `shortlist_new_since_previous.csv` were moved, untouched, into `include/data/marts/archive/2026-10-17-texas/` with `mv`.

## Code review (`/code-review high` on the uncommitted diff)

Fixed:
- **`lookup_state` was `TX` for out-of-state mailing addresses.** 396,929 franchise rows mail from another state, and 343,763 businesses used such an address as their lookup with the wrong state. `reg` now carries `address_state` (the franchise stage's `state`), and the lookup uses it. After the fix, 367,063 lookups from `tx_franchise` carry a state other than TX. Spec 06's contract needs the same column; it is recorded there.
- **Right to transact `U` counted as a closure.** `U` means franchise tax not established yet, which new entities have; 45,529 rows carry it, formed as late as 2026-09-23. `active` is now true for `A`, NULL for `U` (no signal), and false for `N`, `I`, `D` and blank. `D` (active but eligible for termination) stays a closure, as Colorado's `Delinquent` will in spec 08. Open status moved from 600,559 to 555,281 likely closed.
- **Evidence dated after `run_date`.** 64 charter dates and 3,581 first-sales dates are in the future (up to 2027-01-06), and 1,294 businesses had an oldest date after `run_date`; a date a year ahead would have made `years_in_business` negative and failed `qc` every day. The `evidence_date` macro now drops both the 1900-01-01 placeholder and any date after `run_date` from the age candidates (so `formed_date` is NULL for a future charter date), a future status date falls back to `as_of`, and signals after `run_date` are ignored. The fixture GOLF START LLC covers both this and `U`.
- **The franchise conservation assertion was untested.** `test_qc_raises_on_a_removed_franchise_taxpayer` now removes a franchise member; the old test, which removes a business row, is kept as `test_qc_raises_on_a_removed_business`.
- **`ppp.discover` kept an unused `data` parameter.** Removed.

Skipped:
- "A franchise closure is dated by `sos_status_date`, so an older PPP loan or plan can outrank a current forfeiture." The spec and product decision 19 date a closure by `status_date`, else `as_of`. Dating every closure by `as_of` would let the registry overrule a 2025 Form 5500 filing, which is newer evidence the business runs. Future status dates, the sharp edge of this finding, are fixed above.
- "The physical and legal lookup branches cannot fire in Texas" and "the shared-key window is always 1 for PPP." Both are spec 06 and 07 paths, written once here so the transform does not change shape later.
- "qc scans the PPP stage twice." About 0.1 s; not a correctness issue.
