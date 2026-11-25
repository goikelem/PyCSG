"""CMIP NetCDF access, coordinate normalization and station extraction."""
from __future__ import annotations
from pathlib import Path
import logging
import numpy as np
import pandas as pd
import xarray as xr

LOG=logging.getLogger(__name__)
ALIASES={
 "tasmax":["tasmax","tmax","tasmaxAdjust","TMAX"],
 "tasmin":["tasmin","tmin","TMIN"],
 "pr":["pr","precip","precipitation","precipitation_flux","RAIN"],
 "srad":["rsds","srad","solar","SRAD"],
}
COORD_ALIASES={"lat":["lat","latitude","nav_lat"],"lon":["lon","longitude","nav_lon"],"time":["time","valid_time","T"]}

def _first_match(names, aliases):
    lookup={str(n).lower():n for n in names}
    for a in aliases:
        if a.lower() in lookup:return lookup[a.lower()]
    return None

def _resolve_paths(model_cfg, experiment, model_dir):
    # Preferred layout: experiments: {historical: [...], ssp245: [...]}.
    expmap=model_cfg.get("experiments",{})
    spec=expmap.get(experiment)
    if spec is None: spec=model_cfg.get("file")
    if spec is None: raise FileNotFoundError(f"No file or experiments.{experiment} configured")
    if isinstance(spec,str): specs=[spec]
    else: specs=list(spec)
    paths=[(Path(model_dir)/p).resolve() for p in specs]
    missing=[str(p) for p in paths if not p.exists()]
    if missing: raise FileNotFoundError("Missing NetCDF input(s): "+", ".join(missing))
    return paths

def _merge_variable_files(opened, paths):
    """Merge per-variable files. Grids/time axes must agree (no silent outer join)."""
    try: return xr.merge(opened,compat="override",join="exact",combine_attrs="drop_conflicts")
    except ValueError:
        # Some models stamp variables at different times of day: align on the calendar day.
        try:
            day=[d.assign_coords(time=d["time"].dt.floor("D")) if "time" in d.coords else d for d in opened]
            return xr.merge(day,compat="override",join="exact",combine_attrs="drop_conflicts")
        except Exception as e:
            raise ValueError("Per-variable files have different grids or time axes and cannot be combined: "
                             +", ".join(Path(p).name for p in paths)+f" ({e})")

def open_model_dataset(model_cfg, experiment, model_dir):
    paths=_resolve_paths(model_cfg,experiment,model_dir)
    opened=[]
    for p in paths:
        opened.append(xr.open_dataset(p,decode_times=True))
    if len(opened)==1: ds=opened[0]
    elif model_cfg.get("combine")=="by_variable":
        # CMIP6 layout: one file per variable on identical grid/time axes.
        try: ds=_merge_variable_files(opened,paths)
        except Exception:
            for d in opened:d.close()
            raise
    else:
        # Multiple files can represent variables or contiguous time chunks.
        try: ds=xr.combine_by_coords(opened,combine_attrs="drop_conflicts")
        except Exception:
            try: ds=xr.merge(opened,join="outer",compat="override")
            except Exception:
                for d in opened:d.close()
                raise
    # Some aggregated CMIP products retain experiment as an explicit dimension.
    for dim in list(ds.dims):
        if dim.lower() in ("experiment_id","experiment","scenario","scenario_id") and dim in ds.coords:
            labels=[str(x) for x in ds[dim].values]
            requested=str(experiment)
            aliases={"ssp126":["ssp126","SSP1-2.6"],"ssp245":["ssp245","SSP2-4.5"],
                     "ssp370":["ssp370","SSP3-7.0"],"ssp585":["ssp585","SSP5-8.5"]}
            options=aliases.get(requested,[requested])
            selected=next((x for x in labels if x.lower() in [v.lower() for v in options]),None)
            if selected is None: raise ValueError(f"Experiment {requested} not found on {dim}; available={labels}")
            ds=ds.sel({dim:selected})
    ren={}
    names=list(ds.coords)+list(ds.dims)
    for standard,aliases in COORD_ALIASES.items():
        found=_first_match(names,aliases)
        if found and found!=standard and standard not in ds.coords and standard not in ds.dims:
            # Rename coordinate and its dimension only for 1-D coordinates.
            if found in ds.coords and ds[found].ndim==1:
                olddim=ds[found].dims[0]
                if olddim!=standard and standard not in ds.dims: ren[olddim]=standard
                ren[found]=standard
            elif found in ds.coords:
                ren[found]=standard
    if ren: ds=ds.rename(ren)
    if "time" not in ds.coords and "time" not in ds.dims:
        raise ValueError(f"No recognizable time coordinate in {paths}")
    return ds

