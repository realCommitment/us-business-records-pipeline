"""Florida: the Department of State, Division of Corporations.

The quarterly full corporate file, cordata.zip, on the Division's SFTP server
(refreshed in January, April, July and October), read with the public login
the Division publishes for its free data downloads. Its records are 1,440
fixed-width characters; the offsets below follow the Division's corporate
file layout, checked against a real record. docs/data-sources.md section 10.1.
"""

import json
import logging
import os
import subprocess
from datetime import UTC, date, datetime
from email.utils import format_datetime
from pathlib import Path

import duckdb

from include.pipeline.states import File, Source, raw_path

log = logging.getLogger(__name__)

URL = "sftp://sftp.floridados.gov/Public/doc/quarterly/cor/cordata.zip"
# published by the Division for public access, not a secret (decision 15)
LOGIN = "Public:PubAccess1845!"
# SHA-256 of the server's ECDSA host key, pinned on 2026-10-17 with
# ssh-keyscan; a changed key fails the download instead of trusting it
HOST_KEY = "TPtpEBn4t/fjdWpecrIQ0BgLXRAqj9wjDkoCNIggZEE="
MEMBERS = [f"cordata{n}.txt" for n in range(10)]
WIDTH = 1440

CORDATA = File("cordata.zip", URL, "", ())


def curl(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["curl", "--silent", "--show-error", "--fail", "--hostpubsha256", HOST_KEY,
             "--user", LOGIN, *args],
            check=True, capture_output=True, text=True, timeout=7200,
        )  # fmt: skip
    except subprocess.CalledProcessError as e:
        # curl's own message, such as a changed host key, is the cause
        raise RuntimeError(f"curl {args[-1]}: {e.stderr.strip()}") from e


def remote_size_and_time(tmp: Path) -> tuple[int, datetime]:
    """The file's size from the directory listing and its modification time.

    `curl --head` prints nothing over SFTP, and the listing's date has no year,
    so the time comes from a one-byte read with --remote-time.
    """
    folder = URL.rsplit("/", 1)[0] + "/"
    listing = curl(folder).stdout.splitlines()
    sizes = [int(f[4]) for f in map(str.split, listing) if f[-1:] == ["cordata.zip"]]
    if len(sizes) != 1:
        raise RuntimeError(f"{folder}: listing has no single cordata.zip: {listing}")
    probe = tmp.with_name(tmp.name + ".probe")
    try:
        curl("--range", "0-0", "--remote-time", "--output", str(probe), URL)
        mtime = datetime.fromtimestamp(probe.stat().st_mtime, UTC)
    finally:
        probe.unlink(missing_ok=True)
    return sizes[0], mtime


