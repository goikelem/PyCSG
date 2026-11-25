"""Discover CMIP6 NetCDF files on disk and select models / SSP scenarios.

Expected directory layout (default root ``~/DATA/cmip6/data``)::

    <root>/<resolution>/<experiment>/<model>_<var>_lat2to16_lon32to49_<YYYYMMDD>_<YYYYMMDD>.nc

* ``resolution``: ``daily`` or ``monthly``
* ``experiment``: ``historical``, ``ssp1_2_6``, ``ssp2_4_5``, ``ssp3_7_0``,
  ``ssp4_6_0``, ``ssp5_8_5``
* one file per model *and* variable (``tasmax``, ``tasmin``, ``pr``, ...). A file
  name without a recognised variable token (``<model>_lat..._lon...nc``) is treated
  as a combined multi-variable file for that model.

This module deliberately has no xarray dependency, so catalogues can be listed,
filtered and dry-run on any machine.
"""
from __future__ import annotations
import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROOT = "~/DATA/cmip6/data"
RESOLUTIONS = ("daily", "monthly")
REQUIRED_VARS = ("tasmax", "tasmin", "pr")
KNOWN_VARS = {"huss", "pr", "psl", "sfcwind", "tas", "tasmax", "tasmin",
              "rsds", "rlds", "hurs", "hus", "clt", "uas", "vas", "evspsbl"}

_FILE_RE = re.compile(
    r"^(?P<stem>.+)_lat(?P<lat0>-?\d+)to(?P<lat1>-?\d+)_lon(?P<lon0>-?\d+)to(?P<lon1>-?\d+)"
    r"_(?P<start>\d{8})_(?P<end>\d{8})\.nc$", re.IGNORECASE)
_SSP_RE = re.compile(r"^ssp[_\-. ]?(\d)[_\-. ]?(\d)[_\-. ]?(\d)$", re.IGNORECASE)


class CatalogError(Exception):
    """Requested data is not available in the catalogue."""


def normalize_experiment(name: str) -> str:
    """'ssp2_4_5', 'SSP2-4.5', 'ssp245', '245' -> 'ssp245'; 'historical' unchanged."""
    s = str(name).strip().lower()
    if s in ("historical", "hist"):
        return "historical"
    if re.fullmatch(r"\d{3}", s):
        s = "ssp" + s
    m = _SSP_RE.match(s)
    if m:
        return "ssp" + "".join(m.groups())
    raise ValueError(f"Unrecognised scenario {name!r}; use e.g. ssp126, ssp2_4_5, SSP5-8.5")


