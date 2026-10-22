"""FMCSA Company Census: every motor carrier with a USDOT number.

data.transportation.gov dataset az4n-8mr2, US DOT public data, refreshed
daily. HEAD returns ETag and Last-Modified, with Content-Length 0 because the
export is streamed. docs/data-sources.md section 9.
"""

import logging
from datetime import date
from pathlib import Path

from include.pipeline.db import connect, copy_to_parquet
from include.pipeline.http import download_if_changed
from include.pipeline.paths import DATA
from include.pipeline.states import as_of

log = logging.getLogger(__name__)

URL = "https://data.transportation.gov/api/views/az4n-8mr2/rows.csv?accessType=DOWNLOAD"
# the first line exactly as served
HEADER = (
    "MCS150_DATE,ADD_DATE,STATUS_CODE,DOT_NUMBER,DUN_BRADSTREET_NO,"
    "PHY_OMC_REGION,SAFETY_INV_TERR,CARRIER_OPERATION,BUSINESS_ORG_ID,"
    "MCS150_MILEAGE,MCS150_MILEAGE_YEAR,MCS151_MILEAGE,TOTAL_CARS,"
    "MCS150_UPDATE_CODE_ID,PRIOR_REVOKE_FLAG,PRIOR_REVOKE_DOT_NUMBER,PHONE,FAX,"
    "CELL_PHONE,COMPANY_OFFICER_1,COMPANY_OFFICER_2,BUSINESS_ORG_DESC,"
    "TRUCK_UNITS,POWER_UNITS,BUS_UNITS,FLEETSIZE,REVIEW_ID,"
    "RECORDABLE_CRASH_RATE,MAIL_NATIONALITY_INDICATOR,"
    "PHY_NATIONALITY_INDICATOR,PHY_BARRIO,MAIL_BARRIO,CARSHIP,DOCKET1PREFIX,"
    "DOCKET1,DOCKET2PREFIX,DOCKET2,DOCKET3PREFIX,DOCKET3,POINTNUM,"
    "TOTAL_INTRASTATE_DRIVERS,MCSIPSTEP,MCSIPDATE,HM_Ind,"
    "INTERSTATE_BEYOND_100_MILES,INTERSTATE_WITHIN_100_MILES,"
    "INTRASTATE_BEYOND_100_MILES,INTRASTATE_WITHIN_100_MILES,TOTAL_CDL,"
    "TOTAL_DRIVERS,AVG_DRIVERS_LEASED_PER_MONTH,CLASSDEF,LEGAL_NAME,DBA_NAME,"
    "PHY_STREET,PHY_CITY,PHY_COUNTRY,PHY_STATE,PHY_ZIP,PHY_CNTY,"
    "CARRIER_MAILING_STREET,CARRIER_MAILING_STATE,CARRIER_MAILING_CITY,"
    "CARRIER_MAILING_COUNTRY,CARRIER_MAILING_ZIP,CARRIER_MAILING_CNTY,"
    "CARRIER_MAILING_UND_DATE,DRIVER_INTER_TOTAL,EMAIL_ADDRESS,REVIEW_TYPE,"
    "REVIEW_DATE,SAFETY_RATING,SAFETY_RATING_DATE,UNDELIV_PHY,CRGO_GENFREIGHT,"
    "CRGO_HOUSEHOLD,CRGO_METALSHEET,CRGO_MOTOVEH,CRGO_DRIVETOW,CRGO_LOGPOLE,"
    "CRGO_BLDGMAT,CRGO_MOBILEHOME,CRGO_MACHLRG,CRGO_PRODUCE,CRGO_LIQGAS,"
    "CRGO_INTERMODAL,CRGO_PASSENGERS,CRGO_OILFIELD,CRGO_LIVESTOCK,"
    "CRGO_GRAINFEED,CRGO_COALCOKE,CRGO_MEAT,CRGO_GARBAGE,CRGO_USMAIL,CRGO_CHEM,"
    "CRGO_DRYBULK,CRGO_COLDFOOD,CRGO_BEVERAGES,CRGO_PAPERPROD,CRGO_UTILITY,"
    "CRGO_FARMSUPP,CRGO_CONSTRUCT,CRGO_WATERWELL,CRGO_CARGOOTHR,"
    "CRGO_CARGOOTHR_DESC,OWNTRUCK,OWNTRACT,OWNTRAIL,OWNCOACH,OWNSCHOOL_1_8,"
    "OWNSCHOOL_9_15,OWNSCHOOL_16,OWNBUS_16,OWNVAN_1_8,OWNVAN_9_15,OWNLIMO_1_8,"
    "OWNLIMO_9_15,OWNLIMO_16,TRMTRUCK,TRMTRACT,TRMTRAIL,TRMCOACH,TRMSCHOOL_1_8,"
    "TRMSCHOOL_9_15,TRMSCHOOL_16,TRMBUS_16,TRMVAN_1_8,TRMVAN_9_15,TRMLIMO_1_8,"
    "TRMLIMO_9_15,TRMLIMO_16,TRPTRUCK,TRPTRACT,TRPTRAIL,TRPCOACH,TRPSCHOOL_1_8,"
    "TRPSCHOOL_9_15,TRPSCHOOL_16,TRPBUS_16,TRPVAN_1_8,TRPVAN_9_15,TRPLIMO_1_8,"
    "TRPLIMO_9_15,TRPLIMO_16,DOCKET1_STATUS_CODE,DOCKET2_STATUS_CODE,"
    "DOCKET3_STATUS_CODE"
)

