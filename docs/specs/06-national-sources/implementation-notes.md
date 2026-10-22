# 06-national-sources implementation notes

## Real data, first full run (2026-10-17)

- The first run downloaded 26 more Form 5500 zips; `raw/dol/` is now 12 GB with the extracted CSVs.
- `ppp_stage`: 11,467,847 loans in 9,192,675 `(norm_name, zip5)` keys across 59 state codes; 363 dropped, exactly the planning count.
- `dol_stage`: 14,653,616 filings from 1,627,361 sponsor EINs over 17 form years (2009 to 2025), in 18 seconds. **Floor: `min_rows = 10_250_000`**, about 70% of the first run.
- **The first `build` ran out of memory** ("failed to pin block of size 256.0 KiB (7.4 GiB/7.4 GiB used)"), in `ppp_agg`, which aggregates 9.2M keys with several struct-keyed `arg_max` states. Applying decision 5:
  - `build` runs on a work database, `marts/_work/build.duckdb`, so its tables can be evicted to disk, with `temp_directory` at `marts/_work/tmp`. The file is deleted before and after every build. The SQL's tables are therefore plain tables, not temp tables.
  - `preserve_insertion_order = false`: the output is written with an explicit `order by business_id`.
  - `threads = 4`, which holds fewer aggregate states at once. Each change alone was tried on the host first: neither the work database nor `preserve_insertion_order` was enough without fewer threads.
  - `connect()` takes an optional database path for this.

- **Final run** (`smoke__20261017T094811Z`, then `smoke__20261017T095321Z`): the DAG takes about 4 minutes when nothing downloads; `build` 3 minutes at a peak RSS of 10,378 MB.
- **13,630,650 businesses** in 63 state codes: all 50 states and DC, plus PR, GU, VI, MP, AS, FM and the junk codes `AA`, `AE`, `AP` and `FI` that PPP and Form 5500 carry.
  - By source: ppp 8,355,925; tx_franchise 2,868,855; dol_5500 957,448; dol_5500 + ppp 580,904; tx_franchise + tx_sales_outlets 353,177; tx_sales_outlets 243,857; ppp + tx_franchise 102,682; ppp + tx_franchise + tx_sales_outlets 74,780; dol_5500 + tx_franchise 33,327; dol_5500 + ppp + tx_franchise 26,225; dol_5500 + ppp + tx_franchise + tx_sales_outlets 16,479; dol_5500 + tx_franchise + tx_sales_outlets 10,660; ppp + tx_sales_outlets 5,785; dol_5500 + tx_sales_outlets 385; dol_5500 + ppp + tx_sales_outlets 161.
  - `age_source`: ppp_loan 8,480,418; formed 3,201,863; plan 1,449,254; first_sales 270,927; none 228,188.
  - `naics_source`: ppp 9,065,886; dol_5500 997,931; tx_sales_outlets 597,656; tx_franchise 458,102; none 2,511,075.
  - `open_status`: unknown 8,474,394; likely_open 4,075,352; likely_closed 1,080,904. Outside Texas most businesses are known only from a 2020 or 2021 PPP loan, so they are `unknown`, as decision 19 says.
- Sponsors (1,626,581 with a US address): 51,381 joined by EIN, 35,746 by name, 1,102 by the hop, 1,538,352 alone.
- PPP keys by tier: 1 154,368; 2 40,401; 3 11,976; 4 15,784 (unchanged from spec 05); 5 486,801; 6 54,504; 7 72,916; unmatched 8,355,925.
- `qc` TX matched share 60.1% (217,435 of 361,771).
- **749 sponsor EINs never filed with a US address** (their US address fields are empty; the filings come from abroad). They are not US businesses and stay out of the merge; conservation counts the 1,626,581 EINs that filed with a US state at least once. 436 more had their latest filing from abroad and take the address of their latest US filing. The first run's `qc` caught this: 1,185 businesses without a state.

## Texas regression against spec 05's file

