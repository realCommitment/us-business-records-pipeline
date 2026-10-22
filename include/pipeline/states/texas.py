"""Texas: the Comptroller of Public Accounts' open data on data.texas.gov.

- Active Franchise Taxpayers, dataset 9cir-efmm: the registry.
- Active Sales Tax Permit Holders, dataset jrea-zgmq: trade names, one row per
  outlet.

Both refresh weekly. Layouts, codes and quirks: docs/data-sources.md section 2.
"""

from datetime import date

from include.pipeline.states import File, Source, mdy

URL = "https://data.texas.gov/api/views/{id}/rows.csv?accessType=DOWNLOAD"

# Taxpayer numbers starting with 1 embed the federal EIN: 1, the EIN, a check
# digit (verified on Texas Instruments and Southwest Airlines).
EIN = "case when taxpayer_number like '1%' then substr(taxpayer_number, 2, 9) end"

FRANCHISE = File(
    "tx_franchise.csv",
    URL.format(id="9cir-efmm"),
    "Taxpayer Number,Taxpayer Name,Taxpayer Address,Taxpayer City,"
    "Taxpayer State,Taxpayer Zip,Taxpayer County Code,"
    "Taxpayer Organizational Type,Record Type Code,"
    "Responsibility Beginning Date,"
    "  Secretary of State (SOS) or COA File Number,SOS Charter Date,"
    "SOS Status Date ,SOS Status Code,Right to Transact Business Code,"
    "Current Exempt Reason Code,Exempt Begin Date,NAICS Code",
    ("taxpayer_number", "taxpayer_name", "address", "city", "state", "zip",
     "county_code", "org_type", "record_type", "responsibility_begin_date",
     "sos_file_number", "charter_date", "sos_status_date", "sos_status",
     "right_to_transact", "exempt_reason", "exempt_begin_date", "naics"),
)  # fmt: skip

OUTLETS = File(
    "tx_sales_outlets.csv",
    URL.format(id="jrea-zgmq"),
    "Taxpayer Number,Taxpayer Name,Taxpayer Address,Taxpayer City,"
    "Taxpayer State,Taxpayer Zip Code,Taxpayer County Code,"
    "Taxpayer Organization Type,Outlet Number,Outlet Name,Outlet Address,"
    "Outlet City,Outlet State,Outlet Zip Code,Outlet County Code,"
    "Outlet NAICS Code,Outlet Inside/Outside City Limits Indicator,"
    "Outlet Permit Issue Date,Outlet First Sales Date",
    ("taxpayer_number", "taxpayer_name", "taxpayer_address", "taxpayer_city",
     "taxpayer_state", "taxpayer_zip", "taxpayer_county_code", "org_type",
     "outlet_number", "outlet_name", "outlet_address", "outlet_city",
     "outlet_state", "outlet_zip", "outlet_county_code", "outlet_naics",
     "outlet_inside_city", "permit_issue_date", "first_sales_date"),
)  # fmt: skip

SOURCES = (
    Source(
        name="tx_franchise",
        state="TX",
        kind="registry",
        files=(FRANCHISE,),
        # 31 taxpayer numbers appear twice; keep the active, most recently
        # updated copy. record_type and exempt_reason break the remaining ties
        # seen in the data, so the same copy is kept every run.
        select=f"""
            with typed as (
                select taxpayer_number, {EIN} as ein, taxpayer_name, address,
                       upper(city) as city, state, left(zip, 5) as zip5,
                       county_code, org_type, record_type,
                       {mdy("responsibility_begin_date")}
                           as responsibility_begin_date,
                       sos_file_number, {mdy("charter_date")} as charter_date,
                       {mdy("sos_status_date")} as sos_status_date, sos_status,
                       right_to_transact, exempt_reason, naics
                from tx_franchise
                qualify row_number() over (
                    partition by taxpayer_number
                    order by (sos_status = 'A') desc,
                             sos_status_date desc nulls last,
                             charter_date, record_type, exempt_reason) = 1
            )
            select 'TX' as state, taxpayer_number as registry_id, ein,
                   taxpayer_name as name, norm_name(taxpayer_name) as norm_name,
                   address, city, state as address_state, zip5,
                   -- the Comptroller's taxpayer address is where tax mail goes
                   'mailing' as address_kind, org_type as entity_type,
                   sos_status as status, sos_status_date as status_date,
                   -- U (franchise tax not established yet) says nothing
                   case when right_to_transact = 'A' then true
                        when right_to_transact is distinct from 'U' then false
                   end as active,
                   charter_date as formed_date, naics,
                   null::VARCHAR[] as officers,
                   sos_file_number as tx_sos_file_number,
                   record_type as tx_record_type,
                   right_to_transact as tx_right_to_transact,
                   sos_status_date as tx_sos_status_date,
                   responsibility_begin_date as tx_responsibility_begin_date,
                   exempt_reason as tx_exempt_reason,
                   county_code as tx_county_code
            from typed""",
        min_rows=3_000_000,
        dropped=(1, 999),
        sentinel=("17502899705", date(1938, 12, 31)),
    ),
    Source(
        name="tx_sales_outlets",
        state="TX",
        kind="dba",
        files=(OUTLETS,),
        select=f"""
            select 'TX' as state, taxpayer_number as registry_id, {EIN} as ein,
                   org_type as entity_type, outlet_name as dba_name,
                   norm_name(outlet_name) as norm_dba_name,
                   outlet_address as address, upper(outlet_city) as city,
                   left(outlet_zip, 5) as zip5,
                   {mdy("first_sales_date")} as first_seen_date,
                   -- the dataset lists active permits only
                   true as active, outlet_naics as naics,
                   outlet_number as tx_outlet_number,
                   {mdy("permit_issue_date")} as tx_permit_issue_date,
                   taxpayer_name as tx_taxpayer_name
            from tx_sales_outlets""",
        min_rows=800_000,
        dropped=(0, 0),
        sentinel=None,
    ),
)
