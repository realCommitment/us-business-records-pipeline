# 11-registries-or-ct-dc implementation notes

## Downloads and stages (2026-10-18)

| Module | Download | Raw rows | Staged | Stage time (host) |
| --- | --- | --- | --- | --- |
| `states/oregon.py` | 499,153,837 bytes in 116 s | 1,582,772 name rows | 567,506 entities | 2.4 s |
| `states/connecticut.py` | Business Master 484,231,060 bytes in 95 s; Principals 441,322,748 bytes in 78 s | 1,303,289 businesses, 1,796,991 principals | 1,303,289 | 35 s |
| `states/district_of_columbia.py` | 163,063,691 bytes in 27 s | 505,487 | 505,482 | 1.5 s |

The files were first downloaded by `download_if_changed` itself on the host, into their raw paths with their sidecars, while spec 10's runs were going; the DAG then found them unchanged. Every sentinel passed: Pendleton Woolen Mills `1333616` formed 1909-02-16, Stanley Black & Decker `0074441` 1901-06-04, Washington Gas Light `571294` 1957-03-25.

**Floors:** Oregon `min_rows = 397_000`, Connecticut `912_000`, DC `353_000`, each about 70% of the first run. Oregon's `dropped` range is (812,000, 1,219,000) around the measured 1,015,266.

## Oregon

