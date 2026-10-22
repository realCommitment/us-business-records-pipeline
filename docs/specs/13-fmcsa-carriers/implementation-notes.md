# 13-fmcsa-carriers implementation notes

## Download and stage (2026-10-18)

- **Download:** `download_if_changed` itself, run on the host while spec 11's runs were going, into `raw/fmcsa/fmcsa_census.csv` with its sidecar: **1,702,950,902 bytes in 2,015 s** (33.6 minutes, about 0.85 MB/s), the largest Socrata export. HEAD gives `ETag` and `Last-Modified: Sat, 17 Oct 2026 10:19:13 GMT`, with `Content-Length: 0`; the GET streams with no length either, so the size cannot be checked against a header. `fmcsa_download` has a 2-hour timeout.
- **The header as served equals `docs/data-sources.md` section 9.** No byte-order mark.
- **Stage:** **4,518,655 carriers**, every `dot_number` unique: `A` 2,241,932, `I` 2,275,378, `P` 1,345 (planning counted 4,518,028 on 2026-10-16). 4,423,399 have `PHY_COUNTRY = 'US'`, 67,571 Canada, 27,248 Mexico. All `ADD_DATE`s and `MCS150_DATE`s parse as `YYYYMMDD` (595,220 carriers have no MCS-150 date); `POWER_UNITS`, `TRUCK_UNITS` and `TOTAL_DRIVERS` are whole numbers. Staged in 3.8 s on the host. **Floor `min_rows = 3_160_000`**, about 70%.
- **Sentinel:** USDOT 1, FEDERAL MOTOR CARRIER SAFETY ADMINISTRATION, added 1974-06-01, in Washington DC 20590, with the test officer `john mary`.
- `CLASSDEF` holds every class a carrier has, joined by `;`: "AUTHORIZED FOR HIRE" 2,016,294, "PRIVATE PROPERTY" 1,466,146, and their combinations; 2,615,738 include "FOR HIRE" (which also matches "EXEMPT FOR HIRE"). 85,639 active US carriers were added before 1997 (planning counted 87,010 with another filter).
- **A ZIP is a US carrier's only**: a Mexican postal code also has five digits. 67 US carriers have no usable ZIP.

## Decisions the spec did not cover

- **Two US carriers have no state** (9772871 EPIC NORTH TOUR EXPERIENCES INC. in Whitehorse, Yukon, and 3362478 TUTTLE SHUTTLE TEST LLC, a test record). A business needs a state (`qc` asserts it), so a carrier enters the merge only when it is in the US and has a state; the others are staged, and `qc`'s conservation counts the same set. A fixture carrier without a state covers it.
- **"Joined to a PPP key through its DBA"** happens through the registry: the carrier's DBA fits, in tiers 1 to 3, the registry business the PPP key also joined. Step 4 groups leftovers by the legal name, as the spec says, so a carrier whose only link to a PPP key is its DBA, with no registry business between them, stays apart. The fixture is TANGO FREIGHT LLC: a Texas franchise taxpayer with a PPP loan, and a carrier whose legal name is its owner's (TOMAS ORTEGA) and whose DBA is the company.
- **The descriptive FMCSA columns come from the carrier that filed its MCS-150 last** (a carrier with no MCS-150 date counts as the oldest), the add date is the earliest, the officers are every distinct name of both officer fields, and `484` applies when any of the business's carriers is for hire. Each carrier gives its own open-status signal; the newest decides, as for every source.
- **Activity is dated by `evidence_date(MCS150_DATE)`**: an active carrier with no MCS-150 date gives no activity signal; an inactive one is a closure dated by `as_of`.
- **`lookup_name`**: FMCSA's DBA comes after SAM's and before the Form 5500 DBA; its legal name after SAM's legal name and before the registry name, as decision 20 orders them. `state` falls back to the carrier's state last.

## Results (`smoke__20261018T023105Z`)

