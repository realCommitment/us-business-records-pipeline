import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline.national.ppp import parse_links, stage

FIXTURES = Path(__file__).parents[2] / "fixtures" / "national" / "ppp"
BASE = "https://data.sba.gov/sites/default/files/distribution/SBA-OCA-2022-07-001/"


URLS = [BASE + p.name for p in sorted(FIXTURES.glob("*.csv"))]


def raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw" / "ppp"
    raw.mkdir(parents=True)
    for csv in FIXTURES.glob("*.csv"):
        shutil.copy(csv, raw)
    return raw


def test_stage_keeps_every_state_typed(tmp_path: Path) -> None:
    raw = raw_dir(tmp_path)
    # an older release the page no longer lists stays on disk, uncounted
    shutil.copy(
        FIXTURES / "public_up_to_150k_1_240930.csv",
        raw / "public_up_to_150k_99_240930.csv",
    )

    assert stage(URLS, tmp_path, min_rows=1) == 6

    rows = duckdb.sql(
        f"""select loan_number, norm_name, dba_norm_name, city, zip5, state, naics,
                   nonprofit, date_approved::VARCHAR, loan_status_date,
                   jobs_reported
            from '{tmp_path / "stage" / "ppp.parquet"}' order by loan_number"""
    ).fetchall()
    assert rows == [
        (1000000001, "SUMTER COATINGS", None, "GARLAND", "75041", "TX", "238320",
         False, "2020-04-15", date(2021, 3, 9), 22),
        # out-of-state loans are staged too
        (1000000002, "OKIE ROOFING", None, "TULSA", "74103", "OK", "238160",
         False, "2020-05-01", None, 12),
        (1000000003, "SMITH JONES AND", None, "SHREVEPORT", "71101", "LA",
         "541211", False, "2020-06-02", None, 9),
        (2000000001, "ROBERT GARZA", "COOL AIR", "LAREDO", "78040", "TX", "238220",
         False, "2021-01-22", None, 1),
        (2000000002, "FIRST BAPTIST CHURCH OF ALVIN", None, "ALVIN", "77511", "TX",
         "813110", True, "2020-04-28", None, 14),
        (2000000003, "SMITH", None, "EL PASO", "79901", "TX", None,
         False, "2020-05-05", None, 5),
    ]  # fmt: skip


def test_stage_raises_on_a_listed_file_not_downloaded(tmp_path: Path) -> None:
    raw_dir(tmp_path)
    missing = BASE + "public_up_to_150k_2_240930.csv"

    with pytest.raises(FileNotFoundError, match="public_up_to_150k_2_240930.csv"):
        stage([*URLS, missing], tmp_path, min_rows=1)


def test_parse_links_returns_the_13_files_sorted() -> None:
    links = parse_links((FIXTURES / "page.html").read_text())

    assert links == [
        BASE + "public_150k_plus_240930.csv",
        *(BASE + f"public_up_to_150k_{n}_240930.csv" for n in (10, 11, 12)),
        *(BASE + f"public_up_to_150k_{n}_240930.csv" for n in range(1, 10)),
    ]


def test_parse_links_raises_on_too_few_links() -> None:
    page = "".join(
        f'<a href="{BASE}public_up_to_150k_{n}_240930.csv">x</a>' for n in (1, 2)
    )

    with pytest.raises(ValueError, match="2 PPP CSV links, expected at least 13"):
        parse_links(page)


def test_parse_links_raises_on_two_releases_of_one_file() -> None:
    page = (FIXTURES / "page.html").read_text()
    page += f'<a href="{BASE}public_up_to_150k_1_250331.csv">x</a>'

    with pytest.raises(ValueError, match="a file appears in two releases"):
        parse_links(page)