def _pick_var(ds, canonical, cfg):
    configured=cfg.get("variables",{}).get(canonical)
    names=list(ds.data_vars)
    var=_first_match(names,([configured] if configured else [])+ALIASES[canonical])
    if var is None:
        raise KeyError(f"Variable {canonical!r} not found. Available: {names}. Configure variables.{canonical}.")
    return ds[var]

def _standardize_units(da, canonical):
    units=str(da.attrs.get("units","" )).lower().replace(" ","")
    if canonical in ("tasmax","tasmin"):
        if units in ("k","kelvin","degreesk"): da=da-273.15
        elif units and units not in ("degc","degree_celsius","degrees_celsius","c","celsius","°c","degreec","degreesc","degree_c","degrees_c"):
            LOG.warning("Unrecognized %s units %s; values are left unchanged",canonical,units)
        da.attrs=dict(da.attrs); da.attrs["units"]="degC"
    elif canonical=="pr":
        if units in ("kgm-2s-1","kg/m2/s","kgm**-2s**-1","kgm^-2s^-1"):
            da=da*86400.0
        elif units in ("m/s","ms-1","ms^-1"): da=da*86400.0*1000.0
        elif units in ("mm/s",): da=da*86400.0
        elif units in ("m/day","md-1","mday-1"): da=da*1000.0
        # mm/day, mm/month and kg m-2 per timestep retain their original scale.
        da.attrs=dict(da.attrs); da.attrs["units"]="mm day-1 or source accumulation units"
    return da

def _check_inside_domain(latitude, longitude, lats, lons):
    """Refuse stations outside a regional (subset) grid instead of silently using an edge cell."""
    def spacing(v):
        d=np.abs(np.diff(np.sort(v[np.isfinite(v)])))
        return float(np.median(d)) if d.size else 0.0
    sl,so=spacing(lats),spacing(lons)
    lo,hi=np.nanmin(lats),np.nanmax(lats)
    if latitude<lo-sl or latitude>hi+sl:
        raise ValueError(f"Station latitude {latitude} is outside the model domain {lo:.2f} to {hi:.2f}")
    if float(np.nanmin(np.abs(((lons-longitude+180)%360)-180)))>so:
        raise ValueError(f"Station longitude {longitude} is outside the model domain "
                         f"{np.nanmin(lons):.2f} to {np.nanmax(lons):.2f}")

