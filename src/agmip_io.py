"""Read and write the classic 12-column AgMIP daily weather format."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

COLUMNS = ["date_code", "year", "month", "day", "srad", "tmax", "tmin", "rain", "wind", "dewp", "vprs", "rhum"]

@dataclass
class AgMIPStation:
    code: str
    lat: float
    lon: float
    elev: float
    tav: float
    amp: float
    refht: float
    wndht: float

@dataclass
class AgMIPFile:
    station: AgMIPStation
    data: pd.DataFrame
    original_header: str = ""


def read_agmip(path: str | Path) -> AgMIPFile:
    path = Path(path)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 6:
        raise ValueError(f"{path} is too short to be an AgMIP weather file")
    header = lines[0].replace("*WEATHER DATA :", "", 1).strip()
    station_line = next((x for x in lines if x.strip().startswith("@ INSI")), None)
    if station_line is None:
        raise ValueError("Could not find @ INSI station metadata header")
    idx = lines.index(station_line)
    vals = lines[idx + 1].split()
    if len(vals) < 8:
        raise ValueError("Station metadata must contain INSI LAT LONG ELEV TAV AMP REFHT WNDHT")
    station = AgMIPStation(vals[0], *map(float, vals[1:8]))
    date_idx = next((i for i, x in enumerate(lines) if x.strip().startswith("@DATE")), None)
    if date_idx is None:
        raise ValueError("Could not find @DATE header")
    rows=[]
    for line in lines[date_idx+1:]:
        p=line.split()
        if len(p) < 8: continue
        try:
            row=[float(x) for x in p[:12]]
            row += [-99.0] * (12-len(row))
            rows.append(row)
        except ValueError: continue
    if not rows: raise ValueError("No daily data rows found")
    df=pd.DataFrame(rows, columns=COLUMNS)
    for c in ["date_code","year","month","day"]: df[c]=df[c].astype(int)
    if not df.month.between(1,12).all() or not df.day.between(1,31).all():
        raise ValueError("Invalid month/day values in AgMIP data")
    return AgMIPFile(station, df, header)


def _station_climatology(df):
    tx=df.tmax.to_numpy(dtype=float); tn=df.tmin.to_numpy(dtype=float)
    tx=np.where(tx < -70, np.nan, tx); tn=np.where(tn < -70, np.nan, tn)
    tave=float(np.nanmean(np.r_[tx,tn]))
    clean=df[["month","tmax","tmin"]].copy()
    clean.loc[clean.tmax < -70,"tmax"]=np.nan
    clean.loc[clean.tmin < -70,"tmin"]=np.nan
    monthly=clean.groupby("month")[["tmax","tmin"]].mean().mean(axis=1).reindex(range(1,13))
    tamp=float((monthly.max()-monthly.min())/2)
    return tave,tamp


def write_agmip(path: str | Path, station: AgMIPStation, df: pd.DataFrame, header: str, full: bool = True):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    out=df.copy()
    required=set(COLUMNS)
    missing=required-set(out.columns)
    if missing: raise ValueError(f"Missing AgMIP columns: {sorted(missing)}")
    tave,tamp=_station_climatology(out)
    with path.open("w",encoding="ascii",errors="replace",newline="\n") as f:
        f.write(f"*WEATHER DATA : {header}\n\n")
        f.write(f"{'@ INSI      LAT     LONG  ELEV   TAV   AMP REFHT WNDHT':>54}\n")
        f.write(f"{station.code:>6s}{station.lat:9.3f}{station.lon:9.3f}{station.elev:6.0f}{tave:6.1f}{tamp:6.1f}{station.refht:6.1f}{station.wndht:6.1f}\n")
        columns = ("@DATE    YYYY  MM  DD  SRAD  TMAX  TMIN  RAIN  WIND  DEWP  VPRS  RHUM\n"
                   if full else "@DATE    YYYY  MM  DD  SRAD  TMAX  TMIN  RAIN\n")
        f.write(columns)
        for r in out.itertuples(index=False):
            vals=[r.srad,r.tmax,r.tmin,r.rain,r.wind,r.dewp,r.vprs,r.rhum]
            if not full: vals=vals[:4]
            f.write(f"{int(r.date_code):7d}{int(r.year):6d}{int(r.month):4d}{int(r.day):4d}" +
                    "".join(f"{float(v):6.0f}" if i==7 else f"{float(v):6.1f}" for i,v in enumerate(vals))+"\n")
