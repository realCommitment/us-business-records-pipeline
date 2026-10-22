# 08-registries-ny-pa-co implementation notes

## Downloads and stages (2026-10-17)

| Module | Download | Raw rows | Staged | Stage time |
| --- | --- | --- | --- | --- |
| `states/new_york.py` | 857,664,041 bytes in 5 min 39 s | 4,299,620 | 4,299,620 | 4.5 s |
| `states/pennsylvania.py` | 763,724,091 bytes in 6 min 4 s | 4,174,730 officer rows | 2,376,226 filings | 3.7 s |
| `states/colorado.py` | 695,457,117 bytes in 4 min 6 s | 3,124,420 | 3,124,420 | 4.2 s |

All three came through Socrata's streamed CSV with no HTTP 429. Every sentinel passed: IBM `30059` formed 1911-06-16, Yuengling `0000399042` 1914-04-09, the Manitou and Pike's Peak Railway `19871009071` 1888-11-17.

**Floors:** New York `min_rows = 3_000_000`, Pennsylvania `1_660_000`, Colorado `2_190_000`, each about 70% of the first run. Pennsylvania's `dropped` range is (1,440,000, 2,160,000) around the measured 1,798,504; Colorado has no repeated ids, so `dropped = (0, 0)` stands.

## First-run checks the spec asked for

- **New York:** 350,078 rows have a location ZIP and take it as a `physical` address; the other 3,949,542 use the DOS process address as `legal` (3,868,883 of them have a 5-digit ZIP). CEO names fill 471,965 rows.
- **Pennsylvania:**
  - **No filing's officer rows ever differ** in name, address, city, ZIP, type or creation date, so the per-filing pick (the smallest struct of those fields) loses nothing.
  - 1,340,760 filings list officers; 24,779 filings lose their date to the 1753-01-01 placeholder.
  - **`address_kind` is `physical`, not the spec's default `legal`.** Of 20 random filings, 17 had a place of business or the owner's home (a diner on RR 1 in Gouldsboro, a pizza restaurant on Pine Street in Langhorne, a mower shop on Lancaster Ave in Berwyn), and 3 a registered agent or registered office (600 N 2nd Street in Harrisburg, "C/o Corporation Service Company", a c/o law office). As the spec says, most being a place of business switches it to `physical`. Registered-agent hubs still show: 600 N 2nd Street, Harrisburg holds about 63,000 filings across its spellings, and 5235 North Front Street 37,655.
- **Colorado:**
  - **`Exists` counts as no signal (`active` NULL), not as a closure.** Its 15,659 entities are almost all types Colorado tracks no standing for: domestic limited partnerships 13,782, plus trusts, unincorporated associations and others; 6,902 were formed before 1990. The spec's `active = entitystatus = 'Good Standing'` would have called every one closed.
  - Every other status but `Good Standing` is a closure, dated by `as_of`, since Colorado publishes no status date.

## Results (`smoke__20261017T121033Z`, after the code-review fixes)

- **24,411,925 businesses** (spec 07: 15,074,603). `build` takes 3 minutes 9 seconds with a peak RSS of 26,307 MB; the 24 GB limit spills a little.
- The spec's query:

  | State | Businesses | Registry only | PPP with registry | With formed | With officers | Likely open |
  | --- | --- | --- | --- | --- | --- | --- |
  | CO | 3,256,663 | 3,047,832 | 61,945 | 3,124,420 | 0 | 1,039,711 |
  | NY | 4,760,804 | 4,052,328 | 201,627 | 4,299,613 | 471,965 | 72,660 |
  | PA | 2,606,408 | 2,254,354 | 95,306 | 2,351,445 | 1,340,760 | 37,889 |

- **Matched share of non-individual PPP keys** (`qc`): New York 62.8% (212,722 of 338,957), Pennsylvania 60.5% (100,724 of 166,536), Colorado 57.8% (64,354 of 111,326). Texas is unchanged at 60.1%.
- **PPP keys by tier**, per state (1 / 2 / 3 / 5 / 6 / 7 / none): New York 168,503 / 26,988 / 12,076 / 10,815 / 1,216 / 2,688 / 336,029; Pennsylvania 81,758 / 7,863 / 8,007 / 6,026 / 367 / 1,291 / 167,162; Colorado 52,709 / 7,439 / 3,399 / 2,740 / 408 / 353 / 86,650. Nationally, sponsors joined by name rose from 35,728 to 143,261 and by the hop from 1,177 to 2,232.
- **`age_source`**: New York formed 4,284,718, ppp_loan 336,260, sba_loan 73,373, plan 66,070, none 383; Pennsylvania formed 2,342,944, ppp_loan 167,251, sba_loan 38,709, plan 32,693, none 24,811 (mostly the 1753 placeholder); Colorado formed 3,119,981, ppp_loan 86,290, sba_loan 32,757, plan 17,619, none 16.
- **`open_status`**: New York unknown 4,636,532, likely open 72,660, likely closed 51,612; Pennsylvania unknown 2,547,513, likely open 37,889, likely closed 21,006 (both registries give no signal, by design); Colorado likely closed 2,084,838, likely open 1,039,711, unknown 132,114 (Delinquent and dissolved entities are closures).
- **Spot checks against the row APIs**, two per state, 30 or more years old, joined in tier 1:
  - New York `1785112` MARTY Z, INC.: ours formed 1994-01-06, CEO MARTIN ZWIERZCHOWSKI. API: `initial_dos_filing_date` 1994-01-06, `chairman_name` MARTIN ZWIERZCHOWSKI, location ZIP 14221.
  - New York `1278217` RUSSO'S MOZZARELLA & PASTA CORP.: ours 1988-07-19, CEO GIACOMO CANGEMI, joined through the DOS process ZIP. API: 1988-07-19, GIACOMO CANGEMI, no location ZIP, process ZIP 10003.
  - Pennsylvania `0000305919` The Ridley Park Presbyterian Church: ours 1970-06-18, six officer entries. API: six rows, `creationdate` 1970-06-18, Ridley Park 19078-0.
  - Pennsylvania `0000684945` Klick-lewis, Inc.: ours 1955-09-29, officers PAT LEWIS and PATRICK LEWIS. API: two rows, 1955-09-29, Palmyra 17078.
  - Colorado `19871267949` VIC LEFFLER & SONS, INC.: ours 1974-01-30, Good Standing. API: 1974-01-30, Good Standing, ZIP 80615.
  - Colorado `19931048953` Gary L. Coats, PhD, PA: ours 1993-05-10, Good Standing. API: 1993-05-10, Good Standing, ZIP 80123.
