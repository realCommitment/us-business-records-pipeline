"""Virginia: the State Corporation Commission's entity files.

data.virginia.gov (CKAN), organization state-corporate-commission:
corporations (corp.xlsx), LLCs (llc.csv), general partnerships (gp.xlsx),
limited partnerships (lp.xlsx) and the officers of all of them (officer.csv).
They are a snapshot (the corporation file is dated 2024-11-14), and llc.csv
and officer.csv stop at Excel's 1,048,575 rows. The downloads redirect to
presigned S3 URLs that answer HEAD with 403, so a one-byte ranged GET reads
the validators. docs/data-sources.md section 10.4.
"""

import json
import logging
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import requests

from include.pipeline.http import HEADERS, TIMEOUT
from include.pipeline.states import File, Source, raw_path, read_default

log = logging.getLogger(__name__)

# installed at image build (Dockerfile); the container's HOME is not writable
EXTENSIONS = "/usr/local/airflow/duckdb_extensions"

ENTITY = (
    "EntityID,Name,Status,StatusReason,Status Date,Duration,IncorpDate,"
    "IncorpState,IndustryCode,Street1,Street2,City,State,Zip,PrinOffEffDate,"
    "RA-Name,RA-Street1,RA-Street2,RA-City,RA-State,RA-Zip,RA-EffDate,RA-Status,"
    "RA-Loc,StockInd,TotalShares,MergerInd,AssessInd"
)


def snake(header: str) -> tuple[str, ...]:
    return tuple(re.sub(r"[^a-z0-9]+", "_", c.lower()) for c in header.split(","))


def ckan(dataset: str, resource: str, name: str) -> str:
    return (
        f"https://data.virginia.gov/dataset/{dataset}/resource/{resource}"
        f"/download/{name}"
    )


# an XLSX header is its column names as read_xlsx reports them, joined by commas
CORP = File(
    "corp.xlsx",
    ckan("3c73d9b4-a544-4cd5-a25f-f522d32815f1",
         "9d79f14f-86cd-4ce2-b2da-2df005958e0d", "corp.xlsx"),
    ENTITY + ",Stock1",
    snake(ENTITY + ",Stock1"),
)  # fmt: skip
LLC = File(
    "llc.csv",
    ckan("cdb25eb3-b177-42c6-97e9-be2b170fd778",
         "6d55efe1-1784-414a-a38e-ce1f6b4be5fe", "llc.csv"),
    ENTITY + ",Is Series LLC,Is Protected Series,Series LLC ID",
    snake(ENTITY + ",Is Series LLC,Is Protected Series,Series LLC ID"),
)  # fmt: skip
GP = File(
    "gp.xlsx",
    ckan("9cfdd2f3-f0f8-47fd-9ce7-c7d638b8139b",
         "883ab241-c33f-40e4-892f-03d0c9dbac4a", "gp.xlsx"),
    ENTITY,
    snake(ENTITY),
)  # fmt: skip
LP = File(
    "lp.xlsx",
    ckan("032a3586-c5b3-4ab2-a473-dac26df96256",
         "77a2ff90-e9f8-401a-8a90-5970d48fdbd2", "lp.xlsx"),
    ENTITY,
    snake(ENTITY),
)  # fmt: skip
OFFICERS = File(
    "officer.csv",
    ckan("178aa97e-3398-4bc2-98c1-0a2ca7f6398f",
         "c72f2bcd-13f7-4b10-b9ba-d2c88802661e", "officer.csv"),
    "EntityID,OfficerLastName,OfficerFirstName,OfficerMiddleName,OfficerTitle",
    ("entityid", "last_name", "first_name", "middle_name", "title"),
)  # fmt: skip
ENTITIES = (CORP, LLC, GP, LP)


def vdate(col: str) -> str:
    """An XLSX Excel serial, an M/D/YYYY date in the CSV, or ISO before 1900.

    Excel counts 1900-02-29, so a serial below 61 is a day later than the
    1899-12-30 epoch gives. Strict: a malformed date fails the stage.
    """
    return f"""case
        when regexp_full_match({col}, '\\d+') then if({col}::INTEGER < 61,
            date '1899-12-31' + {col}::INTEGER, date '1899-12-30' + {col}::INTEGER)
        when {col} like '%/%' then strptime({col}, '%m/%d/%Y')::DATE
        else strptime({col}, '%Y-%m-%d')::DATE end"""


