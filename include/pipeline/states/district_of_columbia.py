"""District of Columbia: DLCP's corporate registrations on Open Data DC.

opendata.dc.gov item 5238c4fd99c843a1bd7679a243747a8c, every entity in every
status, CC BY 4.0, refreshed daily. The download URL answers 302 to
hub.arcgis.com, whose weak ETag and Last-Modified the sidecar keeps. The file
starts with a byte-order mark, and its column names misspell BUSNIESS.
docs/data-sources.md section 10.9.
"""

from datetime import date

from include.pipeline.states import File, Source

HEADER = (
    "OBJECTID,FILE_NUMBER,ENTITY_STATUS,LOCALE,MODELTYPE,BUSINESS_NAME,"
    "BUSNIESS_ADDRESS_LINE1,BUSNIESS_ADDRESS_LINE2,BUSNIESS_ADDRESS_LINE3,"
    "BUSNIESS_ADDRESS_LINE4,BUSINESS_CITY,BUSINESS_STATE,ZIPCODE,BUSINESS_COUNTRY,"
    "SUFFIX,RA_NAME,RA_ADDRESS1,RA_ADDRESS2,RA_ADDRESS3,RA_ADDRESS4,RA_CITY,"
    "RA_STATE,RA_ZIPCODE,EFFECTIVE_DATE,FOREIGN_DATEOF_ORGANIZATION,"
    "NEXT_REPORTYEAR_DUE,DCS_LAST_MOD_DTTM,DATE_LAST_REPORT_FILED,NEXT_REPORTYEAR,"
    "LATESTFILED_REPORTDATE,LATESTREPORT_YEARFILED,GLOBALID"
)

CORPORATIONS = File(
    "dc_corporations.csv",
    "https://opendata.dc.gov/api/download/v1/items/"
    "5238c4fd99c843a1bd7679a243747a8c/csv?layers=0",
    HEADER,
    tuple(c.lower() for c in HEADER.split(",")),
)


def ymd(col: str) -> str:
    # 2010/08/27 00:00:00+00; strict, so a malformed date fails the stage
    return f"strptime(left({col}, 10), '%Y/%m/%d')::DATE"


SOURCES = (
    Source(
        name="dc_corporations",
        state="DC",
        kind="registry",
        files=(CORPORATIONS,),
        select=f"""
            select 'DC' as state, file_number as registry_id, null::VARCHAR as ein,
                   business_name as name, norm_name(business_name) as norm_name,
                   busniess_address_line1 as address, upper(business_city) as city,
                   -- NotSet is a placeholder (1,373 rows on 2026-10-18)
                   nullif(business_state, 'NotSet') as address_state,
                   -- a foreign postal code is no ZIP
                   if(regexp_matches(zipcode, '^[0-9]{{5}}')
                      and coalesce(business_country, 'USA') = 'USA',
                      left(zipcode, 5), null) as zip5,
                   'physical' as address_kind, modeltype as entity_type,
                   entity_status as status,
                   -- DCS_LAST_MOD_DTTM is the export's load time, the same on
                   -- every row, so a closure is dated by as_of
                   null::DATE as status_date,
                   entity_status = 'Active - In Good Standing' as active,
                   -- a foreign entity's own formation is older than its DC
                   -- registration; 1753-01-01 is a placeholder
                   least({ymd("effective_date")},
                         nullif({ymd("foreign_dateof_organization")},
                                date '1753-01-01')) as formed_date,
                   null::VARCHAR as naics, null::VARCHAR[] as officers,
                   ra_name as dc_registered_agent, locale as dc_locale,
                   next_reportyear_due as dc_next_report_year,
                   {ymd("date_last_report_filed")} as dc_last_report_filed
            from dc_corporations
            -- a few file numbers are listed twice, as a revoked and a later
            -- row of one entity: keep the one that filed a report last
            qualify row_number() over (
                partition by file_number
                order by date_last_report_filed desc nulls last,
                         objectid::BIGINT desc) = 1""",
        min_rows=353_000,
        # about two-thirds of the first run's matched share, 75.9% (spec 11 notes)
        min_match_share=0.50,
        # 5 repeated file numbers on 2026-10-17
        dropped=(0, 50),
        sentinel=("571294", date(1957, 3, 25)),
    ),
)
