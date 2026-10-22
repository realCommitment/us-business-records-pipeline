# 11-registries-or-ct-dc

Adds the Oregon, Connecticut and District of Columbia business registries as state modules.

Bound by `docs/specs/00-product/spec.md`: decisions 4 to 6, 9, 11 to 13 and 17. Also bound by `docs/data-sources.md` sections 10.7 (CT), 10.8 (OR) and 10.9 (DC). It uses spec 06's contract, including multi-file sources, which Connecticut needs.

## Goal

Three small registries go through the default HTTP download and CSV read. Every entity becomes a registry business (product decision 9, step 1), and the national records in these states join them. Together they cover 263,279 PPP loans.

| Module | Dataset | Rows (2026-10-17) | Sentinel |
| --- | --- | --- | --- |
| `states/oregon.py` | data.oregon.gov `tckn-sxa6`, "Active Businesses - ALL" | 1,582,772 rows, 567,506 active entities | `1333616` PENDLETON WOOLEN MILLS, INC., 1909-02-16 |
| `states/connecticut.py` | data.ct.gov `n7gp-d28j` "Business Master", plus `ka36-64k6` "Principals" | 1,303,035 businesses, all statuses; 1,796,710 principals | `0074441` STANLEY BLACK & DECKER, INC., 1901-06-04 |
| `states/district_of_columbia.py` | opendata.dc.gov item `5238c4fd99c843a1bd7679a243747a8c` | 505,487 entities, all statuses | `571294` WASHINGTON GAS LIGHT Company, 1957-03-25 |

## What the user can do afterwards

```
scripts/smoke.sh 7200
uv run python -c "import duckdb; print(duckdb.sql(\"select state, open_status, count(*) businesses, count(*) filter (where list_contains(sources, 'ppp') and registry_id is not null) ppp_with_registry, count(formed_date) with_formed, count(registry_officers) with_officers from 'include/data/marts/businesses.parquet' where state in ('OR', 'CT', 'DC') group by all order by all\"))"
```

## Anti-goals

- No Connecticut agents file (`qh2m-n44y`). It is not clear how it links to Business Master, and agents are not owners.
- No status filter at stage or in matching, as in spec 08.
- No fix to DC's formation date beyond `FOREIGN_DATEOF_ORGANIZATION`. DC's `EFFECTIVE_DATE` can be a re-registration. Washington Gas Light dates to 1848 but shows 1957-03-25. That understates age, which is the safe direction.

## Files and interfaces

- **`states/oregon.py`**, `File("or_active_businesses.csv", "https://data.oregon.gov/api/views/tckn-sxa6/rows.csv?accessType=DOWNLOAD", …)`.
  - Each entity has one row per associated name type: `PRINCIPAL PLACE OF BUSINESS`, `MAILING ADDRESS`, `REGISTERED AGENT`, `AUTHORIZED REPRESENTATIVE` and any others found. The select groups by `registry_number` into one row:
    - name, entity type and registry date from a deterministic pick
    - address, city and `zip5` from the `PRINCIPAL PLACE OF BUSINESS` row with `address_kind = 'physical'`, else from the `MAILING ADDRESS` row with `address_kind = 'mailing'`
    - `officers` from every person-name row that is not the registered agent, as `associated_name_type || ': ' || first || ' ' || last`
    - extra `or_registered_agent`
  - `formed_date = strptime(registry_date, '%m/%d/%Y %I:%M:%S %p')::DATE`.
  - `active = true`: the dataset lists active businesses only, and Oregon drops entities that miss their annual renewal. `status` and `status_date` are NULL.
  - Extras: `or_jurisdiction`, `or_business_details`.
  - `dropped` is the raw rows minus the entities: 1,015,266 on 2026-10-17. Set the range to about ±20% of the first run.
  - Sentinel `("1333616", date(1909, 2, 16))`.