def nearest_cell(da, ds, latitude, longitude):
    latname="lat" if "lat" in ds.coords else _first_match(ds.coords,COORD_ALIASES["lat"])
    lonname="lon" if "lon" in ds.coords else _first_match(ds.coords,COORD_ALIASES["lon"])
    if latname is None or lonname is None: raise ValueError("NetCDF must include latitude and longitude coordinates")
    lat=ds[latname]; lon=ds[lonname]
    if lat.ndim==1 and lon.ndim==1:
        latdim=lat.dims[0]; londim=lon.dims[0]
        iy=int(np.nanargmin(np.abs(np.asarray(lat.values,dtype=float)-latitude)))
        lonvals=np.asarray(lon.values,dtype=float)
        # Compare longitudes circularly to support both [-180,180] and [0,360].
        delta=np.abs(((lonvals-longitude+180)%360)-180)
        ix=int(np.nanargmin(delta))
        _check_inside_domain(latitude,longitude,np.asarray(lat.values,dtype=float),lonvals)
        selected=da.isel({latdim:iy,londim:ix})
        return selected,float(lat.values[iy]),float(lon.values[ix]),{latdim:iy,londim:ix}
    if lat.ndim==2 and lon.ndim==2 and lat.dims==lon.dims:
        la=np.asarray(lat.values,dtype=float); lo=np.asarray(lon.values,dtype=float)
        dlat=la-latitude; dlon=((lo-longitude+180)%360)-180
        # Longitude distance is scaled by cosine(latitude) for nearest angular distance.
        dist=dlat*dlat+(dlon*np.cos(np.deg2rad(latitude)))**2
        iy,ix=np.unravel_index(np.nanargmin(dist),dist.shape)
        dims=lat.dims
        selected=da.isel({dims[0]:int(iy),dims[1]:int(ix)})
        return selected,float(la[iy,ix]),float(lo[iy,ix]),{dims[0]:int(iy),dims[1]:int(ix)}
    raise ValueError(f"Unsupported lat/lon coordinate shapes: {lat.shape}, {lon.shape}")

def extract_station_series(ds, canonical, cfg, latitude, longitude):
    da=_pick_var(ds,canonical,cfg)
    # Select scenario/ensemble dimensions only when explicitly requested; otherwise first member.
    for dim in list(da.dims):
        if dim in ("time",): continue
        if dim.lower() in ("member_id","realization","variant_label","ensemble","member"):
            wanted=cfg.get("member")
            if wanted is not None and dim in da.coords: da=da.sel({dim:wanted})
            else: da=da.isel({dim:0})
    # Select the grid cell first so unit conversion only touches one time series
    # instead of loading the whole (possibly global) daily field into memory.
    point,actual_lat,actual_lon,index=nearest_cell(da,ds,latitude,longitude)
    # If a time dimension remains, collapse accidental singleton extras.
    for d in list(point.dims):
        if d!="time": point=point.isel({d:0})
    point=_standardize_units(point,canonical).sortby("time")
    return point,actual_lat,actual_lon,index

def _period_bounds(start,end):
    """Whole-year periods are sliced by year so non-standard calendars work.

    String slices such as '2070-12-31' fail on 360_day calendars (no day 31).
    """
    s=pd.Timestamp(start); e=pd.Timestamp(end)
    if (s.month,s.day)==(1,1) and (e.month,e.day)==(12,31):
        return str(s.year),str(e.year)
    return str(start),str(end)

def slice_period(da,start,end):
    try: out=da.sel(time=slice(*_period_bounds(start,end)))
    except Exception as e: raise ValueError(f"Cannot select time period {start} to {end}: {e}")
    if out.sizes.get("time",0)==0: raise ValueError(f"No data in period {start} to {end}")
    return out

def _is_daily(da):
    t=np.asarray(da.time.values)
    if len(t)<2:return False
    try:
        gaps=[]
        for a,b in zip(t[:-1],t[1:]):
            diff=b-a
            gaps.append(diff.total_seconds()/86400 if hasattr(diff,"total_seconds") else float(diff/np.timedelta64(1,"D")))
        return bool(np.nanmedian(gaps)<=2.0)
    except Exception:return False

def monthly_statistics(da,start,end,wet_threshold=1.0):
    sub=slice_period(da,start,end)
    daily=_is_daily(sub)
    grouped=sub.groupby("time.month")
    mean=grouped.mean("time",skipna=True)
    std=grouped.std("time",skipna=True,ddof=1)
    result={"mean":mean,"std":std,"daily":daily}
    if daily:
        result["wet_frequency"]=(sub>wet_threshold).groupby("time.month").mean("time",skipna=True)
    else: result["wet_frequency"]=None
    return result

def as_12_months(da):
    if "month" not in da.dims: raise ValueError("Expected monthly grouped statistics")
    return np.asarray(da.reindex(month=np.arange(1,13)).values,dtype=float).reshape(12)
