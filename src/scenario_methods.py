"""AgMIP delta and mean/variability scenario adjustments."""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.stats import gamma


MISSING_THRESHOLD=-90.0  # AgMIP missing value is -99; real values are never this low


def _valid(x):
    """Boolean mask of finite, non-missing (-99) values."""
    x=np.asarray(x,dtype=float)
    return np.isfinite(x)&(x>MISSING_THRESHOLD)


def _check_factors(factors, need_std=False):
    """Fail early if a monthly factor is not 12 finite numbers."""
    for v,keys in (("tasmax",("mean_change",)+(("std_ratio",) if need_std else ())),
                   ("tasmin",("mean_change",)+(("std_ratio",) if need_std else ())),
                   ("pr",("mean_ratio",))):
        for k in keys:
            a=np.asarray(factors[v][k],dtype=float)
            if a.shape!=(12,) or not np.isfinite(a).all():
                raise ValueError(f"Change factor {v}.{k} must be 12 finite monthly values "
                                 f"(model data may not cover every month of the period): {a}")


def _safe_ratio(a,b,default=1.0,lower=None,upper=None):
    out=np.divide(a,b,out=np.full_like(np.asarray(a,dtype=float),default),where=np.isfinite(b)&(np.asarray(b)!=0))
    out=np.where(np.isfinite(out),out,default)
    if lower is not None:out=np.maximum(out,lower)
    if upper is not None:out=np.minimum(out,upper)
    return out

def calculate_change_factors(hist, future, wet_threshold=1.0):
    """Calculate 12 monthly factors from historical and future model series."""
    factors={}
    for v in ("tasmax","tasmin","pr"):
        h=hist[v]; f=future[v]
        hs=h["stats"]; fs=f["stats"]
        hm, fm=hs["mean"],fs["mean"]
        if v in ("tasmax","tasmin"):
            hstd, fstd=hs["std"],fs["std"]
            std_ratio=_safe_ratio(fstd,hstd,default=1.0,lower=0.0,upper=5.0)
            factors[v]={"mean_change":fm-hm,"std_ratio":std_ratio}
        else:
            ratio=_safe_ratio(fm,hm,default=1.0,lower=0.0,upper=3.0)
            wet_ratio=None; future_wet=None
            if hs["wet_frequency"] is not None and fs["wet_frequency"] is not None:
                hw=hs["wet_frequency"]; fw=fs["wet_frequency"]
                wet_ratio=_safe_ratio(fw,hw,default=1.0,lower=0.25,upper=10.0)
                future_wet=fw
            factors[v]={"mean_ratio":ratio,"wet_ratio":wet_ratio,"future_wet":future_wet,
                        "future_monthly_mean":fm}
    factors["daily_model_data"]=bool(all(bool(hist[v]["stats"].get("daily")) and bool(future[v]["stats"].get("daily"))
                                         for v in ("tasmax","tasmin","pr")))
    return factors

def _month_groups(df):
    return {m:np.flatnonzero(df.month.to_numpy()==m) for m in range(1,13)}

def _enforce_tmax_gt_tmin(out):
    """Legacy safeguard: Tmax must exceed Tmin (violations are set to mid-point +/- 0.1 C)."""
    tx=out["tmax"].to_numpy(float); tn=out["tmin"].to_numpy(float)
    bad=_valid(tx)&_valid(tn)&(tx<=tn)
    if bad.any():
        mid=(tx[bad]+tn[bad])/2
        tx=tx.copy(); tn=tn.copy()
        tx[bad]=mid+0.1; tn[bad]=mid-0.1
        out["tmax"]=tx; out["tmin"]=tn

def apply_delta(base, factors):
    """Original AgMIP simple-delta logic: monthly additive T and multiplicative P.

    Missing values (-99) in the baseline are left untouched.
    """
    _check_factors(factors)
    out=base.copy().reset_index(drop=True)
    mi=out["month"].to_numpy(int)-1
    tx=out["tmax"].to_numpy(float); tn=out["tmin"].to_numpy(float); r=out["rain"].to_numpy(float)
    out["tmax"]=np.where(_valid(tx),tx+np.asarray(factors["tasmax"]["mean_change"],float)[mi],tx)
    out["tmin"]=np.where(_valid(tn),tn+np.asarray(factors["tasmin"]["mean_change"],float)[mi],tn)
    ratio=np.asarray(factors["pr"]["mean_ratio"],float)[mi]
    out["rain"]=np.where(_valid(r),np.minimum(np.maximum(r,0)*ratio,999.9),r)
    _enforce_tmax_gt_tmin(out)
    return out

def _fit_gamma(values):
    x=np.asarray(values,dtype=float); x=x[np.isfinite(x)&(x>0)]
    if len(x)<=31:return None
    try:
        shape,loc,scale=gamma.fit(x,floc=0)
        if not np.isfinite(shape) or not np.isfinite(scale) or shape<=0 or scale<=0:return None
        return float(shape),float(scale)
    except Exception:return None

def _temperature_stretch(values, target_mean, std_ratio):
    x=np.asarray(values,dtype=float); mu=np.nanmean(x)
    sd=np.nanstd(x,ddof=1) if np.isfinite(x).sum()>1 else np.nan
    target_sd=sd*float(std_ratio)
    if not np.isfinite(sd) or sd<1e-10:return x+(target_mean-mu)
    return (x-mu)*(target_sd/sd)+target_mean