# Dates are YYYYMMDD and counts whole numbers, cast strictly, so a malformed
# value fails the read. A ZIP is a US carrier's only.
STAGE_SQL = """
select DOT_NUMBER::BIGINT as dot_number,
       LEGAL_NAME as legal_name, norm_name(LEGAL_NAME) as norm_name,
       DBA_NAME as dba_name, norm_name(DBA_NAME) as norm_dba_name,
       PHY_STREET as phy_street, upper(PHY_CITY) as phy_city,
       PHY_STATE as phy_state,
       if(regexp_matches(PHY_ZIP, '^[0-9]{5}') and PHY_COUNTRY = 'US',
          left(PHY_ZIP, 5), null) as zip5,
       PHY_COUNTRY as phy_country,
       STATUS_CODE as status_code,
       strptime(ADD_DATE, '%Y%m%d')::DATE as add_date,
       strptime(MCS150_DATE, '%Y%m%d')::DATE as mcs150_date,
       COMPANY_OFFICER_1 as company_officer_1,
       COMPANY_OFFICER_2 as company_officer_2,
       BUSINESS_ORG_DESC as business_org_desc,
       CARRIER_OPERATION as carrier_operation, CLASSDEF as classdef,
       POWER_UNITS::INTEGER as power_units, TRUCK_UNITS::INTEGER as truck_units,
       TOTAL_DRIVERS::INTEGER as total_drivers,
       PHONE as phone, EMAIL_ADDRESS as email_address,
       ?::DATE as as_of
from (
    select nullif(trim(columns(*)), '')
    from read_csv(?, header=true, all_varchar=true)
)
"""

# USDOT 1 is FMCSA's own record and the export's first row; it is in DC
SENTINEL = (1, "FEDERAL MOTOR CARRIER SAFETY ADMINISTRATION", date(1974, 6, 1))


def raw(data: Path = DATA) -> Path:
    return data / "raw" / "fmcsa" / "fmcsa_census.csv"


def download(data: Path = DATA) -> bool:
    return download_if_changed(URL, raw(data))


def stage(data: Path = DATA, min_rows: int = 3_160_000) -> int:
    """Write every carrier, in every status and country, to the stage file."""
    src = raw(data)
    with src.open(encoding="utf-8-sig") as f:
        served = f.readline().rstrip("\r\n")
    if served != HEADER:
        raise ValueError(
            f"{src}: header changed\nserved:   {served}\nexpected: {HEADER}"
        )
    con = connect()
    con.execute(f"create temp table carriers as {STAGE_SQL}", [as_of(src), str(src)])
    rows, unique, us, sentinel = con.execute(
        """select count(*), count(distinct dot_number),
                  count(*) filter (where phy_country = 'US'),
                  list((legal_name, add_date)) filter (where dot_number = ?)
           from carriers""",
        [SENTINEL[0]],
    ).fetchall()[0]
    # checked before writing, so a bad export never replaces the previous file
    assert rows >= min_rows, f"{src}: {rows} carriers, expected >= {min_rows}"
    assert unique == rows, f"{src}: {rows - unique} repeated DOT numbers"
    expected = [(SENTINEL[1], SENTINEL[2])]
    assert sentinel == expected, f"{src}: USDOT 1 is {sentinel}, expected {expected}"
    out = data / "stage" / "fmcsa_carriers.parquet"
    copy_to_parquet(con, "select * from carriers", out)
    log.info("fmcsa_stage carriers=%d us=%d", rows, us)
    return int(rows)