- **Compared with spec 07's file** (saved before the first run; the Texas files did not change in between):
  - Outside NY, PA and CO, 13,787,243 of 13,788,051 rows are unchanged. The other 808 are Texas businesses that lost a record filed in one of the three states: 823 PPP keys and 95 SBA borrowers that had reached a Texas business's sponsor through tiers 5 to 7 now fit their own state's registry in tiers 1 to 3, which rank first. One New Jersey PPP key followed its same-key SBA borrower into a New York registry business, which removed `KEY-10977-OBILO PEDIATRIC ASSOCIATES`.
  - Inside them, 823,469 of 1,286,552 former rows are unchanged, and every one of the 463,083 others had a record join a NY, PA or CO registry business.
- 164 Colorado rows keep a ZIP while their state code is not a US one, because their country is blank.
- **Second run** (`smoke__20261017T121501Z`): all 58 downloads log `unchanged`, and `sha256sum include/data/marts/businesses.parquet` is `3048934d13410cb49d510f19eae5254dd4286916ce4b5b9f71b2d222efddf85b` after both runs.

## Decisions the spec did not cover

- **`min_match_share`** is set from the first run to about two-thirds of each state's measured share: New York 0.44 (measured 62.8%), Pennsylvania 0.42 (60.5%), Colorado 0.40 (57.8%). Texas keeps the product spec's 0.30.
- **`address_state`** (spec 06's contract addition) is the location or process state in New York, the filing's state in Pennsylvania and the principal state in Colorado.
- **New York's `ny_ceo_address`** is the CEO address parts joined with commas, as published: for IBM, `CEO Address 1` holds the name again ("ARVIND KRISHNA, ARMONK, NY, 10504").
- **The unit tests override Pennsylvania's `dropped` range** with `dataclasses.replace`, because 8 fixture rows cannot fall in a range set for 4.2M.
- **The businesses test now stages only its own sources** (Texas and the IL fixture), by replacing `states.SOURCES` for the test, since `build` reads every module's stage file.

## Code review (`/code-review high` on the uncommitted diff)

Fixed:
- **Pennsylvania's registered-agent offices were tagged as places of business**, so their address became the lookup for tens of thousands of businesses (600 North Second Street, Suite 401 in Harrisburg alone for 39,112). An address that 1,000 or more filings share (18 addresses, 159,927 filings on 2026-10-17) or any `c/o` address (32,589 filings) is now `legal`; the rest stay `physical`. The 100-to-999 range was left `physical`: it mixes agent addresses with office buildings such as 1700 Market St. The fixture's AAA ENTERPRISES, INC. at "C/o C T Corporation System" covers it.
- **Colorado foreign postal codes became ZIPs**: 3,237 rows with a non-US country had 5-digit codes such as Munich's 80331. `zip5` is now set only when the country is `US` or blank.
- **A NULL Colorado status would have been a closure.** It is now NULL, no signal. No row has one today.
- **New York rows with a location ZIP but no location street** (2 rows) took a NULL address and lost their process address. The location now counts only with both.
- **Colorado's docstring** said every pre-1987 entity has a 1987 prefix; 18861217679 (formed 1886) does not. The docstring now says renumbered entities carry it. The sentinel's name in the file is "MANITOU AND PIKE'S PEAK RAILWAY COMPANY", without the "THE" that `docs/data-sources.md` gives; the fixture row is copied from the file.
- `nullif(officers, [])` was redundant and is gone; the businesses test takes its source list from the fixture module instead of naming Texas sources.

Skipped:
- "A Colorado closure dated by `as_of` beats a Form 5500 filed last month" (256 Delinquent businesses with a 2025-10 or later filing are likely closed). The spec makes `Delinquent` a closure dated by `as_of` on purpose, as the publisher's own judgment at the export date.
- "One `zip5` helper for every state": the Texas rule would change Texas data; cleanup only.
- "Unit-test assertions without messages": the existing tests follow the same pattern; the rule is kept in pipeline code.
