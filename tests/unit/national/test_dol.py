import zipfile
from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline.national.dol import stage
from include.pipeline.zips import extract

FIXTURES = Path(__file__).parents[2] / "fixtures" / "national" / "dol"


def zip_fixture(raw: Path, form: str) -> None:
    csv = FIXTURES / f"{form.lower()}_2024_latest.csv"
    with zipfile.ZipFile(raw / f"{form}_2024_Latest.zip", "w") as z:
        z.write(csv, csv.name)
        z.writestr(f"{form.lower()}_2024_latest_layout.txt", "layout")


def test_stage_keeps_every_filing(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "dol"
    raw.mkdir(parents=True)
    zip_fixture(raw, "F_5500")
    zip_fixture(raw, "F_5500_SF")

    assert stage(tmp_path, min_rows=1) == 5

    rows = duckdb.sql(
        f"""select ein, state, plan_name, signer_name, signer_source, plan_eff_date,
                   date_received, is_defined_benefit, form, form_year, zip5,
                   active_participants
            from '{tmp_path / "stage" / "dol_5500_filings.parquet"}'
            order by ein, ack_id"""
    ).fetchall()
    assert rows == [
        ("470871940", "TX",
         "NORTH TEXAS COMPRESSION, INC. 401(K) PROFIT SHARING AND TRUST",
         "DWAYNE GARRETT", "admin_is_sponsor", date(2014, 1, 1), date(2025, 1, 3),
         False, "5500-SF", 2024, "76426", 15),
        # both Texas Instruments filings are kept; the transform picks one
        ("750289970", "TX", "TEXAS INSTRUMENTS 401(K) SAVINGS PLAN", "JANE R DOE",
         "sponsor", date(1988, 1, 1), date(2025, 6, 1), False, "5500", 2024,
         "75266", 24100),
        ("750289970", "TX", "TEXAS INSTRUMENTS EMPLOYEES PENSION PLAN", "JANE R DOE",
         "sponsor", date(1997, 1, 1), date(2025, 7, 15), True, "5500", 2024, "75266",
         1830),
        ("760123456", "TX", "GULF COAST MACHINE WORKS 401(K) PLAN", None, None,
         date(1992, 7, 1), date(2025, 2, 14), False, "5500-SF", 2024, "77075", 31),
        # a sponsor outside Texas is staged too
        ("814786801", "CA", "EXCOLO CONSTRUCTION SERVICES INC 401(K) PLAN",
         "ROBERT FARMAN", "sponsor", date(2020, 1, 1), date(2025, 1, 3), False,
         "5500-SF", 2024, "94502", 6),
    ]  # fmt: skip


def test_extract_never_replaces_its_zip(tmp_path: Path) -> None:
    path = tmp_path / "A.ZIP"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("A.ZIP", "inner")

    with pytest.raises(ValueError, match="its member A.ZIP would replace it"):
        extract(path, ".zip")


def test_extract_keeps_members_in_their_folder(tmp_path: Path) -> None:
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("../evil.csv", "a\n1\n")

    with pytest.raises(ValueError, match="member ../evil.csv leaves"):
        extract(path)


def test_extract_raises_on_two_csvs(tmp_path: Path) -> None:
    path = tmp_path / "F_5500_2024_Latest.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("f_5500_2024_latest.csv", "a\n1\n")
        z.writestr("f_5500_2024_extra.csv", "a\n2\n")

    with pytest.raises(ValueError, match="expected exactly one CSV"):
        extract(path)
