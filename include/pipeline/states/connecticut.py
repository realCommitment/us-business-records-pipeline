"""Connecticut: the Secretary of the State's Business Master and Principals.

data.ct.gov datasets n7gp-d28j (every business in every status) and ka36-64k6
(principals, whose Unique_Key is the business's Id), Public Domain, refreshed
daily. docs/data-sources.md section 10.7.
"""

from datetime import date

from include.pipeline.states import File, Source, mdy

# Business Master's header as served ends in a space after Geo_Location
MASTER_HEADER = (
    "Id,Name,Business_Type,Status,Sub_status,AccountNumber,Annual_Report_Due_Date,"
    "Began_Transacting_in_CT,Business_Street,Business_Unit,Business_City,"
    "Business_Country,Business_ZIP,Business_State,Business_Email_Address,"
    "Business_Name_in_state_country,Citizenship,Country_Formation,"
    "Date_Registration,Formation_Place,State_or_Territory_Formation,"
    "Date_of_Organization_Meeting,Dissolution_date,"
    "Mail_Jurisdiction_International_address,Mailing_Address,"
    "Mailing_International_Address,Mailing_Jurisdiction_Address,"
    "Mailing_Jurisdiction_BusinessStreet,Mailing_Jurisdiction_BusinessUnit,"
    "Mailing_Jurisdiction_BusinessCity,Mailing_Jurisdiction_BusinessState,"
    "Mailing_Jurisdiction_BusinessZipCode,Mailing_Jurisdiction_Country,"
    "Woman_Owned_Organization,Veteran_Owned_Organization,"
    "Minority_Owned_Organization,Org_Owned_by_Person_s_with_disabilities,"
    "Organization_is_LGBTQI_Owned,Category_Survey_Email_Address,NAICS_Code,"
    "NAICS_Sub_Code,Office_Jurisdiction_Address,Office_Jurisdiction_BusinessStreet,"
    "Office_Jurisdiction_BusinessUnit,Office_Jurisdiction_BusinessCity,"
    "Office_Jurisdiction_BusinessState,Office_Jurisdiction_BusinessZipCode,"
    "Office_in_Jurisdiction_Country,Reason_for_Administrative_Dissolution,"
    "Record_Address,Records_Address_Street,Records_Address_Unit,"
    "Records_Address_City,Records_Address_State,Records_Address_Zip_Code,"
    "Records_Address_Country,Total_Authorized_Shares,CREATE_DT,Geo_Location "
)
PRINCIPALS_HEADER = (
    "Unique_Key,Principal Name,First Name,Middle Name,Last Name,Suffix,Designation,"
    "Business Street Address 1,Business Street Address 2,Business Street Address 3,"
    "Business City,Business State,Business Zip Code,Business Country,"
    "Business International Address,Residence Address,Residence Street Address 1,"
    "Residence Street Address 2,Residence Street Address 3,Residence City,"
    "Residence State,Residence Zip Code,Residence Country,"
    "Residence International Address,Type,CREATE_DT"
)


def snake(header: str) -> tuple[str, ...]:
    return tuple(c.strip().lower().replace(" ", "_") for c in header.split(","))


MASTER = File(
    "ct_business_master.csv",
    "https://data.ct.gov/api/views/n7gp-d28j/rows.csv?accessType=DOWNLOAD",
    MASTER_HEADER,
    snake(MASTER_HEADER),
)
PRINCIPALS = File(
    "ct_principals.csv",
    "https://data.ct.gov/api/views/ka36-64k6/rows.csv?accessType=DOWNLOAD",
    PRINCIPALS_HEADER,
    snake(PRINCIPALS_HEADER),
)

# the code in "Hardware Manufacturing (332510)"
NAICS = r"\((\d{2,6})\)"

SOURCES = (
    Source(
        name="ct_businesses",
        state="CT",
        kind="registry",
        files=(MASTER, PRINCIPALS),
        select=f"""
            with officers as (
                select unique_key,
                       -- distinct: a principal can be listed twice
                       list(distinct coalesce(designation || ': ', '')
                                     || principal_name
                            order by coalesce(designation || ': ', '')
                                     || principal_name) as officers
                from ct_principals
                where principal_name is not null
                group by unique_key
            )
            select 'CT' as state,
                   -- 0000000 is a placeholder shared by unregistered businesses
                   -- and stubs (24 on 2026-10-17); they keep their Id instead
                   if(b.accountnumber = '0000000', b.id, b.accountnumber)
                       as registry_id,
                   null::VARCHAR as ein, b.name, norm_name(b.name) as norm_name,
                   b.business_street as address, upper(b.business_city) as city,
                   b.business_state as address_state,
                   -- a foreign address has no state, and its postal code is no ZIP
                   if(regexp_matches(b.business_zip, '^[0-9]{{5}}')
                      and b.business_state is not null, left(b.business_zip, 5),
                      null) as zip5,
                   'physical' as address_kind, b.business_type as entity_type,
                   b.status,
                   strptime(b.dissolution_date, '%m/%d/%Y %I:%M:%S %p')::DATE
                       as status_date,
                   b.status = 'Active' as active,
                   -- 01/03/0001 is the placeholder on name reservations
                   if(b.date_registration = '01/03/0001', null,
                      {mdy("b.date_registration")}) as formed_date,
                   -- Hardware Manufacturing (332510), or a bare code
                   coalesce(nullif(regexp_extract(b.naics_code, '{NAICS}', 1), ''),
                            if(regexp_full_match(b.naics_code, '\\d{{6}}'),
                               b.naics_code, null)) as naics,
                   o.officers,
                   b.id as ct_id, b.sub_status as ct_sub_status,
                   {mdy("b.began_transacting_in_ct")} as ct_began_transacting,
                   b.formation_place as ct_formation_place,
                   strptime(b.dissolution_date, '%m/%d/%Y %I:%M:%S %p')::DATE
                       as ct_dissolution_date,
                   b.woman_owned_organization::BOOLEAN as ct_woman_owned,
                   b.veteran_owned_organization::BOOLEAN as ct_veteran_owned,
                   b.minority_owned_organization::BOOLEAN as ct_minority_owned,
                   b.naics_code as ct_naics_text
            from ct_business_master b
            left join officers o on o.unique_key = b.id""",
        min_rows=912_000,
        # about two-thirds of the first run's matched share, 71.1% (spec 11 notes)
        min_match_share=0.47,
        dropped=(0, 0),
        sentinel=("0074441", date(1901, 6, 4)),
    ),
)
