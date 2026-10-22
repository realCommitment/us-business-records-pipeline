import dataclasses
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline import states
from include.pipeline.states import stage

FIXTURES = Path(__file__).parents[2] / "fixtures" / "states" / "texas"
AS_OF = date(2026, 10, 10)


def raw_dir(tmp_path: Path, franchise: str = "tx_franchise.csv") -> Path:
    raw = tmp_path / "raw" / "tx"
    raw.mkdir(parents=True)
    shutil.copy(FIXTURES / franchise, raw / "tx_franchise.csv")
    shutil.copy(FIXTURES / "tx_sales_outlets.csv", raw)
    for name in ("tx_franchise", "tx_sales_outlets"):
        shutil.copy(FIXTURES / f"{name}.csv.meta.json", raw)
    return raw


def test_stage_maps_both_sources_onto_the_contract(tmp_path: Path) -> None:
    raw_dir(tmp_path)

    assert stage("tx_franchise", tmp_path, min_rows=1) == 4
    assert stage("tx_sales_outlets", tmp_path, min_rows=1) == 5

    registry = tmp_path / "stage" / "registry" / "tx_franchise.parquet"
    columns = [c[0] for c in duckdb.sql(f"describe from '{registry}'").fetchall()]
    assert columns == [
        *states.REGISTRY_COLUMNS[:-1],
        "tx_sos_file_number", "tx_record_type", "tx_right_to_transact",
        "tx_sos_status_date", "tx_responsibility_begin_date", "tx_exempt_reason",
        "tx_county_code", "as_of",
    ]  # fmt: skip
    franchise = duckdb.sql(
        f"""select registry_id, ein, norm_name, address_state, zip5, address_kind,
                   entity_type, status, active, formed_date, naics, as_of,
                   tx_record_type
            from '{registry}' order by registry_id"""
    ).fetchall()
    assert franchise == [
        # mails from Connecticut
        ("10101858008", "010185800", "FIRST HARTFORD", "CT", "06042", "mailing",
         "CF", None, True, None, None, AS_OF, "X"),
        ("17412345675", "741234567", "SANCHEZ PLUMBING", "TX", "78332", "mailing",
         "CT", "A", True, date(1979, 6, 1), "238220", AS_OF, "U"),
        ("17502899705", "750289970", "TEXAS INSTRUMENTS", "TX", "75266", "mailing",
         "CF", "A", True, date(1938, 12, 31), "334413", AS_OF, "V"),
        ("32063342011", None, "BULLS LAWN CARE", "TX", "75692", "mailing",
         "CL", "A", True, date(2017, 3, 31), None, AS_OF, "U"),
    ]  # fmt: skip
    outlets = duckdb.sql(
        f"""select registry_id, ein, dba_name, norm_dba_name, city, zip5,
                   first_seen_date, active, tx_permit_issue_date, as_of
            from '{tmp_path / "stage" / "dba" / "tx_sales_outlets.parquet"}'
            order by registry_id"""
    ).fetchall()
    assert outlets == [
        ("17502899705", "750289970", "TEXAS INSTRUMENTS INC", "TEXAS INSTRUMENTS",
         "DALLAS", "75243", date(1961, 9, 1), True, None, AS_OF),
        ("17515166332", "751516633", "LANKMARK INTERIOR BUILDERS, INC.",
         "LANKMARK INTERIOR BUILDERS", "KRUM", "76249", date(2016, 8, 1), True,
         date(2016, 8, 3), AS_OF),
        ("32012345678", None, "LOPEZ TIRE SHOP", "LOPEZ TIRE SHOP", "ALICE",
         "78332", date(1985, 3, 1), True, date(1985, 3, 1), AS_OF),
        ("32034309057", None, "TMK ENTERPRISES", "TMK ENTERPRISES", "ALEDO",
         "76008", date(2007, 12, 15), True, date(2008, 2, 11), AS_OF),
        ("32089812484", None, "SILKY SMOOTH WAXING", "SILKY SMOOTH WAXING",
         "SAN ANTONIO", "78216", date(2024, 8, 1), True, date(2024, 9, 4), AS_OF),
    ]  # fmt: skip


def test_renamed_header_raises(tmp_path: Path) -> None:
    raw_dir(tmp_path, "tx_franchise_renamed_header.csv")

    with pytest.raises(ValueError, match="header changed"):
        stage("tx_franchise", tmp_path, min_rows=1)


def test_malformed_date_raises(tmp_path: Path) -> None:
    raw_dir(tmp_path, "tx_franchise_bad_date.csv")

    with pytest.raises(duckdb.InvalidInputException, match="31/12/1938"):
        stage("tx_franchise", tmp_path, min_rows=1)

    assert not (tmp_path / "stage" / "registry" / "tx_franchise.parquet").exists()


def test_a_select_without_formed_date_fails_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir(tmp_path)
    source = states.SOURCES["tx_franchise"]
    select = f"select * exclude (formed_date) from ({source.select})"
    monkeypatch.setitem(
        states.SOURCES, "tx_franchise", dataclasses.replace(source, select=select)
    )

    missing = r"lacks contract columns \['formed_date'\]"
    with pytest.raises(AssertionError, match=missing):
        stage("tx_franchise", tmp_path, min_rows=1)

    assert not (tmp_path / "stage" / "registry" / "tx_franchise.parquet").exists()