- The run succeeded in 1,470 s; `fmcsa_download` logged `unchanged fmcsa_census.csv`, and `fmcsa_stage` staged 4,518,655 carriers (4,423,399 in the US).
- **`build`'s first attempt was killed by Airflow, not by the pipeline**: "Server indicated the task shouldn't be running anymore. Terminating process" at 02:42:29, 8 min 40 s in. The scheduler's log shows why: its own heartbeat stalled for 30 to 37 s at a time while the build used all 10 cores ("Heartbeat recovered after 33.75 seconds"), the API server took 30 to 36 s to answer the task's heartbeats ("Failed to send heartbeat ... ReadTimeout"), and at 02:42:29 it "Marked 1 SchedulerJob instances as failed", past the 30 s scheduler health check, so the build it had started was reset as orphaned. The second attempt ran 11 min 43 s to the end.
- **Fix: a task process lowers its CPU priority to nice 10 when it opens a DuckDB connection** (`os.setpriority` in `db.connect()`, before DuckDB starts its threads, which inherit it; first written in `build` alone, moved after the second run below). DuckDB still uses every idle core, so nothing is throttled while Airflow is idle, but the scheduler, the API server and Postgres get the CPU when they need it. uid 1000 may lower its priority in the container (checked).
- **44,793,512 businesses** (spec 12: 41,379,358); `build` peak RSS 37,197 MB at the 32 GB limit.
- **FMCSA records by tier:** 1 476,851; 2 43,028; 3 30,464; 4 4,782; 5 109,895; 6 11,988; 7 12,068; none 3,734,321 (these group by key or stand alone; a key two carriers share keeps both as `DOT-`).
- **The spec's query:** with_carrier 4,392,968; carrier_only 3,416,203; with_officers 3,775,666; dated_by_fmcsa 3,782,127; address_from_fmcsa 4,392,968 (FMCSA's physical address is first in the lookup order, and every merged carrier has one).
- **Businesses with NAICS starting `484` that gained a carrier: 2,393,671** (of 2,671,193 with a 484 code; spec 12 had 373,173). 2,298,079 take `484` from FMCSA itself, as the last industry source; **95,592 had a 484 code from another source (PPP, SBA, SAM, Form 5500 or a registry) and gained a carrier**.
- `qc` floor for businesses with a carrier: **`min_fmcsa = 3_070_000`**, about 70% of 4,392,968. Phones: 5,704,618 businesses (spec 12: 1,607,400).
- **National open status, before (spec 12's file) and after:**

  | open_status | Before | After |
  | --- | --- | --- |
  | likely_open | 11,520,121 | 12,218,373 |
  | likely_closed | 14,587,311 | 16,545,787 |
  | unknown | 15,271,926 | 16,029,352 |

  3,562,822 businesses are decided by a carrier signal (`open_evidence` 'fmcsa carrier active' or 'fmcsa carrier inactive').
- **Spot checks against `https://data.transportation.gov/resource/az4n-8mr2.json?dot_number=<n>`**, two matched carriers added before 1996:
  - `OR-17873399` MARK JONES TRUCKING, INC. (`dol_5500 + fmcsa + or_active_businesses + ppp + sam`): ours USDOT 582601, status A, added 1994-11-30, officers KATHARINE JONES and MARK JONES, lookup 9080 NORTH UMPUA HWY 97470, phone 5414307018, NAICS 113310 from PPP. API: MARK JONES TRUCKING INC, A, `add_date` 19941130, 9080 NORTH UMPUA HWY, ROSEBURG OR 97470, officers KATHARINE JONES and MARK JONES, phone 5416720788. The phone differs because Form 5500's comes first (decision 20); the carrier's classes include AUTHORIZED FOR HIRE, but PPP's code comes first.
  - `CT-0214269` NEW HAVEN MASONRY & BUILDING SUPPLY, INC. (`ct_businesses + dol_5500 + fmcsa + ppp`), the Connecticut business spot-checked in spec 11: ours USDOT 507682, A, added 1992-12-21, officers ANDREW CONSIGLIO III and ELISA CONSIGLIO, lookup 355 JAMES STREET 06513, phone 2035626657. API: NEW HAVEN MASONRY & BLDG SUPPLY INC, A, 19921221, 355 JAMES STREET, NEW HAVEN CT 06513, phone 2035626657, the same officers.

- **The second run** (`smoke__20261018T025946Z`) had the Florida stage fail on a different Airflow error: the API server took 8 to 15 s to accept its result (`POST /execution/xcoms/.../state_stage/return_value`), the client retried, the first request had already stored it, and the retries got "409 Unique constraint violation". Same cause: DuckDB on every core starved the API server. That run was marked failed and replaced by the pair below, after the fixes.

## The runs after the code-review fixes

- **The lower CPU priority did not stop the stalls.** In `smoke__20261018T030913Z` the build's first attempt was reset again after 56 s ("Heartbeat recovered after 36.20 seconds", "Marked 1 SchedulerJob instances as failed", "Reset the following 1 orphaned TaskInstances"), and in `smoke__20261018T032937Z` the Florida stage needed a second try. Both runs succeeded on the retries, with the same file (`c881f208…`).
- **The stalls are disk I/O, not CPU.** During the build `vmstat` showed 100 to 360 MB/s written and iowait of 10 to 24% between CPU-bound stretches, and `/proc/pressure/io` showed some task stalled on I/O 17% of the last five minutes (memory 0.2%, CPU 3%); the scheduler had no major page faults. Its heartbeat and the API server's writes are Postgres commits on the same disk as the build's work database and spill files. The disk's I/O scheduler is `none`, so I/O priority (`ionice`) has no effect, and changing it needs root.
- **Fix, in the Dockerfile:** `AIRFLOW__SCHEDULER__SCHEDULER_HEALTH_CHECK_THRESHOLD=300` (from 30 s), so the one scheduler no longer judges itself dead while its heartbeat waits on the disk, and `AIRFLOW__WORKERS__EXECUTION_API_TIMEOUT=60` (from 5 s), so a task's slow result is not sent again as a duplicate. The nice value stays: it keeps Airflow and the desktop responsive while DuckDB holds every core, and costs nothing when the machine is idle.

- **The final pair** (`smoke__20261018T035037Z`, then `smoke__20261018T041103Z`, after `astro dev restart` with the two settings): both succeed with **no task retried** and no scheduler stall or reset in its log; all 71 downloads log `unchanged`, `fmcsa_census.csv` among them; `build` 15 min 20 s at a peak RSS of 36,819 MB, then 15 min 22 s at 36,809 MB; `sha256sum include/data/marts/businesses.parquet` is `c881f208cb35c8d618c4f8d754ccf16bc6acd191fb0f8f167e013ebca77d4980` after each, the same file as the two runs before the settings.

## The final file

The spec's query on it:

| with_carrier | carrier_only | with_officers | dated_by_fmcsa | address_from_fmcsa |
| --- | --- | --- | --- | --- |
| 4,392,968 | 3,416,203 | 3,775,666 | 3,667,981 | 4,392,968 |

- `dated_by_fmcsa` is 3,667,981, down from the first run's 3,782,127, since 1974-06-01 is no longer age evidence; 104,537 carrier businesses now have no age at all (carrier-only, with only the load date).
- **Businesses with NAICS starting `484` that gained a carrier: 2,393,671**; 95,592 of them had the code from another source. Phones: 5,704,698 (80 more than the first run, from the newest carrier that has one).
- National open status is as in the first run: likely_open 12,218,373, likely_closed 16,545,787, unknown 16,029,352 (spec 12: 11,520,121 / 14,587,311 / 15,271,926).

## Code review (`/code-review high` on the uncommitted diff)

Fixed:
- **FMCSA's 1974-06-01 is a load date, not an add date**: 122,637 carriers have it, and no carrier has any other date from 1974-06-02 through 1980 (the next is in 1981); BOGGESS TRUCKING LLC has it although it is an LLC. Taken as an add date it gave 114,331 businesses an age of 52 years that may be several years too old, against decision 11's rule that every age is a lower bound and known placeholders are ignored. It is now ignored as evidence, like 1900-01-01 everywhere; the stage keeps it as published (USDOT 1, the sentinel, is added 1974-06-01). A fixture carrier has it, and its business is dated by its PPP loan instead.
- **The lower CPU priority moved into `db.connect()`**, so it covers every stage and `qc` as well as `build` (the Florida stage's failure above), and it **never raises the priority**: it takes the larger of the current nice value and 10, since `setpriority` to a lower value than the current one needs a privilege.
- **The phone came only from the carrier with the newest MCS-150**, even when that carrier has none and another of the business's carriers does. It now comes from the newest carrier that has one.
- **`industry_group` showed a subsector for `484`**, because the three-digit code's first four characters are itself. A group is now looked up only for codes of four or more digits; `naics_title` still names `484` Truck Transportation.
- **The carriers were joined to their businesses four times** (aggregate, names and two signals); `fmcsa_b` joins them once.

Skipped, each set by the spec or the product decisions:
- "An inactive carrier with no MCS-150 date closes the business as of the census date": decision 19's table dates an inactive carrier "its last MCS-150 update, else `as_of`".
- "`FOR HIRE` includes passenger carriers, which get 484": the spec's rule ("`484` when `CLASSDEF` includes "FOR HIRE""), and it is last in decision 18's order.
- "FMCSA's DBA can be the owner's name, and it ranks above legal names in `lookup_name`" (BOGGESS TRUCKING LLC's DBA is JOEL S BOGGESS), and "an inactive carrier's old address comes first in the lookup": decision 20 fixes both orders. Worth the owner's look.
- "A carrier whose DBA equals a PPP key's name stays apart when no registry business links them": step 4 groups by the legal name, as the spec says (above).
- "The US-with-a-state rule is written twice, in the SQL and in `qc`": the same pattern as SAM's `country = 'USA'`.
