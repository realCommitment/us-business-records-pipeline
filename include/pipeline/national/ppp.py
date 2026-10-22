import logging
import re
from pathlib import Path

import requests

from include.pipeline.db import connect, copy_to_parquet
from include.pipeline.http import HEADERS, TIMEOUT, download_if_changed
from include.pipeline.paths import DATA

log = logging.getLogger(__name__)

# The CKAN API returns 404 for this dataset, so the page HTML is the only listing.
PAGE = "https://data.sba.gov/dataset/ppp-foia"
LINK = re.compile(
    r"https://data\.sba\.gov/sites/default/files/distribution/[^\"' ]+"
    r"/public_(?:150k_plus|up_to_150k_\d+)_\d+\.csv"
)

# The SBA files are Latin-1: stray bytes such as 0xBF and 0xA0, and no UTF-8.
# read_csv reads empty fields, quoted or not, as NULL.
STAGE_SQL = """
select
    LoanNumber::BIGINT as loan_number,
    strptime(DateApproved, '%m/%d/%Y')::DATE as date_approved,
    ProcessingMethod as processing_method,
    BorrowerName as borrower_name,
    norm_name(BorrowerName) as norm_name,
    dba_name(BorrowerName) as dba_norm_name,
    BorrowerAddress as address,
    upper(trim(BorrowerCity)) as city,
    coalesce(BorrowerState, ProjectState) as state,
    left(BorrowerZip, 5) as zip5,
    ProjectCountyName as county,
    LoanStatus as loan_status,
    strptime(LoanStatusDate, '%m/%d/%Y')::DATE as loan_status_date,
    InitialApprovalAmount::DOUBLE as initial_approval_amount,
    CurrentApprovalAmount::DOUBLE as current_approval_amount,
    ForgivenessAmount::DOUBLE as forgiveness_amount,
    JobsReported::INTEGER as jobs_reported,
    NAICSCode as naics,
    BusinessType as business_type,
    BusinessAgeDescription as business_age_description,
    coalesce(NonProfit = 'Y', false) as nonprofit
from read_csv(?, header=true, all_varchar=true, union_by_name=true,
              encoding='latin-1')
"""


def parse_links(html: str) -> list[str]:
    links = sorted(set(LINK.findall(html)))
    if len(links) < 13:
        raise ValueError(f"{PAGE}: {len(links)} PPP CSV links, expected at least 13")
    # two releases of one file listed together would count its loans twice
    stems = {re.sub(r"_\d+\.csv$", "", u) for u in links}
    if len(stems) != len(links):
        raise ValueError(f"{PAGE}: a file appears in two releases: {links}")
    return links


def discover() -> list[str]:
    """Return the PPP CSV URLs the SBA page lists.

    Nothing is deleted: a republished dataset gets new file names, and the
    stage reads only the listed ones.
    """
    r = requests.get(PAGE, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    urls = parse_links(r.text)
    log.info("ppp_discover links=%d", len(urls))
    return urls


def download(url: str, data: Path = DATA) -> bool:
    return download_if_changed(url, data / "raw" / "ppp" / url.rsplit("/", 1)[1])


def stage(urls: list[str], data: Path = DATA, min_rows: int = 8_000_000) -> int:
    """Write every loan with a ZIP, a name and a state to stage/ppp.parquet.

    Reads exactly the listed files. Malformed dates and numbers fail the read,
    so the previous file survives.
    """
    files = [data / "raw" / "ppp" / u.rsplit("/", 1)[1] for u in urls]
    for f in files:
        if not f.exists():
            raise FileNotFoundError(f"{f}: listed by {PAGE} but not downloaded")
    con = connect()
    src = data / "raw" / "ppp"
    con.execute(f"create temp table loans as {STAGE_SQL}", [[str(f) for f in files]])
    # a loan without a ZIP, a usable name or a state cannot be matched
    usable = "zip5 is not null and norm_name is not null and state is not null"
    loans, dropped, businesses = con.execute(
        f"""select count(*) filter (where {usable}),
                   count(*) filter (where not ({usable})),
                   count(distinct (norm_name, zip5)) filter (where {usable})
            from loans"""
    ).fetchall()[0]
    # checked before writing, so a bad read never replaces the previous file
    assert loans >= min_rows, f"{src}: {loans} loans, expected >= {min_rows}"
    assert dropped < 1000, (
        f"{src}: {dropped} loans without zip5, norm_name or state, expected < 1000"
    )
    out = data / "stage" / "ppp.parquet"
    rows = copy_to_parquet(con, f"select * from loans where {usable}", out)
    log.info("ppp_stage loans=%d businesses=%d dropped=%d", rows, businesses, dropped)
    return rows
