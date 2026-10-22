import logging
import os
import shutil
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)


def extract(zip_path: Path, suffix: str = ".csv", into: Path | None = None) -> Path:
    """Write the zip's single <suffix> member into a folder, unless it is newer.

    The folder defaults to the zip's own. A member may never replace the zip
    it comes from: SAM.gov's inner zip has the outer zip's name.
    """
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(suffix)]
        if len(names) != 1:
            kind = suffix.lstrip(".").upper()
            raise ValueError(f"{zip_path}: expected exactly one {kind}, found {names}")
        folder = (into or zip_path.parent).resolve()
        dest = folder / names[0]
        if dest.resolve().parent != folder:
            raise ValueError(f"{zip_path}: member {names[0]} leaves {folder}")
        if dest.resolve() == zip_path.resolve():
            raise ValueError(f"{zip_path}: its member {names[0]} would replace it")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_mtime > zip_path.stat().st_mtime:
            return dest
        part = dest.with_name(dest.name + ".part")
        try:
            with z.open(names[0]) as src, part.open("wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            os.replace(part, dest)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
    log.info("extracted %s", dest.name)
    return dest
