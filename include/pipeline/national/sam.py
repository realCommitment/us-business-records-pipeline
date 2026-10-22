import json
import logging
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import requests

from include.pipeline.db import connect, copy_to_parquet
from include.pipeline.http import HEADERS, TIMEOUT
from include.pipeline.paths import DATA
from include.pipeline.zips import extract

log = logging.getLogger(__name__)

# SAM.gov's public V2 entity extract; docs/data-sources.md section 8. The
# keyless endpoints are the ones the sam.gov website uses, undocumented.
LIST = (
    "https://sam.gov/api/prod/fileextractservices/v1/api/listfiles"
    "?domain=Entity%20Registration/Public%20V2&privacy=Public"
)
DOWNLOAD = (
    "https://sam.gov/api/prod/fileextractservices/v1/api/download/"
    "Entity%20Registration/Public%20V2/{name}?privacy=Public"
)
NAME = re.compile(r"SAM_PUBLIC_UTF-8_MONTHLY_V2_(\d{8})\.ZIP")
FIELDS = 142

# Pipe-delimited, no header; a field that holds a pipe is wrapped in NUL
# bytes, which read_csv cannot take as a quote. So each line is read whole,
# pipes inside the NUL-quoted (even-numbered) parts are masked, and the line
# is split. 1-based field positions follow GSA's "SAM Public V2 extract"
# layout, checked against records of the 2026-10-05 file (notes of spec 09).
STAGE_SQL = r"""
with records as (
    select list_transform(
               string_split(array_to_string(
                   list_transform(string_split(line, chr(0)),
                                  (p, i) -> if(i % 2 = 0, replace(p, '|', chr(1)), p)),
                   ''), '|'),
               v -> replace(v, chr(1), '|')) as f
    from read_csv(?, header=false, columns={'line': 'VARCHAR'}, delim=e'\x01',
                  quote='', escape='', auto_detect=false)
    where not starts_with(line, 'BOF ') and not starts_with(line, 'EOF ')
),
fields as (
    select len(f) as field_count,
           list_transform(f, v -> nullif(trim(v), '')) as v
    from records
)
select field_count,
       v[1] as uei,
       -- with the UEI, unique: one entity can have several registrations
       v[3] as eft_indicator,
       v[4] as cage,
       -- a record can carry two registrations as "A~E", with paired dates;
       -- the first is the one the status names first
       contains(v[6], '~') as paired,
       split_part(v[6], '~', 1) as registration_status,
       strptime(split_part(v[11], '~', 1), '%Y%m%d')::DATE as activation_date,
       strptime(split_part(v[9], '~', 1), '%Y%m%d')::DATE as expiration_date,
       if(contains(v[6], '~'), split_part(v[12], '~', 1), v[12]) as legal_name,
       norm_name(legal_name) as norm_name,
       if(contains(v[6], '~'), split_part(v[13], '~', 1), v[13]) as dba_name,
       norm_name(dba_name) as norm_dba_name,
       v[16] as address_1,
       v[17] as address_2,
       upper(v[18]) as city,
       v[19] as state,
       if(regexp_full_match(v[20], '[0-9]{5}'), v[20], null) as zip5,
       v[22] as country,
       strptime(v[25], '%Y%m%d')::DATE as start_date,
       v[28] as entity_structure,
       v[33] as primary_naics,
       v[35] as naics_list,
       v[47] as gov_poc_first_name,
       v[49] as gov_poc_last_name,
       v[91] as elec_poc_first_name,
       v[93] as elec_poc_last_name
from fields
"""


def newest(listing: dict[str, Any]) -> str:
    """The newest UTF-8 monthly file in a listing, by the date in its name."""
    dated = {}
    for o in listing["_embedded"]["customS3ObjectSummaryList"]:
        m = NAME.fullmatch(o["displayKey"])
        if m:
            dated[m.group(1)] = str(o["displayKey"])
    if not dated:
        raise ValueError(f"{LIST}: no SAM_PUBLIC_UTF-8_MONTHLY_V2 file listed")
    return dated[max(dated)]