- All 3,736,373 Texas businesses with a `registry_id` are present under the same `business_id`, with the same `registry_id` and `formed_date`.
- `match_tier` is the same for 3,726,028. 10,304 gained a tier 5 to 7 PPP key, because a national sponsor joined the business (most often by EIN from another state) and a PPP key fits that sponsor. 39 lost a tier 5 to 7 key, and 2 moved from tier 5 to 7, when the sponsor's latest filing moved.
- `years_in_business` is the same for 3,710,583 and higher for 25,699: 25,509 through an older plan, and 190 that had no date and gained a PPP loan.
- **91 are lower or lost their age**, against the spec's "same or higher". Each lost a sponsor it had in spec 05: 179 name links and 61 hops broke, because the sponsor's latest filing, whose address the spec makes the sponsor's, is now a 2025 filing from another state or ZIP. Examples: VGCIT (latest filing CA 91343, earlier TX 75080), DATAWORLD (CA 95054, earlier TX 78701), ATSER (ZIP 77060, earlier 77030). Some are filing errors, such as SDOST ENTERPRISE with state CA and the Texas ZIP 76034. The rule stays as the spec wrote it.
- **New Texas rows**: 22,679 sponsor-only, 2,429 sponsor plus PPP, and 171 PPP-only. Of the 25,108 sponsors behind them, 25,057 are new to Texas (not in spec 05's 2022 to 2025 Texas set) and 51 moved out of a spec 05 business as above. The 2,514 PPP keys in the new rows were `KEY-` businesses that now join their new sponsor; 188 more moved between sponsor businesses. The 171 PPP-only rows are keys that a sponsor no longer fits. One spec 05 sponsor-only row and 3,018 `KEY-` rows are gone, absorbed by those joins.

## Merge quality outside Texas

- **20 random businesses with two or more sources: 20 right.** All are a sponsor and a PPP key: 16 in tier 5, 2 in tier 6, 1 in tier 7 (JEFFRY GARDNER DDS LLC against JEFFRY P. GARDNER, DDS, LLC, similarity 0.936), and one in tier 5 through a sponsor DBA (RENSHA CORP DBA JAVA CAT).
- **20 random `KEY-` businesses: 20 right.** 14 are individuals; 6 are companies (RED RIVER PRINTING CORP., DAC REALTY, INC. and others) with no sponsor of that name in their state. None of these states has a registry yet.

## The Airflow UI

The API the UI reads (`/api/v2/dags`) lists `retiring_owners`, not paused, not stale, no import errors, with its latest run `success`. `tx_retiring_owners` was paused before the move and is stale now that its file is gone, so the UI no longer lists it.

## Second run

`smoke__20261017T095321Z`: all 49 downloads (13 PPP, 2 Texas, 34 Form 5500) log `unchanged`, and `sha256sum include/data/marts/businesses.parquet` is `ba6633f56be92e69585ee45db55123d1b1fe69ad52a374096e33ccd25178b554` after both runs.

## Decisions the spec did not cover

- **`REGISTRY_COLUMNS` gains `address_state`**, the address's own state, NULL meaning the registry's state. It carries spec 05's code-review fix: 396,929 Texas franchise taxpayers mail from another state, and without it their lookup address would be labelled TX. The lookup uses `coalesce(address_state, state)`; matching still uses `state`, so tiers never cross a state line.
- **The contract lives in `states/__init__.py`, which imports the state modules at its end** (after `File`, `Source` and `mdy` are defined), because the modules import those names from the package. ruff's E402 is silenced on that one line.
- **`Source.download` and `Source.read` take the data directory** as their `Path` argument; `read` finds the file with `raw_path(state, file, data)`.
- **"Two sources of one state may not output the same extra name" is not enforced.** Spec 12 gives Virginia's three registry sources the same four extras (`va_industry_code` and so on), which `union_by_name` lines up correctly. The one real collision, a registry and a trade-name source of one state sharing an extra, is not possible today (Texas's are disjoint) and would show as a duplicate column in `build`.
- **Extras in the output**: registry extras come after `registry_officers` in the Registry group, and trade-name extras after `outlet_count`, each from the row the business's other registry or trade-name columns come from. So `tx_sos_file_number`, `tx_right_to_transact` and `tx_sos_status_date` keep their spec 05 names, and Texas businesses also gain `tx_record_type`, `tx_responsibility_begin_date`, `tx_exempt_reason`, `tx_county_code`, `tx_outlet_number`, `tx_permit_issue_date` and `tx_taxpayer_name`. `tx_sos_status_date` stays an extra beside the contract's `status_date`, so spec 05's column survives.
- **`registry_officers`** is a new output column, the registry's `officers`; specs 08 and 10 query it by that name.
- **The lookup trade name** is the one a record matched in tier 4, else the earliest by `first_seen_date`, then name and address. Spec 05 used the lowest Texas outlet number, which the generic transform cannot name. The trade-name NAICS comes from the same ordering, among names that have one.
- **`names` no longer includes the outlet taxpayer's legal name**; it is in the extra `tx_taxpayer_name`. A Texas sole proprietor's name, such as MARIA LOPEZ, is therefore no longer in `names` unless a PPP loan carries it.
- **Evidence text** for a trade name is `<source> listed <date>` (spec 05: `permit listed`), since "permit" is Texas's word.
- **Per-state match floors**: each registry state's floor is the smallest `min_match_share` among its sources. `qc` takes `match_floors` to override them, which the test uses; the old global `min_match_share` argument is gone.
- **Trade-name conservation counts distinct `registry_id` per trade-name source**, which is one state's taxpayers.
- **Spec 05's shortlist consumer query needs `state = 'TX'`** now that the file is national; the unit test's copy has it.