def normalize_model(name: str) -> str:
    """Case/punctuation-insensitive model key: 'EC-Earth3-Veg' -> 'ec_earth3_veg'."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def parse_filename(filename: str):
    """Return (model, variable|None, start 'YYYYMMDD', end 'YYYYMMDD') or None."""
    m = _FILE_RE.match(os.path.basename(filename))
    if not m:
        return None
    stem = m["stem"]
    model, var = stem, None
    if "_" in stem:
        head, tail = stem.rsplit("_", 1)
        if tail.lower() in KNOWN_VARS:
            model, var = head, tail.lower()
    return normalize_model(model), var, m["start"], m["end"]


@dataclass(frozen=True)
class DataFile:
    path: Path
    start: str
    end: str


@dataclass
class Selection:
    """Files needed for one (model, scenario) run at one time resolution."""
    model: str
    scenario: str
    resolution: str
    historical: list
    future: list
    hist_range: tuple
    future_range: tuple


@dataclass
class Catalog:
    root: Path
    # files[resolution][model][experiment][variable or None] -> DataFile
    files: dict = field(default_factory=dict)

    # ---- discovery -------------------------------------------------------
    @classmethod
    def scan(cls, root: str | os.PathLike = DEFAULT_ROOT) -> "Catalog":
        root_p = Path(os.path.expandvars(os.path.expanduser(str(root)))).resolve()
        if not root_p.is_dir():
            raise CatalogError(f"CMIP6 data directory not found: {root_p}")
        cat = cls(root=root_p)
        for res in RESOLUTIONS:
            rdir = root_p / res
            if not rdir.is_dir():
                continue
            for edir in sorted(p for p in rdir.iterdir() if p.is_dir()):
                try:
                    exp = normalize_experiment(edir.name)
                except ValueError:
                    continue  # unrelated sub-directory
                for f in sorted(edir.glob("*.nc")):
                    parsed = parse_filename(f.name)
                    if parsed is None:
                        continue
                    model, var, start, end = parsed
                    (cat.files.setdefault(res, {}).setdefault(model, {})
                        .setdefault(exp, {}))[var] = DataFile(f, start, end)
        if not cat.files:
            raise CatalogError(f"No CMIP6 NetCDF files found under {root_p}/{{daily,monthly}}/<experiment>/")
        return cat

    # ---- queries ---------------------------------------------------------
    def resolutions(self):
        return [r for r in RESOLUTIONS if r in self.files]

    def models(self, resolution: str | None = None):
        res = [resolution] if resolution and resolution != "auto" else self.resolutions()
        return sorted({m for r in res for m in self.files.get(r, {})})

    def scenarios(self, resolution: str | None = None):
        res = [resolution] if resolution and resolution != "auto" else self.resolutions()
        exps = {e for r in res for m in self.files.get(r, {}).values() for e in m}
        return sorted(e for e in exps if e != "historical")

    def _vars_ok(self, res, model, exp, required):
        entry = self.files.get(res, {}).get(model, {}).get(exp, {})
        if None in entry and not all(v in entry for v in required):
            return [entry[None]]                      # combined multi-variable file
        if all(v in entry for v in required):
            return [entry[v] for v in required]
        return None

    def missing_reason(self, res, model, exp, required):
        entry = self.files.get(res, {}).get(model, {}).get(exp)
        if entry is None:
            return f"no {res}/{exp} files for {model}"
        miss = [v for v in required if v not in entry]
        return f"{res}/{exp}: missing variable file(s) {miss}" if miss else "ok"

    def select(self, model, scenario, resolution="auto", required=REQUIRED_VARS) -> Selection:
        """Resolve the historical + scenario files for one model.

        ``resolution='auto'`` prefers daily and falls back to monthly. Historical and
        future files always come from the same resolution (needed for a consistent
        change factor).
        """
        model, scenario = normalize_model(model), normalize_experiment(scenario)
        order = list(RESOLUTIONS) if resolution == "auto" else [resolution]
        reasons = []
        for res in order:
            h = self._vars_ok(res, model, "historical", required)
            f = self._vars_ok(res, model, scenario, required)
            if h and f:
                rng = lambda fl: (min(x.start for x in fl), max(x.end for x in fl))
                return Selection(model, scenario, res, [x.path for x in h], [x.path for x in f],
                                 rng(h), rng(f))
            reasons.append(self.missing_reason(res, model, "historical", required)
                           if not h else self.missing_reason(res, model, scenario, required))
        raise CatalogError("; ".join(reasons))

    # ---- selection helpers ----------------------------------------------
    def match_models(self, patterns, resolution="auto"):
        """Expand names / wildcards / 'all' into catalogue model keys.

        Returns (matched, unmatched_patterns). Matching is case- and punctuation-
        insensitive and supports shell wildcards (``ec_earth3*``). An exact name wins
        over a wildcard-style prefix, so ``canesm5`` does not also pick ``canesm5_canoe``
        unless written ``canesm5*``.
        """
        available = self.models(resolution)
        if not patterns or any(str(p).lower() == "all" for p in patterns):
            return available, []
        out, unmatched = [], []
        for p in patterns:
            if "*" in str(p) or "?" in str(p):
                key = re.sub(r"[^a-z0-9*?]+", "_", str(p).strip().lower())
                hits = [m for m in available if fnmatch.fnmatchcase(m, key)]
            else:
                key = normalize_model(p)
                hits = [key] if key in available else []
            if not hits:
                unmatched.append(p)
            out.extend(h for h in hits if h not in out)
        return out, unmatched

    def match_scenarios(self, requested, resolution="auto"):
        available = self.scenarios(resolution)
        if not requested or any(str(s).lower() == "all" for s in requested):
            return available, []
        out, unmatched = [], []
        for s in requested:
            try:
                n = normalize_experiment(s)
            except ValueError:
                unmatched.append(s); continue
            if n == "historical" or n not in available:
                unmatched.append(s)
            elif n not in out:
                out.append(n)
        return out, unmatched

    def summary_rows(self):
        """One row per (resolution, model) listing complete experiments."""
        rows = []
        for res in self.resolutions():
            for model in sorted(self.files[res]):
                exps = self.files[res][model]
                complete = [e for e in sorted(exps) if self._vars_ok(res, model, e, REQUIRED_VARS)]
                rows.append({"resolution": res, "model": model,
                             "variables": ",".join(sorted({v or "combined" for e in exps.values() for v in e})),
                             "complete_experiments": ",".join(complete),
                             "incomplete_experiments": ",".join(sorted(set(exps) - set(complete)))})
        return rows


def read_names_file(path) -> list:
    """Read model names from a text file (one per line; '#' comments).

    Lines may be plain model names *or* CMIP6 file names such as
    ``access_cm2_tas_lat2to16_lon32to49_19800101_20141231.nc`` (the model is parsed
    out of the name; duplicates collapse), so the file lists you already keep can be
    passed straight through.
    """
    names = []
    for line in Path(path).expanduser().read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parsed = parse_filename(line)
        name = parsed[0] if parsed else normalize_model(line)
        if name not in names:
            names.append(name)
    return names
