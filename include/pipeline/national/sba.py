import logging
import re
from datetime import date
from pathlib import Path

import requests

from include.pipeline.db import connect, copy_to_parquet
from include.pipeline.http import HEADERS, TIMEOUT, download_if_changed
from include.pipeline.paths import DATA

log = logging.getLogger(__name__)

# SBA 7(a) and 504 loans since fiscal 1991; docs/data-sources.md section 7
PAGE = "https://data.sba.gov/dataset/7a-504-foia"
LINK = re.compile(
    r"https://data\.sba\.gov/sites/default/files/uploaded_resources/"
    r"FOIA_(?:7a|504)_FY\d{4}_(?:FY\d{4}|Present)_asof_\d+\.csv"
)

# Every field is quoted and dates are ISO, so casts are strict and a
# malformed value fails the read. The 7(a) and 504 headers differ;
# union_by_name reads each file's missing columns as NULL.
STAGE_SQL = """
select trim(Program) as program,
       BorrName as borrower_name,
       norm_name(BorrName) as norm_name,
       dba_name(BorrName) as dba_norm_name,
       BorrStreet as address,
       upper(trim(BorrCity)) as city,
       -- a few states are blank spaces, which read_csv keeps
       nullif(trim(BorrState), '') as state,
       left(BorrZip, 5) as zip5,
       ApprovalDate::DATE as approval_date,
       ApprovalFY::INTEGER as approval_fy,
       GrossApproval::DECIMAL(18, 2) as gross_approval,
       NaicsCode as naics,
       BusinessType as business_type,
       BusinessAge as business_age,
       LoanStatus as loan_status,
       PaidInFullDate::DATE as paid_in_full_date,
       ChargeOffDate::DATE as charge_off_date,
       JobsSupported::INTEGER as jobs_supported,
       FranchiseName as franchise_name,
       coalesce(BankName, CDC_Name) as lender_name,
       regexp_extract(filename, '[^/]+$') as source_file
from read_csv(?, header=true, all_varchar=true, union_by_name=true,
              filename=true)
"""


def parse_links(html: str) -> list[str]:
    links = sorted(set(LINK.findall(html)))
    if len(links) < 6:
        raise ValueError(f"{PAGE}: {len(links)} SBA loan CSV links, expected 6")
    # two releases of one series listed together would count its loans twice
    series = {re.sub(r"_asof_\d+\.csv$", "", u) for u in links}
    if len(series) != len(links):
        raise ValueError(f"{PAGE}: a series appears in two releases: {links}")
    return links


def discover() -> list[str]:
    """Return the loan CSV URLs the SBA page lists; nothing is deleted."""
    r = requests.get(PAGE, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    urls = parse_links(r.text)
    log.info("sba_discover links=%d", len(urls))
    return urls


def download(url: str, data: Path = DATA) -> bool:
    return download_if_changed(url, data / "raw" / "sba" / url.rsplit("/", 1)[1])


def stage(urls: list[str], data: Path = DATA, min_rows: int = 1_530_000) -> int:
    """Write every loan with a ZIP, a name and a state to stage/sba_loans.parquet."""
    files = [data / "raw" / "sba" / u.rsplit("/", 1)[1] for u in urls]
    for f in files:
        if not f.exists():
            raise FileNotFoundError(f"{f}: listed by {PAGE} but not downloaded")
    src = data / "raw" / "sba"
    con = connect()
    con.execute(f"create temp table loans as {STAGE_SQL}", [[str(f) for f in files]])
    usable = "zip5 is not null and norm_name is not null and state is not null"
    loans, dropped, borrowers, sentinel = con.execute(
        f"""select count(*) filter (where {usable}),
                   count(*) filter (where not ({usable})),
                   count(distinct (norm_name, zip5)) filter (where {usable}),
                   list(approval_date) filter (where borrower_name = 'COPYTRON, INC.'
                                               and zip5 = '21771')
            from loans"""
    ).fetchall()[0]
    # checked before writing, so a bad read never replaces the previous file
    assert loans >= min_rows, f"{src}: {loans} loans, expected >= {min_rows}"
    assert dropped < 1000, (
        f"{src}: {dropped} loans without zip5, norm_name or state, expected < 1000"
    )
    assert sentinel and date(1990, 10, 1) in sentinel, (
        f"{src}: COPYTRON, INC. 21771 approved {sentinel}, expected 1990-10-01"
    )
    out = data / "stage" / "sba_loans.parquet"
    rows = copy_to_parquet(con, f"select * from loans where {usable}", out)
    log.info("sba_stage loans=%d borrowers=%d dropped=%d", rows, borrowers, dropped)
    return rows
