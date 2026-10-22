import logging
from pathlib import Path

from include.pipeline.db import connect, copy_to_parquet
from include.pipeline.http import download_if_changed
from include.pipeline.paths import DATA
from include.pipeline.zips import extract

log = logging.getLogger(__name__)

# shortcut: extend the range by hand when DOL publishes the next form year's
# Latest zip; first filings for plan year N appear around July of N+1
YEARS = range(2009, 2026)
FORMS = ("F_5500", "F_5500_SF")


def url(form: str, year: int) -> str:
    # the bare host's 301 sends a raw space in Location
    base = "https://www.askebsa.dol.gov/FOIA%20Files"
    return f"{base}/{year}/Latest/{form}_{year}_Latest.zip"


def download(url: str, data: Path = DATA) -> bool:
    return download_if_changed(url, data / "raw" / "dol" / url.rsplit("/", 1)[1])


# One shape for both forms; read_csv reads empty fields as NULL. The admin's
# signer counts only when the administrator is the sponsor; otherwise it is a
# service provider, not the owner.
FORM_SQL = """
    select ACK_ID as ack_id, {ein} as ein, {name} as sponsor_name,
           {dba} as sponsor_dba_name, {addr} as address, {city} as city,
           {state} as state, {zip} as zip, {phone} as phone,
           {business} as business_code, {plan} as plan_name,
           {eff} as plan_eff_date, {year_begin} as plan_year_begin,
           DATE_RECEIVED as date_received, {partcp} as participants,
           {act_partcp} as active_participants, {codes} as pension_codes,
           coalesce({spons_signed}, {spons_manual}) as sponsor_signer,
           if({same} = '1', coalesce({admin_signed}, {admin_manual}), null)
               as admin_signer,
           '{form}' as form, filename
    from read_csv(?, header=true, all_varchar=true, union_by_name=true,
                  filename=true)
"""
SF = FORM_SQL.format(
    ein="SF_SPONS_EIN", name="SF_SPONSOR_NAME", dba="SF_SPONSOR_DFE_DBA_NAME",
    addr="SF_SPONS_US_ADDRESS1", city="SF_SPONS_US_CITY",
    state="SF_SPONS_US_STATE", zip="SF_SPONS_US_ZIP", phone="SF_SPONS_PHONE_NUM",
    business="SF_BUSINESS_CODE", plan="SF_PLAN_NAME", eff="SF_PLAN_EFF_DATE",
    year_begin="SF_PLAN_YEAR_BEGIN_DATE", partcp="SF_TOT_PARTCP_BOY_CNT",
    act_partcp="SF_TOT_ACT_PARTCP_BOY_CNT", codes="SF_TYPE_PENSION_BNFT_CODE",
    spons_signed="SF_SPONS_SIGNED_NAME", spons_manual="SF_SPONS_MANUAL_SIGNED_NAME",
    same="SF_ADMIN_NAME_SAME_SPON_IND", admin_signed="SF_ADMIN_SIGNED_NAME",
    admin_manual="SF_ADMIN_MANUAL_SIGNED_NAME", form="5500-SF",
)  # fmt: skip
FULL = FORM_SQL.format(
    ein="SPONS_DFE_EIN", name="SPONSOR_DFE_NAME", dba="SPONS_DFE_DBA_NAME",
    addr="SPONS_DFE_MAIL_US_ADDRESS1", city="SPONS_DFE_MAIL_US_CITY",
    state="SPONS_DFE_MAIL_US_STATE", zip="SPONS_DFE_MAIL_US_ZIP",
    phone="SPONS_DFE_PHONE_NUM", business="BUSINESS_CODE", plan="PLAN_NAME",
    eff="PLAN_EFF_DATE", year_begin="FORM_PLAN_YEAR_BEGIN_DATE",
    partcp="TOT_PARTCP_BOY_CNT", act_partcp="TOT_ACT_PARTCP_BOY_CNT",
    codes="TYPE_PENSION_BNFT_CODE", spons_signed="SPONS_SIGNED_NAME",
    spons_manual="SPONS_MANUAL_SIGNED_NAME", same="ADMIN_NAME_SAME_SPON_IND",
    admin_signed="ADMIN_SIGNED_NAME", admin_manual="ADMIN_MANUAL_SIGNED_NAME",
    form="5500",
)  # fmt: skip

# Dates are ISO and casts are strict, so a malformed date fails the COPY.
# Pension codes pack a digit and a letter per code (2E2J2K3D), so 1[A-I]
# cannot match across a code boundary. Older layouts are subsets of 2022 with
# no renames; union_by_name reads their missing columns as NULL.
STAGE_SQL = f"""
select ack_id, ein, sponsor_name, sponsor_dba_name,
       norm_name(sponsor_name) as norm_name, address, upper(city) as city, state,
       left(zip, 5) as zip5, phone, business_code, plan_name,
       plan_eff_date::DATE as plan_eff_date,
       plan_year_begin::DATE as plan_year_begin,
       date_received::DATE as date_received,
       participants::INTEGER as participants,
       active_participants::INTEGER as active_participants, pension_codes,
       coalesce(sponsor_signer, admin_signer) as signer_name,
       case when sponsor_signer is not null then 'sponsor'
            when admin_signer is not null then 'admin_is_sponsor'
       end as signer_source,
       form,
       regexp_extract(filename, '_(\\d{{4}})_latest\\.csv$', 1)::INTEGER
           as form_year,
       coalesce(regexp_matches(pension_codes, '1[A-I]'), false)
           as is_defined_benefit
from (select * from ({SF}) union all select * from ({FULL}))
where regexp_full_match(ein, '[0-9]{{9}}')
"""


def stage(data: Path = DATA, min_rows: int = 10_250_000) -> int:
    """Write every filing with a 9-digit EIN to stage/dol_5500_filings.parquet."""
    raw = data / "raw" / "dol"
    for z in sorted(raw.glob("*.zip")):
        extract(z)
    con = connect()
    # the f_5500_20?? glob does not match the f_5500_sf files
    sf, full = raw / "f_5500_sf_20??_latest.csv", raw / "f_5500_20??_latest.csv"
    con.execute(f"create temp table filings as {STAGE_SQL}", [str(sf), str(full)])
    rows, sponsors, years, ti = con.execute(
        """select count(*), count(distinct ein), count(distinct form_year),
                  count(*) filter (where ein = '750289970')
           from filings"""
    ).fetchall()[0]
    # checked before writing, so a bad read never replaces the previous file
    assert rows >= min_rows, f"{raw}: {rows} filings, expected >= {min_rows}"
    assert ti > 0, f"{raw}: no filing for Texas Instruments EIN 750289970"
    out = data / "stage" / "dol_5500_filings.parquet"
    copy_to_parquet(con, "select * from filings", out)
    log.info("dol_stage filings=%d sponsors=%d form_years=%d", rows, sponsors, years)
    return int(rows)
