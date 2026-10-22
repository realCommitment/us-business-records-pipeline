import dataclasses
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from include.pipeline import states
from include.pipeline.states import stage, virginia

FIXTURES = Path(__file__).parents[2] / "fixtures" / "states" / "virginia"
# the 2024 snapshot's Last-Modified dates
CORP_AS_OF, LLC_AS_OF = date(2024, 11, 14), date(2024, 12, 2)


@pytest.fixture
def raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # the image installs excel into EXTENSIONS; on the host it lives in
    # DuckDB's default folder, installed once
    home = Path.home() / ".duckdb" / "extensions"
    duckdb.connect(config={"extension_directory": str(home)}).install_extension("excel")
    monkeypatch.setattr(virginia, "EXTENSIONS", str(home))
    raw = tmp_path / "raw" / "va"
    raw.mkdir(parents=True)
    for f in FIXTURES.iterdir():
        shutil.copy(f, raw)
    # a handful of fixture rows cannot fall in ranges set for the real files
    for name, dropped in (
        ("va_corporations", 1),
        ("va_llcs", 0),
        ("va_partnerships", 0),
        ("va_limited_partnerships", 0),
    ):
        source = dataclasses.replace(states.SOURCES[name], dropped=(dropped, dropped))
        monkeypatch.setitem(states.SOURCES, name, source)
    return raw


def staged(tmp_path: Path, name: str) -> list[tuple[object, ...]]:
    return duckdb.sql(
        f"""select registry_id, name, address_state, zip5, entity_type, status,
                   active, formed_date, officers, as_of
            from '{tmp_path / "stage" / "registry" / f"{name}.parquet"}'
            order by registry_id"""
    ).fetchall()


def test_corporations_read_the_xlsx_and_join_officers(
    raw: Path, tmp_path: Path
) -> None:
    assert stage("va_corporations", tmp_path, min_rows=1) == 3

    assert staged(tmp_path, "va_corporations") == [
        # IncorpDate is the Excel serial 6600
        ("00164871", "UNIVERSAL CORPORATION", "VA", "23235", "corporation", "ACTIVE",
         True, date(1918, 1, 25),
         ["CHRMN/P/CEO: GEORGE FREEMAN III", "SR VP/CFO: JOHAN KRONER",
          "SVP &amp; COO: AIRTON HENTSCHKE", "Vice President: PRESTON WIGNER",
          "Vice President: WUSHUANG MA"], CORP_AS_OF),
        # also in llc.csv with the same incorporation date: one entity
        ("03261807", "MONTEREY PALE COMPANY", "VA", "24465", "corporation", "ACTIVE",
         True, date(1988, 8, 22), None, CORP_AS_OF),
        # listed twice; one row is kept
        ("11001319", "WESTMATIC CORPORATION", "NY", "14225", "corporation", "ACTIVE",
         True, date(2020, 1, 23), None, CORP_AS_OF),
    ]  # fmt: skip


def test_llcs_read_the_csv_past_its_bom(raw: Path, tmp_path: Path) -> None:
    assert (raw / "llc.csv").read_bytes().startswith(b"\xef\xbb\xbfEntityID,")

    assert stage("va_llcs", tmp_path, min_rows=1) == 3

    assert staged(tmp_path, "va_llcs") == [
        ("00036251", "Lumos Telephone of Botetourt LLC", "VA", "22980", "llc",
         "ACTIVE", True, date(1901, 2, 23), None, LLC_AS_OF),
        # 1899-02-16 is a placeholder
        ("00601153", "Handy Distribution LLC", "VA", "24504", "llc", "ACTIVE", True,
         None, None, LLC_AS_OF),
        ("03261807", "MONTEREY PALE, LLC", "VA", "24465", "llc", "ACTIVE", True,
         date(1988, 8, 22), None, LLC_AS_OF),
    ]  # fmt: skip


def test_partnerships_stage(raw: Path, tmp_path: Path) -> None:
    assert stage("va_partnerships", tmp_path, min_rows=1) == 2
    assert stage("va_limited_partnerships", tmp_path, min_rows=1) == 2

    assert [r[:8] for r in staged(tmp_path, "va_partnerships")] == [
        ("11068234", "BOAS PROMOTION", "VA", "22031", "general_partnership",
         "ACTIVE", True, None),
        ("K0000119", "Deloitte LLP", "NY", "10112", "general_partnership", "ACTIVE",
         True, date(1996, 3, 6)),
    ]  # fmt: skip
    assert [r[:8] for r in staged(tmp_path, "va_limited_partnerships")] == [
        ("L0002297", "RM LAND L.P.", "VA", "23219", "limited_partnership",
         "INACTIVE", False, date(1987, 1, 5)),
        ("L0005035", "GENERAL INVESTORS REALTY ASSOCIATES, A LIMITED PARTNERSHIP",
         "VA", "23462", "limited_partnership", "ACTIVE", True, date(1987, 1, 21)),
    ]  # fmt: skip


def test_two_entities_under_one_id_raise(raw: Path, tmp_path: Path) -> None:
    llc = raw / "llc.csv"
    text = llc.read_text(encoding="utf-8-sig")
    llc.write_text(text.replace("8/22/1988", "8/23/1988"))

    # the earlier file's source checks the pair
    with pytest.raises(ValueError, match="1 of 1 ids shared with llc.csv"):
        stage("va_corporations", tmp_path, min_rows=1)


def test_an_unknown_date_on_a_shared_id_passes(raw: Path, tmp_path: Path) -> None:
    llc = raw / "llc.csv"
    text = llc.read_text(encoding="utf-8-sig")
    llc.write_text(text.replace("8/22/1988", "1899-02-16"))

    assert stage("va_corporations", tmp_path, min_rows=1) == 3


def test_a_renamed_xlsx_header_raises(raw: Path, tmp_path: Path) -> None:
    con = duckdb.connect(config={"extension_directory": virginia.EXTENSIONS})
    con.load_extension("excel")
    corp = str(raw / "corp.xlsx")
    con.execute(
        f"copy (select * rename (EntityID as Entity) from read_xlsx('{corp}', "
        f"all_varchar=true)) to '{corp}' (format xlsx, header true)"
    )

    with pytest.raises(ValueError, match="header changed"):
        stage("va_corporations", tmp_path, min_rows=1)
