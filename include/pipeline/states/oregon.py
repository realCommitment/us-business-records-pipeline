"""Oregon: the Secretary of State's "Active Businesses - ALL".

data.oregon.gov dataset tckn-sxa6, refreshed weekly. It lists active entities
only: Oregon drops an entity that misses its annual renewal. Each entity has
one row per associated name (principal place of business, mailing address,
registered agent, authorized representative). docs/data-sources.md
section 10.8.
"""

from datetime import date

from include.pipeline.states import File, Source

BUSINESSES = File(
    "or_active_businesses.csv",
    "https://data.oregon.gov/api/views/tckn-sxa6/rows.csv?accessType=DOWNLOAD",
    "Registry Number,Business Name,Entity Type,Registry Date,Associated Name Type,"
    "First Name,Middle Name,Last Name,Suffix,Not of Record Entity,"
    "Entity of Record Reg Number,Entity of Record Name,Address,Address Continued,"
    "City,State,Zip,Jurisdiction,Business Details",
    ("registry_number", "business_name", "entity_type", "registry_date",
     "associated_name_type", "first_name", "middle_name", "last_name", "suffix",
     "not_of_record_entity", "entity_of_record_reg_number",
     "entity_of_record_name", "address", "address_continued", "city", "state",
     "zip", "jurisdiction", "business_details"),
)  # fmt: skip

SOURCES = (
    Source(
        name="or_active_businesses",
        state="OR",
        kind="registry",
        files=(BUSINESSES,),
        # an entity's name, type, date and details are the same on every row
        # (checked on 2026-10-17), so min() is a deterministic pick
        select="""
            with e as (
                select registry_number, min(business_name) as name,
                       min(entity_type) as entity_type,
                       min(registry_date) as registry_date,
                       min(jurisdiction) as jurisdiction,
                       min(business_details) as business_details,
                       -- one struct, so the parts are one row's
                       min({'address': address, 'city': city, 'state': state,
                            'zip': zip})
                           filter (where associated_name_type
                                   = 'PRINCIPAL PLACE OF BUSINESS') as place,
                       min({'address': address, 'city': city, 'state': state,
                            'zip': zip})
                           filter (where associated_name_type = 'MAILING ADDRESS')
                           as mailing,
                       list(distinct associated_name_type || ': '
                                     || concat_ws(' ', first_name, last_name)
                            order by associated_name_type || ': '
                                     || concat_ws(' ', first_name, last_name))
                           filter (where associated_name_type != 'REGISTERED AGENT'
                                   and coalesce(first_name, last_name) is not null)
                           as officers,
                       min(coalesce(nullif(concat_ws(' ', first_name, last_name), ''),
                                    entity_of_record_name))
                           filter (where associated_name_type = 'REGISTERED AGENT')
                           as registered_agent
                from or_active_businesses
                group by registry_number
            )
            select 'OR' as state, registry_number as registry_id,
                   null::VARCHAR as ein, name, norm_name(name) as norm_name,
                   coalesce(place, mailing).address as address,
                   upper(coalesce(place, mailing).city) as city,
                   -- spelled out as published; the two US territories get
                   -- their codes, and a Canadian province keeps its name
                   case coalesce(place, mailing).state
                       when 'PUERTO RICO' then 'PR' when 'VIRGIN ISLANDS' then 'VI'
                       else coalesce(place, mailing).state end as address_state,
                   -- a Canadian postal code is no ZIP
                   if(regexp_matches(coalesce(place, mailing).zip, '^[0-9]{5}'),
                      left(coalesce(place, mailing).zip, 5), null) as zip5,
                   if(place is not null, 'physical', 'mailing') as address_kind,
                   entity_type, null::VARCHAR as status, null::DATE as status_date,
                   -- the dataset lists active entities only
                   true as active,
                   strptime(registry_date, '%m/%d/%Y %I:%M:%S %p')::DATE
                       as formed_date,
                   null::VARCHAR as naics, officers,
                   registered_agent as or_registered_agent,
                   jurisdiction as or_jurisdiction,
                   business_details as or_business_details
            from e""",
        min_rows=397_000,
        # about two-thirds of the first run's matched share, 60.2% (spec 11 notes)
        min_match_share=0.40,
        # one row per associated name: 1,015,266 more rows than entities on
        # 2026-10-17, and about 20% either side
        dropped=(812_000, 1_219_000),
        sentinel=("1333616", date(1909, 2, 16)),
    ),
)