def _adjust_precip_month(rain, srad, mean_ratio, wet_ratio, wet_threshold=1.0, gamma_factor=1.0):
    """M&V wet-day selection plus gamma quantile stretch and mean constraint.

    Mirrors the source R workflow: target wet-day count is changed first (drying
    lowest-rain days or activating cloudiest/dimmest days), then wet-day gamma
    distribution is stretched and monthly mean is restored.
    """
    p=np.maximum(np.asarray(rain,dtype=float),0).copy()
    rad=np.asarray(srad,dtype=float).copy()
    n=len(p); base_mean=float(np.nanmean(p)) if n else 0.0
    target_mean=max(0.001,base_mean*float(mean_ratio))
    wet=np.flatnonzero(p>0)
    target_n=int(np.floor(len(wet)*float(wet_ratio)+0.5))
    # The R implementation enforces at least one rainy day in each month.
    target_n=max(1,min(n,target_n))
    if len(wet)==0:
        # Activate the cloudiest (lowest-radiation) day, as in the source R code.
        chosen=int(np.nanargmin(np.nan_to_num(rad,nan=np.inf))) if np.isfinite(rad).any() else 0
        p[chosen]=0.3
        rad[chosen]*=0.9
        current=float(np.nanmean(p))
        if current>0:p*=target_mean/current
        return np.minimum(p,999.0),rad
    if target_n<len(wet):
        # Remove lowest rainfall totals first; randomize ties reproducibly.
        order=wet[np.argsort(p[wet],kind="stable")]
        p[order[:len(wet)-target_n]]=0.0
        rad[order[:len(wet)-target_n]]*=1.1
    elif target_n>len(wet):
        dry=np.flatnonzero(p<=0)
        # Cloudiest days approximated by lowest solar radiation, as in R source.
        candidates=dry[np.argsort(np.nan_to_num(rad[dry],nan=np.inf),kind="stable")]
        add=candidates[:target_n-len(wet)]
        p[add]=0.3; rad[add]*=0.9
    wet_now=np.flatnonzero(p>0)
    base_gamma=_fit_gamma(rain[np.asarray(rain)>0])
    if base_gamma is not None and len(wet_now)>0:
        shape,scale=base_gamma
        target_shape=max(0.05,shape*float(gamma_factor))
        target_scale=target_mean*n/(len(wet_now)*target_shape)
        vals=p[wet_now]
        ranks=pd.Series(vals).rank(method="average",pct=True).to_numpy()
        stretched=gamma.ppf(np.clip(ranks,1e-5,1-1e-5),a=target_shape,scale=target_scale)
        p[wet_now]=np.maximum(stretched,0.1)
    # The source algorithm rescales the complete monthly vector to the imposed mean.
    current=float(np.nanmean(p))
    if current>0:p*=target_mean/current
    return np.minimum(p,999.0),rad

def apply_mandv(base, factors, wet_threshold=1.0, gamma_factor=1.0, seed=42):
    """Mean-and-variability method following AgMIP v2 parameter definitions.

    Temperature: impose monthly mean and standard-deviation factors. Tmin is
    first adjusted for the new Tmax while retaining baseline daily temperature
    range, then standardized to its target monthly mean and standard deviation.
    Precipitation: adjust wet-day count, gamma-distribution shape/scale and
    monthly mean. This is a deterministic Python implementation of the R
    stretched-distribution intent; random tie-breaking in the original is
    replaced with stable ordering, so `seed` is accepted for API compatibility
    but does not change the result. Missing values (-99) are left untouched
    and excluded from all monthly statistics.
    """
    _check_factors(factors,need_std=True)
    out=base.copy().reset_index(drop=True)
    tmax=out["tmax"].to_numpy(float).copy(); tmin=out["tmin"].to_numpy(float).copy()
    rain_o=out["rain"].to_numpy(float).copy(); srad_o=out["srad"].to_numpy(float).copy()
    month=out["month"].to_numpy(int)
    pr=factors["pr"]
    for m in range(1,13):
        ix=np.flatnonzero(month==m)
        if len(ix)==0:continue
        tx=tmax[ix]; tn=tmin[ix]
        vx=_valid(tx); vn=_valid(tn)
        tx_new=tx.copy(); tn_new=tn.copy()
        if vx.any():
            target_tx=float(np.mean(tx[vx])+factors["tasmax"]["mean_change"][m-1])
            tx_new[vx]=_temperature_stretch(tx[vx],target_tx,factors["tasmax"]["std_ratio"][m-1])
        if vn.any():
            # Preserve the observed daily diurnal range while moving Tmax.
            tn_int=tn.copy(); both=vx&vn
            tn_int[both]=tx_new[both]-(tx[both]-tn[both])
            target_tn=float(np.mean(tn[vn])+factors["tasmin"]["mean_change"][m-1])
            tn_new[vn]=_temperature_stretch(tn_int[vn],target_tn,factors["tasmin"]["std_ratio"][m-1])
        tmax[ix]=tx_new; tmin[ix]=tn_new
        rain=rain_o[ix]; srad=srad_o[ix]; vr=_valid(rain)
        if not vr.any():continue
        rad=np.where(_valid(srad),srad,np.nan)
        wetratio=pr["wet_ratio"][m-1] if pr.get("wet_ratio") is not None else 1.0
        pnew,rnew=_adjust_precip_month(rain[vr],rad[vr],pr["mean_ratio"][m-1],wetratio,
                                       wet_threshold,gamma_factor)
        rain_o[ix[vr]]=pnew
        srad_o[ix[vr]]=np.where(np.isnan(rnew),srad[vr],rnew)
    out["tmax"]=tmax; out["tmin"]=tmin; out["rain"]=rain_o; out["srad"]=srad_o
    _enforce_tmax_gt_tmin(out)
    return out
