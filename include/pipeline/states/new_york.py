"""New York: the Department of State's "Active Corporations: Beginning 1800".

data.ny.gov dataset n9v6-gdp6, refreshed monthly, no licence stated. It lists
every entity not formally dissolved; New York enforces no annual report, so
being listed is no evidence of trading. Layout and fill rates:
docs/data-sources.md section 10.2.
"""

from datetime import date

from include.pipeline.states import File, Source, mdy

CORPORATIONS = File(
    "ny_corporations.csv",
    "https://data.ny.gov/api/views/n9v6-gdp6/rows.csv?accessType=DOWNLOAD",
    "DOS ID,Current Entity Name,Initial DOS Filing Date,County,Jurisdiction,"
    "Entity Type,DOS Process Name,DOS Process Address 1,DOS Process Address 2,"
    "DOS Process City,DOS Process State,DOS Process Zip,CEO Name,"
    "CEO Address 1,CEO Address 2,CEO City,CEO State,CEO Zip,"
    "Registered Agent Name,Registered Agent Address 1,"
    "Registered Agent Address 2,Registered Agent City,Registered Agent State,"
    "Registered Agent Zip,Location Name,Location Address 1,Location Address 2,"
    "Location City,Location State,Location Zip",
    ("dos_id", "current_entity_name", "initial_dos_filing_date", "county",
     "jurisdiction", "entity_type", "dos_process_name", "dos_process_address_1",
     "dos_process_address_2", "dos_process_city", "dos_process_state",
     "dos_process_zip", "ceo_name", "ceo_address_1", "ceo_address_2",
     "ceo_city", "ceo_state", "ceo_zip", "registered_agent_name",
     "registered_agent_address_1", "registered_agent_address_2",
     "registered_agent_city", "registered_agent_state", "registered_agent_zip",
     "location_name", "location_address_1", "location_address_2",
     "location_city", "location_state", "location_zip"),
)  # fmt: skip

SOURCES = (
    Source(
        name="ny_corporations",
        state="NY",
        kind="registry",
        files=(CORPORATIONS,),
        # The location fields are the place of business but fill only 8% of
        # rows; otherwise the address is where legal papers go, often a lawyer
        # or an agent.
        select=f"""
            with picked as (
                select *, if(located, location_zip, dos_process_zip) as zip
                from (
                    -- the location counts only with both a street and a ZIP
                    select *, location_zip is not null
                              and location_address_1 is not null as located
                    from ny_corporations
                )
            )
            select 'NY' as state, dos_id as registry_id, null::VARCHAR as ein,
                   current_entity_name as name,
                   norm_name(current_entity_name) as norm_name,
                   if(located, location_address_1, dos_process_address_1)
                       as address,
                   upper(if(located, location_city, dos_process_city)) as city,
                   if(located, location_state, dos_process_state)
                       as address_state,
                   if(regexp_full_match(left(zip, 5), '[0-9]{{5}}'), left(zip, 5),
                      null) as zip5,
                   if(located, 'physical', 'legal') as address_kind,
                   entity_type, null::VARCHAR as status, null::DATE as status_date,
                   -- listed is no evidence of trading: no signal
                   null::BOOLEAN as active,
                   {mdy("initial_dos_filing_date")} as formed_date,
                   null::VARCHAR as naics,
                   if(ceo_name is not null, ['CEO: ' || ceo_name], null)
                       as officers,
                   county as ny_county, jurisdiction as ny_jurisdiction,
                   dos_process_name as ny_dos_process_name,
                   registered_agent_name as ny_registered_agent_name,
                   location_name as ny_location_name,
                   nullif(concat_ws(', ', ceo_address_1, ceo_address_2, ceo_city,
                                    ceo_state, ceo_zip), '') as ny_ceo_address
            from picked""",
        min_rows=3_000_000,
        # about two-thirds of the first run's matched share (spec 08 notes)
        min_match_share=0.44,
        dropped=(0, 0),
        sentinel=("30059", date(1911, 6, 16)),
    ),
)
