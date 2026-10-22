"""Iowa: the Secretary of State's "Active Iowa Business Entities".

data.iowa.gov dataset 554, CC BY 4.0, refreshed monthly, active entities only.
The portal left Socrata (the old id ez5t-3qay returns 404), and URL is the one
its download button builds (getDownloadUrl), undocumented. The download is a
zip holding one CSV. It sends neither ETag nor Last-Modified, so the file is
downloaded in full each run and the old copy kept when its SHA-256 is
unchanged. docs/data-sources.md section 10.6.
"""

import hashlib
import json
import logging
import os
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import requests

from include.pipeline import zips
from include.pipeline.http import HEADERS, TIMEOUT
from include.pipeline.states import File, Source, raw_path, read_default

log = logging.getLogger(__name__)

URL = "https://data.iowa.gov/api/dataset-download?path=datasets%2F554%2Frows.csv"
HEADER = (
    "corp_number,legal_name,corporation_type,effective_date,registered_agent,"
    "ra_address_1,ra_address_2,ra_city,ra_state,ra_zip,ra_latitude,ra_longitude,"
    "ra_location,home_office,ho_address_1,ho_address_2,ho_city,ho_state,ho_zip,"
    "ho_country,ho_latitude,ho_longitude,ho_location"
)
ENTITIES = File("ia_business_entities.zip", URL, HEADER, tuple(HEADER.split(",")))


def download(file: File, data: Path) -> bool:
    """Download the zip; keep the old copy when its SHA-256 is unchanged."""
    dest = raw_path("IA", file, data)
    meta = dest.with_name(dest.name + ".meta.json")
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256()
    size = 0
    try:
        with requests.get(file.url, headers=HEADERS, timeout=TIMEOUT, stream=True) as r:
            r.raise_for_status()
            # the portal sends none (2026-10-18); a length that is sent is checked
            expected = r.headers.get("Content-Length")
            with part.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    sha.update(chunk)
                    size += len(chunk)
        if expected is not None and size != int(expected):
            raise RuntimeError(
                f"{file.url}: got {size} bytes, Content-Length {expected}"
            )
        # without a length, a cut-off download shows as a damaged zip; it must
        # not replace the good copy
        with zipfile.ZipFile(part) as z:
            bad = z.testzip()
        if bad is not None:
            raise RuntimeError(f"{file.url}: member {bad} of the download is damaged")
        digest = sha.hexdigest()
        if dest.exists() and meta.exists():
            stored = json.loads(meta.read_text())
            if stored["sha256"] == digest and dest.stat().st_size == size:
                part.unlink()
                log.info("unchanged %s", dest.name)
                return False
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    record = {"url": file.url, "sha256": digest, "bytes": size,
              "content_length": expected,
              "downloaded_at": datetime.now(UTC).isoformat()}  # fmt: skip
    meta_part = meta.with_name(meta.name + ".part")
    meta_part.write_text(json.dumps(record, indent=2))
    os.replace(meta_part, meta)
    log.info("downloaded %s %d", dest.name, size)
    return True


def read(con: duckdb.DuckDBPyConnection, file: File, zip_path: Path) -> None:
    # streaming the zip through funzip failed ("zipfile ended prematurely")
    read_default(con, file, zips.extract(zip_path))


SOURCES = (
    Source(
        name="ia_business_entities",
        state="IA",
        kind="registry",
        files=(ENTITIES,),
        select="""
            select 'IA' as state, corp_number as registry_id, null::VARCHAR as ein,
                   legal_name as name, norm_name(legal_name) as norm_name,
                   ho_address_1 as address, upper(ho_city) as city,
                   ho_state as address_state,
                   -- a foreign postal code is no ZIP
                   if(regexp_matches(ho_zip, '^[0-9]{5}')
                      and coalesce(ho_country, 'USA') = 'USA', left(ho_zip, 5), null)
                       as zip5,
                   'physical' as address_kind, corporation_type as entity_type,
                   null::VARCHAR as status, null::DATE as status_date,
                   -- the list drops entities dissolved for missed reports
                   true as active,
                   effective_date::DATE as formed_date,
                   null::VARCHAR as naics, null::VARCHAR[] as officers,
                   registered_agent as ia_registered_agent, ra_city as ia_ra_city,
                   ho_country as ia_ho_country
            from ia_business_entities""",
        min_rows=243_000,
        # about two-thirds of the first run's matched share, 64.6% (spec 12 notes)
        min_match_share=0.43,
        dropped=(0, 0),
        sentinel=("019862", date(1938, 1, 3)),
        download=download,
        read=read,
    ),
)