def download(file: File, data: Path) -> bool:
    """Download the file unless its ETag and Last-Modified match the sidecar."""
    dest = raw_path("VA", file, data)
    meta = dest.with_name(dest.name + ".meta.json")
    probe = {**HEADERS, "Range": "bytes=0-0"}
    with requests.get(file.url, headers=probe, timeout=TIMEOUT) as r:
        r.raise_for_status()
        if r.status_code != 206:
            raise RuntimeError(f"{file.url}: a ranged GET answered {r.status_code}")
        seen = {"etag": r.headers.get("ETag"),
                "last_modified": r.headers.get("Last-Modified")}  # fmt: skip
        size = int(r.headers["Content-Range"].rsplit("/", 1)[1])
    if not any(seen.values()):
        raise RuntimeError(f"{file.url}: neither ETag nor Last-Modified")
    if dest.exists() and meta.exists():
        stored = json.loads(meta.read_text())
        same = all(stored.get(k) == v for k, v in seen.items())
        if same and dest.stat().st_size == stored["bytes"]:
            log.info("unchanged %s", dest.name)
            return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with requests.get(file.url, headers=HEADERS, timeout=TIMEOUT, stream=True) as r:
            r.raise_for_status()
            got = 0
            with part.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    got += len(chunk)
        if got != size:
            raise RuntimeError(f"{file.url}: got {got} bytes, Content-Range {size}")
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    record = {"url": file.url, **seen, "bytes": size,
              "downloaded_at": datetime.now(UTC).isoformat()}  # fmt: skip
    meta_part = meta.with_name(meta.name + ".part")
    meta_part.write_text(json.dumps(record, indent=2))
    os.replace(meta_part, meta)
    log.info("downloaded %s %d", dest.name, size)
    return True


def load(con: duckdb.DuckDBPyConnection, file: File, path: Path, table: str) -> None:
    """Load one Virginia file as text, trimmed, after checking its header."""
    if path.suffix != ".xlsx":
        read_default(con, file, path)
        if table != Path(file.name).stem:
            con.execute(f"alter table {Path(file.name).stem} rename to {table}")
        return
    con.execute("SET extension_directory = ?", [EXTENSIONS])
    con.load_extension("excel")
    # stop_at_empty: by default read_xlsx stops, silently, at the first blank row
    quoted = str(path).replace("'", "''")
    source = f"read_xlsx('{quoted}', all_varchar=true, stop_at_empty=false)"
    served = [r[0] for r in con.execute(f"describe select * from {source}").fetchall()]
    if ",".join(served) != file.header:
        raise ValueError(
            f"{path}: header changed\nserved:   {','.join(served)}\n"
            f"expected: {file.header}"
        )
    # fields are padded with spaces, and EntityID starts with a tab
    picks = ", ".join(
        f"nullif(trim(\"{s}\", e' \\t\\r\\n'), '') as {c}"
        for s, c in zip(served, file.columns, strict=True)
    )
    con.execute(f"create temp table {table} as select {picks} from {source}")


def read(con: duckdb.DuckDBPyConnection, file: File, path: Path) -> None:
    load(con, file, path, Path(file.name).stem)
    if file not in ENTITIES:
        return
    # An id another entity file also holds must be the same entity: a
    # corporation converted to an LLC keeps its id (5 on 2026-10-18). Two
    # entities under one id would become one business. Each pair of files is
    # checked once, by the earlier file's source; an unknown date (blank or
    # the placeholder) cannot tell two entities apart.
    stem = Path(file.name).stem
    for other in ENTITIES[ENTITIES.index(file) + 1 :]:
        load(con, other, path.with_name(other.name), "other")
        a, b = (f"nullif({vdate(c)}, date '1899-02-16')"
                for c in ("a.incorpdate", "b.incorpdate"))  # fmt: skip
        shared, differ = con.execute(
            f"""select count(*), count(*) filter (where {a} != {b})
                from (select distinct entityid, incorpdate from {stem}) a
                join (select distinct entityid, incorpdate from other) b
                  using (entityid)"""
        ).fetchall()[0]
        if differ:
            raise ValueError(
                f"{path}: {differ} of {shared} ids shared with {other.name} "
                "have another incorporation date"
            )
        log.info("%s shares %d ids with %s, each one entity", file.name, shared,
                 other.name)  # fmt: skip
        con.execute("drop table other")


