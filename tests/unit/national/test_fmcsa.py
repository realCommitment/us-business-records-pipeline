import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline.national import fmcsa

FIXTURES = Path(__file__).parents[2] / "fixtures" / "national" / "fmcsa"
AS_OF = date(2026, 10, 17)


def raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw" / "fmcsa"
    raw.mkdir(parents=True)
    for f in FIXTURES.iterdir():
        shutil.copy(f, raw)
    return raw


def test_stage_keeps_every_status_and_country(tmp_path: Path) -> None:
    raw_dir(tmp_path)

    assert fmcsa.stage(tmp_path, min_rows=1) == 5

    rows = duckdb.sql(
        f"""select dot_number, legal_name, dba_name, phy_state, zip5, phy_country,
                   status_code, add_date, mcs150_date, company_officer_1,
                   company_officer_2, classdef, power_units, as_of
            from '{tmp_path / "stage" / "fmcsa_carriers.parquet"}'
            order by dot_number"""
    ).fetchall()
    assert rows == [
        # FMCSA's own record, the sentinel, with its test officer
        (1, "FEDERAL MOTOR CARRIER SAFETY ADMINISTRATION",
         "FMCSA TECHNOLOGY DIVISION", "DC", "20590", "US", "A", date(1974, 6, 1),
         date(2026, 8, 9), "john mary", None,
         "PRIVATE PROPERTY;AUTHORIZED FOR HIRE", 91, AS_OF),
        # inactive, with two officers
        (33, "BELL-VIEW INCORPORATED", None, "GA", "31096", "US", "I",
         date(1974, 6, 1), date(2015, 3, 31), "ADRIANNE BELL JORDAN",
         "FREIDA H. CLAXTON", "PRIVATE PROPERTY", 1, AS_OF),
        # a sole proprietor trading under a DBA
        (44, "GLEN DYER", "DYERS TRUCKING SERVICE", "AL", "36603", "US", "A",
         date(1974, 6, 1), date(2006, 4, 4), "GLEN DYER", None,
         "AUTHORIZED FOR HIRE", 3, AS_OF),
        # an active owner-operator with one truck; its ZIP+4 gives the ZIP
        (2409, "BOGGESS TRUCKING LLC", "JOEL S BOGGESS", "WV", "25143", "US", "A",
         date(1974, 6, 1), date(2024, 7, 17), "JOEL S BOGGESS", None,
         "AUTHORIZED FOR HIRE", 1, AS_OF),
        # staged though abroad; its postal code is no ZIP
        (12004, "MARPOLE TRANSPORT LIMITED", None, "BC", None, "CA", "A",
         date(1974, 6, 1), date(2026, 1, 30), "SARJEET BAWA", "BHAJAN BAWA",
         "AUTHORIZED FOR HIRE", 24, AS_OF),
    ]  # fmt: skip


def test_a_renamed_header_raises(tmp_path: Path) -> None:
    csv = raw_dir(tmp_path) / "fmcsa_census.csv"
    csv.write_text(csv.read_text().replace("DOT_NUMBER,", "USDOT_NUMBER,", 1))

    with pytest.raises(ValueError, match="header changed"):
        fmcsa.stage(tmp_path, min_rows=1)