def download(file: File, data: Path) -> bool:
    """Download cordata.zip unless its size and modification time are unchanged."""
    dest = raw_path("FL", file, data)
    meta = dest.with_name(dest.name + ".meta.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    size, mtime = remote_size_and_time(dest)
    seen = {"bytes": size, "last_modified": format_datetime(mtime, usegmt=True)}
    if dest.exists() and meta.exists():
        stored = json.loads(meta.read_text())
        same = all(stored.get(k) == v for k, v in seen.items())
        if same and dest.stat().st_size == size:
            log.info("unchanged %s", dest.name)
            return False
    part = dest.with_name(dest.name + ".part")
    try:
        curl("--output", str(part), URL)
        got = part.stat().st_size
        if got != size:
            raise RuntimeError(f"{URL}: got {got} bytes, the listing says {size}")
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    record = {"url": URL, **seen, "downloaded_at": datetime.now(UTC).isoformat()}
    meta_part = meta.with_name(meta.name + ".part")
    meta_part.write_text(json.dumps(record, indent=2))
    os.replace(meta_part, meta)
    log.info("downloaded %s %d", dest.name, size)
    return True


def read(con: duckdb.DuckDBPyConnection, file: File, zip_path: Path) -> None:
    """Unzip the members beside the zip, then view them as one line per row.

    The zip uses Deflate64, which Python's zipfile cannot read, so unzip does.
    Latin-1 makes a character one byte, so offsets are byte offsets.
    """
    names = subprocess.run(
        ["unzip", "-Z1", str(zip_path)], check=True, capture_output=True, text=True
    ).stdout.split()
    if sorted(names) != MEMBERS:
        raise ValueError(f"{zip_path}: members {names}, expected {MEMBERS}")
    members = []
    for name in MEMBERS:
        dest = zip_path.with_name(name)
        members.append(str(dest))
        if dest.exists() and dest.stat().st_mtime > zip_path.stat().st_mtime:
            continue
        part = dest.with_name(dest.name + ".part")
        try:
            with part.open("wb") as out:
                unzip = ["unzip", "-p", str(zip_path), name]
                subprocess.run(unzip, check=True, stdout=out)
            os.replace(part, dest)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        log.info("extracted %s", name)
    # a 13M-row stage: spill under stage/ rather than the working directory
    data = zip_path.parents[2]  # <data>/raw/fl/cordata.zip
    tmp = str(data / "stage" / "_tmp_fl").replace("'", "''")
    con.execute(f"SET temp_directory = '{tmp}'")
    # a view cannot take a prepared parameter, so the paths are quoted inline
    paths = ", ".join("'" + m.replace("'", "''") + "'" for m in members)
    con.execute(
        f"create temp view cordata as select line from read_csv([{paths}], "
        "header=false, columns={'line': 'VARCHAR'}, delim=e'\\x01', quote='', "
        "escape='', encoding='latin-1', auto_detect=false)"
    )
    bad, sentinel_fei = con.execute(
        # a blank line reads as NULL, so "is distinct from" counts it
        f"""select count(*) filter (where length(line) is distinct from {WIDTH}),
                   coalesce(list(substr(line, 481, 14))
                                filter (where trim(substr(line, 1, 12)) = '444750'),
                            [])
            from cordata"""
    ).fetchall()[0]
    if bad:
        raise ValueError(f"{zip_path}: {bad} lines are not {WIDTH} characters")
    # Raymond James Financial's FEI, the EIN check the contract has no slot for
    if [f.replace("-", "").strip() for f in sentinel_fei] != ["591517485"]:
        raise ValueError(
            f"{zip_path}: 444750 has FEI {sentinel_fei}, expected 591517485"
        )


def field(start: int, end: int) -> str:
    """A 1-based, inclusive slice of the record, trimmed, blank as NULL."""
    return f"nullif(trim(substr(line, {start}, {end - start + 1})), '')"


def officer(n: int) -> str:
    base = 128 * (n - 1)
    title, name = field(669 + base, 672 + base), field(674 + base, 715 + base)
    # the name is last, first and middle in padded subfields
    name = f"regexp_replace({name}, ' +', ' ', 'g')"
    return f"if({name} is not null, coalesce({title}, '') || ': ' || {name}, null)"


def mdy(start: int) -> str:
    # strict, and before Florida became a territory (1822) a date is a typo
    d = f"strptime({field(start, start + 7)}, '%m%d%Y')::DATE"
    return f"if({d} < date '1822-01-01', null, {d})"


ZIP = field(335, 344)
OFFICERS = ", ".join(officer(n) for n in range(1, 7))

SOURCES = (
    Source(
        name="fl_corporations",
        state="FL",
        kind="registry",
        files=(CORDATA,),
        # An FEI counts as the EIN only when one document alone carries it: the
        # field holds placeholders (999999999, 123456789) and numbers shared by
        # unrelated companies, such as 542129332 on 459 medical practices, and
        # an EIN merges every record that has it (notes of spec 10). The
        # fields are cut before the window, so it never holds the whole line.
        select=f"""
            with cut as (
                select {field(1, 12)} as registry_id,
                       regexp_replace(coalesce({field(481, 494)}, ''), '[^0-9]', '',
                                      'g') as fei,
                       {field(13, 204)} as name,
                       {field(221, 262)} as address, upper({field(305, 332)}) as city,
                       {field(333, 334)} as address_state,
                       if(regexp_matches({ZIP}, '^[0-9]{{5}}'), left({ZIP}, 5), null)
                           as zip5,
                       'physical' as address_kind, {field(206, 220)} as entity_type,
                       {field(205, 205)} as status,
                       {mdy(496)} as status_date,
                       {field(205, 205)} = 'A' as active,
                       {mdy(473)} as formed_date,
                       null::VARCHAR as naics,
                       nullif(list_filter([{OFFICERS}],
                                          o -> o is not null), []) as officers,
                       {field(347, 472)} as fl_mailing_address,
                       {field(545, 586)} as fl_registered_agent_name,
                       {field(504, 505)} as fl_state_country,
                       {field(495, 495)} as fl_more_than_six_officers,
                       -- suite, unit or floor
                       {field(263, 304)} as fl_address_line_2
                from cordata
            )
            select 'FL' as state, registry_id,
                   -- one digit nine times, or 123456789, is a placeholder
                   if(length(fei) = 9 and replace(fei, left(fei, 1), '') != ''
                      and fei != '123456789'
                      and count(*) over (partition by fei) = 1, fei, null) as ein,
                   name, norm_name(name) as norm_name,
                   * exclude (registry_id, fei, name)
            from cut""",
        min_rows=9_090_000,
        # about two-thirds of the first run's matched share, 71.8% (spec 10 notes)
        min_match_share=0.48,
        dropped=(0, 0),
        sentinel=("444750", date(1974, 1, 24)),
        download=download,
        read=read,
    ),
)