# Full state names to codes, for the address state; a name not here (a
# foreign province) stays as published.
STATE_CODES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN",
    "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
    "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
    "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "Puerto Rico": "PR", "Guam": "GU",
    "Virgin Islands": "VI", "U.S. Virgin Islands": "VI", "American Samoa": "AS",
    "Northern Mariana Islands": "MP", "Armed Forces Americas": "AA",
    "Armed Forces Europe": "AE", "Armed Forces Pacific": "AP",
}  # fmt: skip
# the case varies, as in "District Of Columbia"
CODE = (
    "case upper(state) "
    + " ".join(f"when '{n.upper()}' then '{c}'" for n, c in STATE_CODES.items())
    + " end"
)


def select(table: str, entity_type: str) -> str:
    return f"""
        with officers as (
            select entityid,
                   list(distinct coalesce(title || ': ', '')
                                 || concat_ws(' ', first_name, last_name)
                        order by coalesce(title || ': ', '')
                                 || concat_ws(' ', first_name, last_name))
                       as officers
            from officer
            where coalesce(first_name, last_name) is not null
            group by entityid
        ),
        -- an entity listed more than once: its latest status, then the whole
        -- row as text, so the pick is the same every run
        e as (
            select *, {CODE} as state_code
            from {table} t
            qualify row_number() over (
                partition by entityid
                order by {vdate('"status_date"')} desc nulls last,
                         t::VARCHAR) = 1
        )
        select 'VA' as state, e.entityid as registry_id, null::VARCHAR as ein,
               e.name, norm_name(e.name) as norm_name, e.street1 as address,
               upper(e.city) as city, coalesce(e.state_code, e.state)
                   as address_state,
               -- a foreign address has no US state, and its code is no ZIP
               if(regexp_matches(e.zip, '^[0-9]{{5}}') and e.state_code is not null,
                  left(e.zip, 5), null) as zip5,
               'physical' as address_kind, '{entity_type}' as entity_type,
               e.status, {vdate("e.status_date")} as status_date,
               e.status = 'ACTIVE' as active,
               -- 1899-02-16 is a placeholder on LLCs
               nullif({vdate("e.incorpdate")}, date '1899-02-16') as formed_date,
               null::VARCHAR as naics, o.officers,
               e.industrycode as va_industry_code, e.incorpstate as va_incorp_state,
               e.statusreason as va_status_reason, e.ra_name as va_registered_agent
        from e left join officers o using (entityid)"""


SOURCES = tuple(
    Source(
        name=name,
        state="VA",
        kind="registry",
        files=(file, OFFICERS),
        select=select(Path(file.name).stem, entity_type),
        min_rows=min_rows,
        # about two-thirds of the first run's matched share, 72.2% (spec 12 notes)
        min_match_share=0.48,
        dropped=dropped,
        sentinel=sentinel,
        download=download,
        read=read,
    )
    for name, file, entity_type, min_rows, dropped, sentinel in (
        ("va_corporations", CORP, "corporation", 311_000, (17_000, 26_000),
         ("00164871", date(1918, 1, 25))),
        ("va_llcs", LLC, "llc", 733_000, (400, 650),
         ("00036251", date(1901, 2, 23))),
        ("va_partnerships", GP, "general_partnership", 4_960, (50, 80),
         ("K0000119", date(1996, 3, 6))),
        ("va_limited_partnerships", LP, "limited_partnership", 8_580, (290, 440),
         ("L0005035", date(1987, 1, 21))),
    )
)  # fmt: skip
