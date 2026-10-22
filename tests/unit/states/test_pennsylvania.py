import dataclasses
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline import states
from include.pipeline.states import stage

FIXTURES = Path(__file__).parents[2] / "fixtures" / "states" / "pennsylvania"
AS_OF = date(2026, 10, 6)


@pytest.fixture
def raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    raw = tmp_path / "raw" / "pa"
    raw.mkdir(parents=True)
    for f in FIXTURES.iterdir():
        shutil.copy(f, raw)
    # 9 officer rows make 4 filings; the real range is set for 4.2M rows
    source = states.SOURCES["pa_corporations"]
    monkeypatch.setitem(
        states.SOURCES, source.name, dataclasses.replace(source, dropped=(5, 5))
    )
    return raw


def test_stage_makes_one_row_per_filing(raw: Path, tmp_path: Path) -> None:
    assert stage("pa_corporations", tmp_path, min_rows=1) == 4

    rows = duckdb.sql(
        f"""select registry_id, norm_name, address, city, zip5, address_kind,
                   entity_type, active, formed_date, officers, as_of,
                   pa_county_name, pa_geo
            from '{tmp_path / "stage" / "registry" / "pa_corporations.parquet"}'
            order by registry_id"""
    ).fetchall()
    assert rows == [
        # a c/o address is a registered agent's, not the place of business
        ("0000000024", "AAA ENTERPRISES", "C/o C T Corporation System 23 S Broad St",
         "PHILA", "19109", "legal", "Foreign Business Corporation", None,
         date(1969, 12, 22), None, AS_OF, "Philadelphia",
         "POINT (-75.16385 39.95128)"),
        # three officer rows; the ZIP "0    -0" is no ZIP
        ("0000187670", "KEO SALES AND SERVICE", "R D 2", "SELINSGROVE", None,
         "physical", "Domestic Business Corporation", None, date(1959, 6, 4),
         ["President: FRANK THARP", "Treasurer: RAYMOND KERSTETTER",
          "Vice President: ELLEN THARP"], AS_OF, None, None),
        # 1753-01-01 is the publisher's placeholder, and no officer is named
        ("0000316249", "STS PETER AND PAUL EVANGELICAL LUTHERAN CHURCH OF CENTRAL CITY",
         "Main St Somerset Co", "CENTRAL CITY", None, "physical",
         "Domestic Nonprofit Corporation", None, None, None, AS_OF, "Somerset",
         None),
        ("0000399042", "D G YUENGLING AND SON", "501 Mahantongo St", "POTTSVILLE",
         "17901", "physical", "Domestic Business Corporation", None,
         date(1914, 4, 9),
         ["Governor: Richard Yuengling, Jr.", "President: RICHARD YUENGLING JR",
          "Secretary: Jennifer Yuengling", "Treasurer: Wendy Yuengling Baker"],
         AS_OF, "Schuylkill", "POINT (-76.19806 40.68286)"),
    ]  # fmt: skip


def test_renamed_header_raises(raw: Path, tmp_path: Path) -> None:
    csv = raw / "pa_corporations.csv"
    csv.write_text(csv.read_text().replace("Filing Number", "Filing No", 1))

    with pytest.raises(ValueError, match="header changed"):
        stage("pa_corporations", tmp_path, min_rows=1)
