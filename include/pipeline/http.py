import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# identity on both requests, so the GET's byte count matches Content-Length
HEADERS = {
    "Accept-Encoding": "identity",
    "User-Agent": "retiring-business-owners/0.1 (local data pipeline)",
}
TIMEOUT = (30, 300)  # connect, read


def download_if_changed(url: str, dest: Path) -> bool:
    """Download url to dest unless its ETag and Last-Modified match the sidecar.

    No retry loop: Airflow retries the task.
    """
    head = requests.head(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    head.raise_for_status()
    seen = {
        "etag": head.headers.get("ETag"),
        "last_modified": head.headers.get("Last-Modified"),
    }
    if not any(seen.values()):
        raise RuntimeError(f"{url}: HEAD returned neither ETag nor Last-Modified")
    meta = dest.with_name(dest.name + ".meta.json")
    if dest.exists() and meta.exists():
        stored = json.loads(meta.read_text())
        same = all(stored.get(k) == v for k, v in seen.items())
        # a raw file damaged on disk is downloaded again
        if same and dest.stat().st_size == stored["bytes"]:
            log.info("unchanged %s", dest.name)
            return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        # shortcut: no resume; the SBA server sends Accept-Ranges if a 450 MB
        # restart ever hurts
        with requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True) as r:
            r.raise_for_status()
            expected = int(r.headers.get("Content-Length") or 0)
            size = 0
            with part.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    size += len(chunk)
        if expected and size != expected:
            raise RuntimeError(f"{url}: got {size} bytes, Content-Length {expected}")
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise

    record = {"url": url, **seen, "bytes": size}
    record["downloaded_at"] = datetime.now(UTC).isoformat()
    meta_part = meta.with_name(meta.name + ".part")
    meta_part.write_text(json.dumps(record, indent=2))
    os.replace(meta_part, meta)
    log.info("downloaded %s %d", dest.name, size)
    return True
