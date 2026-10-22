import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from include.pipeline.national.sba import parse_links, stage

FIXTURES = Path(__file__).parents[2] / "fixtures" / "national" / "sba"
BASE = "https://data.sba.gov/sites/default/files/uploaded_resources/"


def test_parse_links_returns_the_six_files() -> None:
    links = parse_links((FIXTURES / "page.html").read_text())

    assert links == [
        BASE + f"FOIA_{name}_asof_260630.csv"
        for name in (
            "504_FY1991_FY2009", "504_FY2010_Present", "7a_FY1991_FY1999",
            "7a_FY2000_FY2009", "7a_FY2010_FY2019", "7a_FY2020_Present",
        )
    ]  # fmt: skip


def test_parse_links_raises_on_two_releases_of_one_series() -> None:
    page = (FIXTURES / "page.html").read_text()
    page += f'<a href="{BASE}FOIA_7a_FY2020_Present_asof_260930.csv">x</a>'

    with pytest.raises(ValueError, match="a series appears in two releases"):
        parse_links(page)


def test_stage_types_the_loans_and_drops_the_unusable_one(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "sba"
    raw.mkdir(parents=True)
    for csv in FIXTURES.glob("*.csv"):
        shutil.copy(csv, raw)
    urls = [BASE + p.name for p in sorted(FIXTURES.glob("*.csv"))]

    assert stage(urls, tmp_path, min_rows=1) == 5

    rows = duckdb.sql(
        f"""select program, norm_name, city, state, zip5, approval_date,
                   approval_fy, gross_approval, naics, business_age, loan_status,
                   charge_off_date, lender_name, source_file
            from '{tmp_path / "stage" / "sba_loans.parquet"}'
            order by source_file, approval_date, norm_name"""
    ).fetchall()
    # the borrower named "-" has no usable name and is dropped
    assert rows == [
        ("504", "JACK BINGHAM PHOTOGRAPHY", "BARRINGTON", "NH", "03825",
         date(1990, 10, 1), 1991, Decimal("65000.00"), "541921",
         "Less than 4 years old but at least 3", "PIF", None,
         "Granite State Economic Development Corporation",
         "FOIA_504_FY1991_FY2009_asof_260630.csv"),
        ("504", "LONG JOHN SILVERS", "BLUE RIDGE", "GA", "30513",
         date(1990, 10, 11), 1991, Decimal("278000.00"), None,
         "New, Less than 1 Year old", "CHGOFF", date(1998, 2, 18),
         "Small Business Access Partners, Inc.",
         "FOIA_504_FY1991_FY2009_asof_260630.csv"),
        # the program is trimmed: the 7(a) files say " 7A"
        ("7A", "COPYTRON", "MT AIRY", "MD", "21771", date(1990, 10, 1), 1991,
         Decimal("33500.00"), None, "Less than 4 years old but at least 3", "P I F",
         None, "Manufacturers and Traders Trust Company",
         "FOIA_7a_FY1991_FY1999_asof_260630.csv"),
        ("7A", "MICHAEL DAVIS", "FOND DU LAC", "WI", "54936", date(1990, 10, 1),
         1991, Decimal("250000.00"), None, "Less than 4 years old but at least 3",
         "P I F", None, "U.S. Bank, National Association",
         "FOIA_7a_FY1991_FY1999_asof_260630.csv"),
        ("7A", "CONNIES TEA ROOM", "NEVADA", "IA", "50201", date(1990, 10, 2), 1991,
         Decimal("20600.00"), None, "Less than 4 years old but at least 3",
         "CHGOFF", date(1992, 6, 17), "U.S. Bank, National Association",
         "FOIA_7a_FY1991_FY1999_asof_260630.csv"),
    ]  # fmt: skip