- **`states/connecticut.py`**, one registry `Source` with two `File`s:
  - **`ct_business_master.csv`** (`n7gp-d28j`). Its served header ends in `Geo_Location ` with a trailing space, and `File.header` keeps it.
  - **`ct_principals.csv`** (`ka36-64k6`). Confirm on the first run that `Unique_Key` equals Business Master's `Id`, using Stanley Black & Decker, and record it.

  The select:
  - `registry_id = AccountNumber`, keeping leading zeros. `Id` becomes extra `ct_id`.
  - `name`, `Business_Street`, `Business_City`, `Business_ZIP`, with `address_kind = 'physical'`.
  - `entity_type = Business_Type`, `status = Status`, `active = Status = 'Active'`. There were 464,565 active businesses on 2026-10-17.
  - `status_date = Dissolution_date`, where set.
  - `formed_date = mdy(Date_Registration)`. The placeholder `01/03/0001` on name reservations becomes NULL.
  - `naics` is the digits in parentheses of `NAICS_Code`, as in `Hardware Manufacturing (332510)`. NULL when there are none.
  - `officers` is principals grouped by `Unique_Key`, as a sorted list of `Designation || ': ' || Principal Name`.
  - Extras: `ct_sub_status`, `ct_began_transacting`, `ct_formation_place`, `ct_dissolution_date`, `ct_woman_owned`, `ct_veteran_owned`, `ct_minority_owned`, `ct_naics_text`.
  - `dropped=(0, 0)` against Business Master. Sentinel `("0074441", date(1901, 6, 4))`.
- **`states/district_of_columbia.py`**, `File("dc_corporations.csv", "https://opendata.dc.gov/api/download/v1/items/5238c4fd99c843a1bd7679a243747a8c/csv?layers=0", …)`.
  - The URL answers 302 to hub.arcgis.com. The target sends a weak `ETag` and a `Last-Modified`; `download_if_changed` follows the redirect, and its HEAD values are what it stores.
  - The file starts with a UTF-8 byte-order mark. The contract reads the header as `utf-8-sig`, and `File.header` has no BOM.
  - The column names misspell `BUSNIESS_ADDRESS_*`, and the columns keep that spelling.
  - The select:
    - `registry_id = FILE_NUMBER`, `name = BUSINESS_NAME`
    - address `BUSNIESS_ADDRESS_LINE1`, `BUSINESS_CITY`, `zip5` from `ZIPCODE`, with `address_kind = 'physical'`
    - `status_date` from `DCS_LAST_MOD_DTTM`. Check on the first run that it moves when the status changes, and record it; if it does not, leave `status_date` NULL so closures are dated by `as_of`.
    - `entity_type = MODELTYPE`. Record its values, and use `SUFFIX` if it describes the type better.
    - `status = ENTITY_STATUS`, `active = ENTITY_STATUS = 'Active - In Good Standing'`
    - `formed_date = least(EFFECTIVE_DATE, FOREIGN_DATEOF_ORGANIZATION)`, each parsed from its first 10 characters with `%Y/%m/%d`. Confirm the second column's format on the first run.
    - `officers = NULL`
  - Extras: `dc_registered_agent`, `dc_locale`, `dc_next_report_year`, `dc_last_report_filed`.
  - Statuses on 2026-10-17:

    | Status | Rows |
    | --- | --- |
    | Revoked | 313,807 |
    | Active - In Good Standing | 118,037 |
    | Dissolved | 32,568 |
    | Withdrawn | 30,828 |
    | Merged | 5,563 |
    | Inactive - Cancelled | 2,783 |
    | Terminated | 741 |
    | Domesticated | 630 |
    | Active - Not in Good Standing | 304 |
    | Converted | 114 |
    | Consolidated | 112 |
  - `dropped=(0, 0)`. Sentinel `("571294", date(1957, 3, 25))`.
- **`states/__init__.py`:** `STATES` gains `oregon`, `connecticut` and `district_of_columbia`.
- **Tests:** each state gets a fixture folder with the exact real header and real rows, including its sentinel, plus a test asserting the staged rows.
  - Oregon's fixture has one entity on four associated-name rows.
  - Connecticut's has a principal on the sentinel and one `01/03/0001` reservation.
  - DC's file starts with a BOM, and the test proves the header check passes.

## End-to-end verification

1. Run `scripts/smoke.sh 7200` and paste its output.
2. Paste the query above. Record each state's matched share of PPP keys, its calibrated `min_match_share`, and how many Connecticut principals joined.
3. Spot-check two old businesses per state:
   - Oregon: `https://data.oregon.gov/resource/tckn-sxa6.json?registry_number=<id>`
   - Connecticut: `https://data.ct.gov/resource/n7gp-d28j.json?accountnumber=<id>`
   - DC: the ArcGIS query endpoint `https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Business_Licensing_and_Grants_WebMercator/FeatureServer/0/query?where=FILE_NUMBER%3D%27<id>%27&outFields=*&f=json`
4. Outside OR, CT and DC, every row is unchanged from spec 10's file.
5. A second run logs `unchanged` for all four files. If DC's weak `ETag` changes daily, record that and accept the daily re-download. The file's `sha256sum` is identical when no source changed.
6. `mise run check` passes.
