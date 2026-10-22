"""Colorado: the Secretary of State's "Business Entities in Colorado".

data.colorado.gov dataset 4ykn-tg5h, Public Domain, refreshed daily, every
entity in every status. Entities renumbered in 1987 carry a 1987 prefix on
their id, while some older ones keep their own year (18861217679). Layout and
statuses: docs/data-sources.md section 10.5.
"""

from datetime import date

from include.pipeline.states import File, Source, mdy

ENTITIES = File(
    "co_business_entities.csv",
    "https://data.colorado.gov/api/views/4ykn-tg5h/rows.csv?accessType=DOWNLOAD",
    "entityid,entityname,principaladdress1,principaladdress2,principalcity,"
    "principalstate,principalzipcode,principalcountry,mailingaddress1,"
    "mailingaddress2,mailingcity,mailingstate,mailingzipcode,mailingcountry,"
    "entitystatus,jurisdictonofformation,entitytype,agentfirstname,"
    "agentmiddlename,agentlastname,agentsuffix,agentorganizationname,"
    "agentprincipaladdress1,agentprincipaladdress2,agentprincipalcity,"
    "agentprincipalstate,agentprincipalzipcode,agentprincipalcountry,"
    "agentmailingaddress1,agentmailingaddress2,agentmailingcity,"
    "agentmailingstate,agentmailingzipcode,agentmailingcountry,entityformdate",
    ("entityid", "entityname", "principaladdress1", "principaladdress2",
     "principalcity", "principalstate", "principalzipcode", "principalcountry",
     "mailingaddress1", "mailingaddress2", "mailingcity", "mailingstate",
     "mailingzipcode", "mailingcountry", "entitystatus",
     "jurisdictonofformation", "entitytype", "agentfirstname",
     "agentmiddlename", "agentlastname", "agentsuffix", "agentorganizationname",
     "agentprincipaladdress1", "agentprincipaladdress2", "agentprincipalcity",
     "agentprincipalstate", "agentprincipalzipcode", "agentprincipalcountry",
     "agentmailingaddress1", "agentmailingaddress2", "agentmailingcity",
     "agentmailingstate", "agentmailingzipcode", "agentmailingcountry",
     "entityformdate"),
)  # fmt: skip

SOURCES = (
    Source(
        name="co_business_entities",
        state="CO",
        kind="registry",
        files=(ENTITIES,),
        select=f"""
            select 'CO' as state, entityid as registry_id, null::VARCHAR as ein,
                   entityname as name, norm_name(entityname) as norm_name,
                   principaladdress1 as address, upper(principalcity) as city,
                   principalstate as address_state,
                   -- a foreign postal code is no ZIP
                   if(regexp_matches(principalzipcode, '^[0-9]{{5}}')
                      and coalesce(principalcountry, 'US') = 'US',
                      left(principalzipcode, 5), null) as zip5,
                   'physical' as address_kind, entitytype as entity_type,
                   entitystatus as status,
                   -- there is no status date, so a closure is dated by as_of
                   null::DATE as status_date,
                   -- Delinquent (a missed periodic report) is the publisher's
                   -- own "not in good standing"; Exists marks partnerships
                   -- and trusts it tracks no standing for, so no signal
                   case when entitystatus = 'Good Standing' then true
                        when entitystatus != 'Exists' then false
                   end as active,
                   {mdy("entityformdate")} as formed_date,
                   null::VARCHAR as naics,
                   -- the registered agent is not an officer
                   null::VARCHAR[] as officers,
                   jurisdictonofformation as co_jurisdiction_of_formation,
                   coalesce(agentorganizationname,
                            nullif(concat_ws(' ', agentfirstname, agentlastname),
                                   '')) as co_agent_name,
                   mailingzipcode as co_mailing_zip
            from co_business_entities""",
        min_rows=2_190_000,
        # about two-thirds of the first run's matched share (spec 08 notes)
        min_match_share=0.40,
        dropped=(0, 0),
        sentinel=("19871009071", date(1888, 11, 17)),
    ),
)
