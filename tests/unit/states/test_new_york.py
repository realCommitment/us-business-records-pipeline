import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline.states import stage

FIXTURES = Path(__file__).parents[2] / "fixtures" / "states" / "new_york"
AS_OF = date(2026, 10, 16)


def raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw" / "ny"
    raw.mkdir(parents=True)
    for f in FIXTURES.iterdir():
        shutil.copy(f, raw)
    return raw


def test_stage_maps_corporations_onto_the_contract(tmp_path: Path) -> None:
    raw_dir(tmp_path)

    assert stage("ny_corporations", tmp_path, min_rows=1) == 3

    rows = duckdb.sql(
        f"""select registry_id, name, norm_name, address, city, zip5, address_kind,
                   entity_type, status, active, formed_date, officers, as_of,
                   ny_county, ny_dos_process_name, ny_location_name, ny_ceo_address
            from '{tmp_path / "stage" / "registry" / "ny_corporations.parquet"}'
            order by registry_id"""
    ).fetchall()
    assert rows == [
        # a location ZIP: the place of business
        ("1475703", "WILD APACHE PRODUCTIONS INC.", "WILD APACHE PRODUCTIONS",
         "1388 FOREST AVENUE", "BALDWIN", "11510", "physical",
         "DOMESTIC BUSINESS CORPORATION", None, None, date(1990, 9, 18),
         ["CEO: WILLIAM ANTHONY MARAGH"], AS_OF, "Nassau",
         "WILD APACHE PRODUCTIONS INC.", "WILD APACHE PRODUCTIONS INC.",
         "WILLIAM ANTHONY MARAGH, BALDWIN, NY, 11510"),
        # no location: the address for legal papers, here an agent's
        ("30059", "INTERNATIONAL BUSINESS MACHINES CORPORATION",
         "INTERNATIONAL BUSINESS MACHINES", "80 STATE STREET", "ALBANY", "12207",
         "legal", "DOMESTIC BUSINESS CORPORATION", None, None, date(1911, 6, 16),
         ["CEO: ARVIND KRISHNA"], AS_OF, "Westchester",
         "C/O CORPORATION SERVICE COMPANY", None, "ARVIND KRISHNA, ARMONK, NY, 10504"),
        ("4424185", "BUTCHY'S WINE & SPIRITS, INC.", "BUTCHYS WINE AND SPIRITS",
         "23 BUSHNEIL PLACE", "MOUNT VERNON", "10550", "legal",
         "DOMESTIC BUSINESS CORPORATION", None, None, date(2013, 6, 27), None, AS_OF,
         "Westchester", "BUTCHY'S WINE & SPIRITS, INC.", None, None),
    ]  # fmt: skip


def test_renamed_header_raises(tmp_path: Path) -> None:
    csv = raw_dir(tmp_path) / "ny_corporations.csv"
    csv.write_text(csv.read_text().replace("DOS ID,", "DOS Id,", 1))

    with pytest.raises(ValueError, match="header changed"):
        stage("ny_corporations", tmp_path, min_rows=1)