- **The four associated name types are all there is,** but no entity has all four: 443,265 entities have three rows (principal place, mailing address, registered agent), 121,356 have two (an assumed business name's principal place and authorized representative), and a few thousand have more, with a type repeated (a second registered agent on 1,783 entities, a second authorized representative on 946). The fixture's "one entity on four rows" is ROMAN CATHOLIC ARCHBISHOP OF PORTLAND IN OREGON (461913, 1874): two registered agents, a mailing address and a principal place.
- **Name, entity type, registry date, jurisdiction and details never differ within an entity** (checked on every entity), so `min()` is the deterministic pick. A repeated principal place or mailing address (8 and 3 entities) takes the smallest row as one struct.
- **116,581 entities are `ASSUMED BUSINESS NAME`** (registered trade names). The spec makes every entity a registry business and stages no filter, so they stay registry rows, with their authorized representative as the officer.
- 108 entities have neither a principal place nor a mailing address; they take `address_kind = 'mailing'` with no address. 5,000 use their mailing address. 346 principal places carry a Canadian postal code and get no ZIP; 31 in Puerto Rico and the Virgin Islands keep theirs, with the state spelled out as published.
- **Officers:** 93,234 entities. A person-name row that is not the registered agent becomes `<type>: <first> <last>`; a company as authorized representative (24,595 rows) is not a person and is left out. `or_registered_agent` is the agent's person name, else the company of record.

## Connecticut

- **`Unique_Key` equals Business Master's `Id`**: Stanley Black & Decker's `Id` 001t000000WmVHCAA3 carries its 27 principals. **1,742,776 of 1,796,857 named principals join a business**; 1,048,931 businesses have officers. 84% of principals have no `Designation`; they are listed by name alone.
- **Account number `0000000` is a placeholder shared by 24 businesses** (unregistered "Unauthorized" companies such as SALSCO, LLC and Diplomat Pharmacy, and `NAME NOT FOUND` stubs), which would break the unique `registry_id`. They keep their `Id` as `registry_id` instead; every other business keeps its account number.
- **`Dissolution_date` is `MM/DD/YYYY hh:mm:ss AM`**, not a plain date; 317,997 businesses have one.
- **NAICS:** 605,424 codes in parentheses, as the spec says, and 13,033 bare six-digit codes such as `551112`, which are taken too. 133 other values (an unclosed parenthesis, a seven-digit code) give no code. 618,456 businesses have one.
- **ZIPs:** `Business_Country` is free text with typos ("UNTED STATES", "UNITEF STATES"), and Mexico and Germany also use five-digit postal codes. A foreign address has no `Business_State`, so a five-digit ZIP counts only when the state is set: 1,059,482 ZIPs; 171 five-digit codes without a state are left out.
- `Date_Registration`'s `01/03/0001` placeholder is on 18,514 rows (reservations and stubs). The earliest real date is 1701-10-09.
- Statuses: Active 464,780 (the spec counted 464,565 on 2026-10-17), Forfeited 357,126, Dissolved 320,252 and 23 others.

## District of Columbia

- **The header now starts with `OBJECTID`**; `docs/data-sources.md` lists it near the end. `File.header` is the header as served.
- **`DCS_LAST_MOD_DTTM` is 2026/10/16 07:48:03 on every one of the 505,487 rows**, the export's load time, not a status change. `status_date` stays NULL, so closures are dated by `as_of`, as the spec says.
- **`SUFFIX` is empty on every row**; `MODELTYPE` ("Domestic Limited Liability Company") is the entity type.
- **Five file numbers are listed twice** (505,482 distinct), as two rows of one entity: usually a Revoked row and an Active one (FireAlarmService.net, Ritter Mortgage Group, PBD Consulting Service), and once a rename (MacKat Logistics LLC and Little Miner Taco Commissary, LLC). The stage keeps the row that filed a report last (`DATE_LAST_REPORT_FILED`), then the highest `OBJECTID`, so `dropped` is set to (0, 50) around the measured 5, not the spec's (0, 0).
- **`FOREIGN_DATEOF_ORGANIZATION`** has `EFFECTIVE_DATE`'s format (`YYYY/MM/DD HH:MM:SS+00`) and is set on 366,521 rows. One holds the placeholder 1753-01-01, which becomes NULL; 567 hold 9999-12-31, which `least()` passes over. 78,957 foreign entities date from their own formation, before their DC registration. The earliest `EFFECTIVE_DATE` is 1791-02-25.
- `BUSINESS_COUNTRY` is `USA` or blank for most; 220,642 rows have no business address at all. A ZIP counts when it has five digits and the country is `USA` or blank: 282,527.

## Results (`smoke__20261018T001627Z`)

- **The DAG's daily run got in the way first.** `scheduled__2026-10-18T00:00:00+00:00` started at 00:07 UTC while I registered the three states: its `build` ran on the old state list and its `qc` on the new one, which failed correctly ("or_active_businesses has 0 memberships of 0 records, expected each of the 567506 staged ... exactly once"). With `max_active_runs=1` the smoke run waited behind its retries, so I marked that run failed through the API; the smoke run then started at 00:19.
- The run took 810 s; all ten state files logged `unchanged`. **39,673,571 businesses** (spec 10: 37,431,961). `build` 5 min 42 s, peak RSS 35,158 MB at the 32 GB limit.
- **Matched share of non-individual PPP keys:** Connecticut 71.1% (45,448 of 63,941), DC 75.9% (10,130 of 13,338), Oregon 60.2% (38,645 of 64,148); the other five are unchanged. **Floors: CT 0.47, DC 0.50, OR 0.40**, about two-thirds of each.
- PPP keys by tier: 1 782,242; 2 128,346; 3 64,131; 4 15,754; 5 397,779; 6 44,387; 7 60,937; none 7,699,099. Sponsors joined by name rose from 142,026 to 174,751 and by the hop from 2,725 to 2,929.
- **Connecticut principals:** 1,742,776 of 1,796,857 named principals joined a business, 1,633,785 distinct per business after the review fix; `with_officers` sums to 1,048,931 in the query below, the stage's count.
- **The spec's query:**

  | State | open_status | Businesses | PPP with registry | With formed | With officers |
  | --- | --- | --- | --- | --- | --- |
  | CT | likely_closed | 841,210 | 9,707 | 819,206 | 595,563 |
  | CT | likely_open | 470,871 | 34,584 | 464,479 | 452,319 |
  | CT | unknown | 55,750 | 373 | 1,090 | 1,049 |
  | DC | likely_closed | 389,375 | 3,306 | 387,297 | 0 |
  | DC | likely_open | 120,964 | 6,630 | 118,024 | 0 |
  | DC | unknown | 13,550 | 0 | 0 | 0 |
  | OR | likely_closed | 4,336 | 0 | 0 | 0 |
  | OR | likely_open | 574,519 | 37,896 | 567,506 | 93,234 |
  | OR | unknown | 66,677 | 0 | 0 | 0 |

  Every Oregon registry business is `likely_open` (the list holds active entities only, dated by `as_of` 2026-10-13); the Oregon `likely_closed` and `unknown` rows are businesses with no Oregon registry row.
- **Spot checks against the row APIs**, two per state, 30 or more years old, joined in tier 1:
  - Oregon `17873399` MARK JONES TRUCKING, INC. (`dol_5500 + or_active_businesses + ppp + sam`, 43 years from an older plan or SAM date): ours formed 2003-10-20, ZIP 97470. API: DOMESTIC BUSINESS CORPORATION, `registry_date` 2003-10-20, three rows (registered agent KATHARINE JONES, mailing address, principal place), ZIP 97470.
  - Oregon `2262889` WEGNER CREEK RANCH (`or_active_businesses + ppp`): ours formed 1986-02-27, officers `AUTHORIZED REPRESENTATIVE: JOHN ETTER`, ZIP 97868. API: ASSUMED BUSINESS NAME, 1986-02-27, authorized representative JOHN ETTER, ZIP 97868.
  - Connecticut `0214269` NEW HAVEN MASONRY & BUILDING SUPPLY, INC. (`ct_businesses + dol_5500 + ppp`): ours formed 1988-02-25, Active, 355 JAMES ST, New Haven 06513, officers ANDREW CONSIGLIO III and ELISA M. CONSIGLIO. API: Active, `date_registration` 1988-02-25, Stock; the API names the business address `billingstreet` 355 JAMES ST, `billingcity` NEW HAVEN, `billingpostalcode` 06513.
  - Connecticut `0201262` EAST LYME RENT-A-SPACE, INC. (`ct_businesses + ppp`): ours formed 1987-06-01, Active, ZIP 06357. API: Active, 1987-06-01, Stock.
  - DC `710278` B & W STAT LABORATORY Inc. (`dc_corporations + dol_5500 + ppp`): ours formed 1971-02-04, Active - In Good Standing, ZIP 20010. API: `EFFECTIVE_DATE` 34491600000 ms (1971-02-04), Active - In Good Standing, ZIP 20010. Its lookup name `B &AMP; W STAT LABORATORY INC` comes from PPP, as published there.
  - DC `961642` CHEVY CHASE PRESBYTERIAN CHURCH (`dc_corporations + ppp`): ours formed 1908-08-31, 118 years, ZIP 20015. API: `EFFECTIVE_DATE` -1935601200000 ms (1908-08-31 in Washington's time), ZIP 20015.
- **Outside OR, CT and DC, against spec 10's file** (rows hashed without `run_date`, `years_in_business` and `open_status`, since this run's date is 2026-10-18 and spec 10's 2026-10-17): 37,134,960 rows unchanged, none gone, none new, **1,359 changed** (915 in Florida, 444 in Texas). Each lost a record to a new registry: 1,300 PPP keys, SAM records and SBA borrowers that had reached a Florida or Texas business's sponsor through tiers 5 to 7 now fit an OR, CT or DC registry business in tiers 1 to 3, which rank first (as spec 08 saw for Texas). So the spec's "every row is unchanged" does not hold exactly; the difference is the tier order working as decided.

## After the code-review fixes (`smoke__20261018T003844Z`, then `smoke__20261018T005216Z`)

- **39,673,571 businesses**, matched shares as above. `build` took 8 min 49 s at a peak RSS of 37,997 MB, then 6 min 46 s at 37,029 MB.
- Both runs log `unchanged` for all 64 downloads, the four new files among them: DC's weak ETag did not change within the data day. `sha256sum include/data/marts/businesses.parquet` is `633a84ae8a87c50ae10263ab9cc204e83413f5dad0359a995b053ce9a09b29b2` after each.
- A run in between (`smoke__20261018T003319Z`) was started before the fixes, had two tasks fail on an Airflow API error ("409 Unique constraint violation", not the pipeline's), and was marked failed and replaced by these two.

## Code review (`/code-review high` on the uncommitted diff)

Fixed:
- **Connecticut listed a principal twice when the Principals file does**: 72,978 businesses had a repeated officer. The list is now distinct, as Oregon's and Pennsylvania's are: 1,633,785 officer entries instead of 1,742,776.
- **Spelled-out address states reached `lookup_state`.** Oregon's 26 Puerto Rico and 5 Virgin Islands addresses now carry `PR` and `VI`; its 368 Canadian provinces keep their names, since they have no US code. Checking the other two found **DC's placeholder `NotSet`** on 1,373 business states, now NULL. Connecticut's free-text state is left as published: about 200 rows spell it out, typos included ("CONNETICUT" 35).

Skipped:
- "Connecticut's `active` ignores `Sub_status`" (Active businesses with 'Annual report past due' 65,346, 'Admin Dissolution Initiated' 27,425): the spec sets `active = Status = 'Active'`; `ct_sub_status` carries the sub-status for anyone who wants it.
- "Oregon's 116,581 assumed business names would be better as a `dba` source linked to the entity that files them": that changes the data model the spec fixed (every entity a registry business), so it is left for the owner. About 24,595 authorized-representative rows name an entity of record, which a `dba` source could link through.
- "Oregon's `active = true` can never give a registry closure": the spec's choice; the dataset holds active entities only.
- "Connecticut name reservations become businesses" (Expired Reservation 12,219, Reserved 1,000): the spec stages every status, as for spec 08.
- "DC's dedupe drops a renamed row's other name" (one pair: MacKat Logistics LLC and Little Miner Taco Commissary, LLC): one entity; the kept row is the one that filed last.
- "`status_date` is set on 1,405 Active Connecticut businesses with an old dissolution date, and `ct_dissolution_date` repeats it": the spec asks for both; a registry closure uses `status_date` only when the business is not active, so open status is not affected.
- "The timestamp format is written out three times" and "Connecticut's read loads every column": maintenance and memory the three stages do not need (3.6 GB RSS for all three on the host).