def discover() -> str:
    r = requests.get(LIST, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    name = newest(r.json())
    log.info("sam_discover %s", name)
    return name


def download(name: str, data: Path = DATA) -> bool:
    """Download the dated file unless it is already on disk with its size.

    The link answers 303 to a signed S3 URL that rejects HEAD, so the dated
    name, not a validator, says whether it changed.
    """
    dest = data / "raw" / "sam" / name
    meta = dest.with_name(dest.name + ".meta.json")
    if dest.exists() and meta.exists():
        if json.loads(meta.read_text())["bytes"] == dest.stat().st_size:
            log.info("unchanged %s", name)
            return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = DOWNLOAD.format(name=name)
    part = dest.with_name(dest.name + ".part")
    try:
        with requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True) as r:
            r.raise_for_status()
            # S3 always sends it; without it a truncated file would count as
            # unchanged until the next month's name
            expected = int(r.headers["Content-Length"])
            size = 0
            with part.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    size += len(chunk)
        if size != expected:
            raise RuntimeError(f"{url}: got {size} bytes, Content-Length {expected}")
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    record = {"url": url, "bytes": size, "downloaded_at": datetime.now(UTC).isoformat()}
    meta_part = meta.with_name(meta.name + ".part")
    meta_part.write_text(json.dumps(record, indent=2))
    os.replace(meta_part, meta)
    log.info("downloaded %s %d", name, size)
    return True


def stage(name: str, data: Path = DATA, min_rows: int = 630_000) -> int:
    """Write every record of the newest extract to stage/sam_entities.parquet."""
    outer = data / "raw" / "sam" / name
    # the inner zip has the outer zip's name, so it goes in a folder of its own
    inner = extract(outer, ".zip", into=outer.with_name(outer.name + ".unzipped"))
    dat = extract(inner, ".dat")
    with dat.open(encoding="utf-8") as f:
        bof = f.readline().split()
    # BOF PUBLIC V2 00000000 <date> <record count> <sequence>
    if bof[:3] != ["BOF", "PUBLIC", "V2"] or len(bof) != 7:
        raise ValueError(f"{dat}: first line {' '.join(bof)!r} is not a V2 BOF line")
    declared = int(bof[5])
    con = connect()
    con.execute(f"create temp table sam as {STAGE_SQL}", [str(dat)])
    rows, unique, bad_width, us, paired, sentinel = con.execute(
        f"""select count(*), count(distinct (uei, eft_indicator)),
                   count(*) filter (where field_count != {FIELDS}),
                   count(*) filter (where country = 'USA'),
                   count(*) filter (where paired),
                   list(distinct start_date) filter (where uei = ?)
            from sam""",
        [SENTINEL[0]],
    ).fetchall()[0]
    # checked before writing, so a bad read never replaces the previous file
    assert rows == declared, f"{dat}: {rows} records, the BOF line says {declared}"
    assert unique == rows, f"{dat}: {rows - unique} repeated (uei, eft_indicator) pairs"
    assert bad_width == 0, f"{dat}: {bad_width} records without {FIELDS} fields"
    assert rows >= min_rows, f"{dat}: {rows} records, expected >= {min_rows}"
    assert sentinel == [SENTINEL[1]], (
        f"{dat}: sentinel {SENTINEL[0]} started {sentinel}, expected {SENTINEL[1]}"
    )
    out = data / "stage" / "sam_entities.parquet"
    copy_to_parquet(con, "select * exclude (field_count, paired) from sam", out)
    log.info("sam_stage records=%d us=%d paired=%d", rows, us, paired)
    return int(rows)


# International Business Machines Corporation, Armonk, NY 10504
SENTINEL = ("J64CSQTQNRC1", date(1911, 6, 16))
