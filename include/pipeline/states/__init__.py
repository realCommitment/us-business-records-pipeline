"""The contract every state registry and trade-name source follows.

Everything about one state lives in its module here, which holds that state's
SOURCES; no other pipeline file names a state. Adding a state is one new
module, one line in STATES, a fixture and a test.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal

import duckdb

from include.pipeline.db import connect, copy_to_parquet
from include.pipeline.http import download_if_changed
from include.pipeline.paths import DATA

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class File:
    name: str  # raw file name under raw/<state lowercased>/
    url: str
    header: str  # first line exactly as served, stray spaces included
    columns: tuple[str, ...]  # our names for those columns, in order


@dataclass(frozen=True)
class Source:
    name: str  # stage file name, e.g. "tx_franchise"
    state: str  # two-letter code
    kind: Literal["registry", "dba"]
    files: tuple[File, ...]  # each becomes a temp table named after the file stem
    select: str  # SQL over those tables producing the stage rows
    min_rows: int
    dropped: tuple[int, int]  # allowed (first file's raw rows - staged rows)
    sentinel: tuple[str, date] | None  # registry_id and formed_date to be staged
    min_match_share: float = 0.30
    download: Callable[[File, Path], bool] | None = None  # (file, data)
    read: Callable[[duckdb.DuckDBPyConnection, File, Path], None] | None = None


# address_state is the address's own state when it can differ from the
# registry's, such as a Texas taxpayer mailing from New York; NULL means state
REGISTRY_COLUMNS = (
    "state", "registry_id", "ein", "name", "norm_name", "address", "city",
    "address_state", "zip5", "address_kind", "entity_type", "status",
    "status_date", "active", "formed_date", "naics", "officers", "as_of",
)  # fmt: skip
DBA_COLUMNS = (
    "state", "registry_id", "ein", "entity_type", "dba_name", "norm_dba_name",
    "address", "city", "zip5", "first_seen_date", "active", "naics", "as_of",
)  # fmt: skip
ADDRESS_KINDS = ("physical", "mailing", "legal")


def mdy(col: str) -> str:
    # strict: a malformed date fails the stage instead of becoming NULL
    return f"strptime({col}, '%m/%d/%Y')::DATE"


def raw_path(state: str, file: File, data: Path = DATA) -> Path:
    return data / "raw" / state.lower() / file.name


def read_default(con: duckdb.DuckDBPyConnection, file: File, path: Path) -> None:
    """Check the served header, then load the file trimmed, as text."""
    with path.open(encoding="utf-8-sig") as f:
        served = f.readline().rstrip("\r\n")
    if served != file.header:
        raise ValueError(
            f"{path}: header changed\nserved:   {served}\nexpected: {file.header}"
        )
    # some exports pad fields with spaces, blank codes are two spaces, and a
    # few quoted fields end in a newline
    con.execute(
        f"create temp table {Path(file.name).stem} as "
        r"select nullif(trim(columns(*), e' \t\r\n'), '') "
        "from read_csv(?, header=true, all_varchar=true, names=?)",
        [str(path), list(file.columns)],
    )


from include.pipeline.states import (  # noqa: E402
    colorado,
    connecticut,
    district_of_columbia,
    florida,
    iowa,
    new_york,
    oregon,
    pennsylvania,
    texas,
    virginia,
)

STATES = (
    texas,
    new_york,
    pennsylvania,
    colorado,
    florida,
    oregon,
    connecticut,
    district_of_columbia,
    iowa,
    virginia,
)

SOURCES: dict[str, Source] = {}
FILES: dict[str, tuple[str, File]] = {}
for _module in STATES:
    for _source in _module.SOURCES:
        if _source.name in SOURCES:
            raise ValueError(f"{_module.__name__}: source {_source.name} is repeated")
        SOURCES[_source.name] = _source
        for _file in _source.files:
            seen = FILES.setdefault(_file.name, (_source.state, _file))
            if seen != (_source.state, _file):
                raise ValueError(f"{_module.__name__}: two files named {_file.name}")


def download(file_name: str, data: Path = DATA) -> bool:
    state, file = FILES[file_name]
    source = next(s for s in SOURCES.values() if file in s.files)
    if source.download:
        return source.download(file, data)
    return download_if_changed(file.url, raw_path(state, file, data))


def as_of(path: Path) -> date:
    """The publisher's data date: the sidecar's Last-Modified, else the download."""
    meta = json.loads(path.with_name(path.name + ".meta.json").read_text())
    if meta.get("last_modified"):
        return parsedate_to_datetime(meta["last_modified"]).date()
    # the contract's rule for publishers that send no Last-Modified
    log.info("as_of %s: no last_modified, dated by the download", path.name)
    return datetime.fromisoformat(meta["downloaded_at"]).date()


def stage_path(source: Source, data: Path = DATA) -> Path:
    return data / "stage" / source.kind / f"{source.name}.parquet"


def stage_paths(kind: str, data: Path = DATA) -> list[str]:
    """The stage files of one kind that the transform reads."""
    return [str(stage_path(s, data)) for s in SOURCES.values() if s.kind == kind]


def stage(name: str, data: Path = DATA, min_rows: int | None = None) -> int:
    """Write the source's stage file from its raw files; return the row count."""
    source = SOURCES[name]
    con = connect()
    paths = [raw_path(source.state, f, data) for f in source.files]
    for file, path in zip(source.files, paths, strict=True):
        (source.read or read_default)(con, file, path)
    first = Path(source.files[0].name).stem
    raw_rows = int(con.execute(f"select count(*) from {first}").fetchall()[0][0])
    con.execute(
        "create temp table staged as "
        f"select *, ?::DATE as as_of from ({source.select})",
        [as_of(paths[0])],
    )
    src = paths[0]
    columns = [r[0] for r in con.execute("describe staged").fetchall()]
    common = REGISTRY_COLUMNS if source.kind == "registry" else DBA_COLUMNS
    prefix = source.state.lower() + "_"
    missing = [c for c in common if c not in columns]
    stray = [c for c in columns if c not in common and not c.startswith(prefix)]
    # checked before writing, so a bad export never replaces the previous file
    assert not missing, f"{src}: {name} lacks contract columns {missing}"
    assert not stray, f"{src}: {name} extras {stray} lack the prefix {prefix}"

    rows, bad_ein = con.execute(
        "select count(*), "
        "count(*) filter (where not regexp_full_match(ein, '[0-9]{9}')) from staged"
    ).fetchall()[0]
    floor = source.min_rows if min_rows is None else min_rows
    low, high = source.dropped
    dropped = raw_rows - rows
    assert rows >= floor, f"{src}: {name} staged {rows} rows, expected >= {floor}"
    assert low <= dropped <= high, (
        f"{src}: {name} dropped {dropped} of {raw_rows} rows, expected {low}-{high}"
    )
    assert bad_ein == 0, f"{src}: {name} has {bad_ein} EINs that are not 9 digits"
    if source.kind == "registry":
        unique, bad_kind = con.execute(
            "select count(distinct registry_id), count(*) filter (where "
            "address_kind is null or not list_contains(?, address_kind)) from staged",
            [list(ADDRESS_KINDS)],
        ).fetchall()[0]
        assert unique == rows, f"{src}: {name} repeats {rows - unique} registry_ids"
        assert bad_kind == 0, f"{src}: {name} has {bad_kind} rows without address_kind"
        if source.sentinel:
            registry_id, formed = source.sentinel
            seen = con.execute(
                "select list(formed_date) from staged where registry_id = ?",
                [registry_id],
            ).fetchall()[0][0]
            assert seen == [formed], (
                f"{src}: {name} sentinel {registry_id} formed {seen}, expected {formed}"
            )
    copy_to_parquet(con, "select * from staged", stage_path(source, data))
    log.info("state_stage %s raw=%d rows=%d dropped=%d", name, raw_rows, rows, dropped)
    return int(rows)
