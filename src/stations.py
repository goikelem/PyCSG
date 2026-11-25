"""Choose AgMIP station baseline files from the input directory."""
from __future__ import annotations
import fnmatch
from pathlib import Path

EXTS = (".agmip",)

def _stem(name: str) -> str:
    n = Path(str(name).strip()).name
    return n[:-6] if n.lower().endswith(EXTS) else n

def list_stations(input_dir) -> list:
    """All *.AgMIP baseline files in the input directory, sorted by name."""
    return sorted(p for p in Path(input_dir).glob("*") if p.is_file() and p.suffix.lower() == ".agmip")

def match_stations(input_dir, patterns):
    """Resolve names to files. Returns (paths, unmatched_patterns).

    A pattern matches a file when, case-insensitively, it equals the file name
    (``ETHA0QXX`` / ``ETHA0QXX.AgMIP``), equals its 4-letter station code (``ETHA``),
    or is a wildcard matching the file name (``ET?A*``, ``ETH*``). ``all`` selects every file.
    """
    files = list_stations(input_dir)
    if any(str(p).lower() == "all" for p in patterns):
        return files, []
    out, unmatched = [], []
    for pat in patterns:
        key = _stem(pat).upper()
        if any(c in key for c in "*?["):
            hits = [f for f in files if fnmatch.fnmatchcase(_stem(f.name).upper(), key)]
        else:
            hits = [f for f in files if _stem(f.name).upper() == key] or \
                   [f for f in files if _stem(f.name).upper()[:4] == key]
        if not hits: unmatched.append(pat)
        out.extend(h for h in hits if h not in out)
    return out, unmatched

def read_station_names(path) -> list:
    names = []
    for line in Path(path).expanduser().read_text().splitlines():
        for tok in line.split("#", 1)[0].replace(",", " ").split():
            if tok not in names: names.append(tok)
    return names
