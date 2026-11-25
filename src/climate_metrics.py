"""Python implementation of AgMIP acr_agmip2metrics.R."""
from __future__ import annotations
import numpy as np
import pandas as pd
try:
    from .agmip_io import read_agmip
except ImportError:
    from agmip_io import read_agmip

SUPPORTED={"mean","count","exceedance","max","min","std","meanconsecutivedays","maxconsecutivedays"}

def _streaks(mask):
    lengths=[]; run=0
    for v in mask:
        if v:run+=1
        elif run: lengths.append(run);run=0
    if run:lengths.append(run)
    return lengths

def calculate_metrics(agmip_file,jdstart,jdend,column,analysis_type,reference=np.nan,special_operator=1):
    """Return year/value table for each planting year in the source record.

    `column` follows R's 1-based AgMIP column numbering (1=DATE,...,13=Tave).
    Day-of-year periods wrap across year-end when jdstart > jdend.
    """
    if analysis_type not in SUPPORTED:raise ValueError(f"analysis_type must be one of {sorted(SUPPORTED)}")
    af=read_agmip(agmip_file); df=af.data.copy()
    if column==13: values=(df.tmax.where(df.tmax>-90)+df.tmin.where(df.tmin>-90))/2
    elif 1<=column<=12: values=df.iloc[:,column-1].astype(float)
    else:raise ValueError("column must be 1..12 or 13 for Tave")
    if analysis_type in ("count","exceedance","meanconsecutivedays","maxconsecutivedays") and not np.isfinite(reference):
        raise ValueError(f"analysis_type '{analysis_type}' requires a finite reference value")
    # AgMIP missing values (-99) must not enter any statistic.
    values=values.where(values>-90)
    period_len=jdend-jdstart+1
    if period_len<1:period_len+=365
    years=sorted(df.year.unique())
    out=[]
    for year in years:
        start_idx=np.flatnonzero((df.year.to_numpy()==year)&((df.date_code.to_numpy()%1000)==jdstart))
        if not len(start_idx):out.append((year,np.nan));continue
        i=int(start_idx[0]); vals=values.iloc[i:i+period_len].to_numpy(dtype=float)
        if len(vals)<period_len:out.append((year,np.nan));continue
        vals=vals[np.isfinite(vals)]
        if not len(vals):out.append((year,np.nan));continue
        if analysis_type=="mean": result=float(np.mean(vals))
        elif analysis_type=="max": result=float(np.max(vals))
        elif analysis_type=="min": result=float(np.min(vals))
        elif analysis_type=="std": result=float(np.std(vals,ddof=1)) if len(vals)>1 else np.nan
        elif analysis_type=="count": result=float(np.sum(vals<reference if special_operator==-1 else vals>reference))
        elif analysis_type=="exceedance":
            d=vals-reference; d=np.minimum(d,0) if special_operator==-1 else np.maximum(d,0); result=float(np.sum(d))
        else:
            mask=(vals<reference) if special_operator==-1 else (vals>reference)
            runs=_streaks(mask)
            result=float(np.mean(runs)) if analysis_type=="meanconsecutivedays" and runs else (float(max(runs)) if runs else 0.0)
        out.append((year,result))
    return pd.DataFrame(out,columns=["year","value"])