- **A sponsor joins a registry entity by exact EIN in any state**, not only its own as the spec says. The registry entity and the sponsor would carry the same `EIN-<ein>` business_id anyway, so the first run merged them by id while `plan_link` stayed NULL, and the out-of-state sponsor could also be joined by name to some other entity of its own state. 28,055 sponsors file from outside the state of their EIN's registry entity (51,381 EIN links against 23,326 when the state had to match). Name tiers 1 to 3 still match only within the sponsor's state.
- **Right to transact `U` is NULL, not false.** Spec 06 says `active = coalesce(right_to_transact = 'A', false)`; spec 05's code review changed it (see spec 05's notes), because `U` means franchise tax not established yet. `N`, `I`, `D` and blank are false.
- **`as_of` falls back to the download time**, as the contract says, and logs it, so the fallback is visible. Iowa (spec 12) sends no `Last-Modified`.

## Code review (`/code-review high` on the uncommitted diff)

Fixed:
- **The lookup trade-name pick was not deterministic.** Without the Texas outlet number, 204 Texas groups tied on the ordering key, and 53 of them differ in city, ZIP or permit date. The key now ends with the whole row as text, so a tie is between identical rows.
- **`reg_agg` and `dba_agg` mixed `min()` with `arg_min()`**: once an EIN merges registry rows of two states, the state could come from one row and the registry id and address from another. State, source and registry id now use the same key as the other columns.
- **On a failed build, the connection stayed open and the spill directory stayed on disk.** `build` now opens the work database with `with` and removes `marts/_work/tmp` afterwards.
- **`plan_count`**, a distinct count over 14.6M filings that nothing read, is gone.
- The two spec deviations it flagged, the national EIN link and `U`, are recorded above.

Skipped:
- "`as_of` falls back silently": the contract specifies the fallback; it now logs.
- "Five stage tasks with 8 GB each could exhaust an 8 GB machine": this machine has 56 GB, and decision 5 fixes three mapped stages. The comment in `db.py` now says five.
- "`names` lost the trade-name taxpayer's legal name": recorded above; a contract column for it would be a spec change.
- "The extras lambda is repeated four times": maintenance only.

## For the owner to delete

These stage files are no longer written or read: `include/data/stage/ppp_tx.parquet`, `include/data/stage/dol_5500_tx.parquet`, `include/data/stage/tx_franchise.parquet` and `include/data/stage/tx_sales_outlets.parquet`.
