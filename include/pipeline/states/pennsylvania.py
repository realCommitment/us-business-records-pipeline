"""Pennsylvania: the Department of State's current business registrations.

data.pa.gov dataset xvd7-5r2c, Public Domain, refreshed monthly. One row per
officer of each current registration. Until the annual-report rule starts
dissolving non-filers in 2027, being listed is no evidence of trading.
Layout and quirks: docs/data-sources.md section 10.3.
"""

from datetime import date

from include.pipeline.states import File, Source, mdy

CORPORATIONS = File(
    "pa_corporations.csv",
    "https://data.pa.gov/api/views/xvd7-5r2c/rows.csv?accessType=DOWNLOAD",
    "Business Name,Filing Number,Address Line 1,Address Line 2,City,State,Zip,"
    "Type of Business Registration,Creation Date,Governor/Principal Officer,"
    "Last Name,Middle Name,First Name,County Name,County Code,"
    "Georeferenced Latitude & Longitude",
    ("business_name", "filing_number", "address_line_1", "address_line_2", "city",
     "state", "zip", "type_of_business_registration", "creation_date",
     "governor_principal_officer", "last_name", "middle_name", "first_name",
     "county_name", "county_code", "geo"),
)  # fmt: skip

SOURCES = (
    Source(
        name="pa_corporations",
        state="PA",
        kind="registry",
        files=(CORPORATIONS,),
        # One row per filing: the smallest of its rows' entity fields, a
        # deterministic pick, and the officers who have a name.
        select=f"""
            with filings as (
                select filing_number,
                       min({{'name': business_name, 'address': address_line_1,
                             'city': city, 'zip': zip,
                             'type': type_of_business_registration,
                             'created': creation_date, 'state': state,
                             'address_2': address_line_2, 'county': county_name,
                             'geo': geo}}) as e,
                       list(distinct governor_principal_officer || ': '
                            || concat_ws(' ', first_name, last_name)
                            order by governor_principal_officer || ': '
                            || concat_ws(' ', first_name, last_name))
                           filter (where coalesce(first_name, last_name)
                                         is not null
                                   and governor_principal_officer is not null)
                           as officers
                from pa_corporations
                group by filing_number
            ),
            -- a registered agent's office: an address 1,000 or more filings
            -- share (18 of them, 159,927 filings on 2026-10-17) or a c/o one
            agents as (
                select upper(e.address) as a, e.zip
                from filings group by all having count(*) >= 1000
            )
            select 'PA' as state, filing_number as registry_id,
                   null::VARCHAR as ein, e.name, norm_name(e.name) as norm_name,
                   e.address, upper(e.city) as city, e.state as address_state,
                   if(regexp_matches(e.zip, '^[0-9]{{5}}'), left(e.zip, 5), null)
                       as zip5,
                   -- 17 of 20 sampled were a place of business or the owner's
                   -- home, 3 a registered agent (notes of spec 08)
                   if(g.a is not null or upper(e.address) like '%C/O%', 'legal',
                      'physical') as address_kind, e.type as entity_type,
                   null::VARCHAR as status, null::DATE as status_date,
                   -- listed is no evidence of trading: no signal
                   null::BOOLEAN as active,
                   -- 1753-01-01 is the publisher's placeholder
                   nullif({mdy("e.created")}, date '1753-01-01') as formed_date,
                   null::VARCHAR as naics, officers,
                   e.county as pa_county_name, e.address_2 as pa_address_line_2,
                   e.geo as pa_geo
            from filings
            left join agents g on g.a = upper(e.address) and g.zip = e.zip""",
        min_rows=1_660_000,
        # raw rows minus filings: 1,798,504 on 2026-10-17, within 20%
        # about two-thirds of the first run's matched share (spec 08 notes)
        min_match_share=0.42,
        dropped=(1_440_000, 2_160_000),
        sentinel=("0000399042", date(1914, 4, 9)),
    ),
)
