"""Create farm-site baseline AgMIP series from a monthly NetCDF climatology.

NetCDF replacement for the WorldClim .mat inputs in agmip_farmclimate.R.
Expected grids: monthly tmean and precipitation, plus elevation, with lat/lon.
"""
from pathlib import Path
import numpy as np
import xarray as xr
try:
    from .agmip_io import read_agmip, AgMIPStation, write_agmip
    from .netcdf_io import nearest_cell
    from .simple2full import saturation_vapour_pressure_hpa, vapour_pressure_to_dewpoint_c
except ImportError:
    from agmip_io import read_agmip, AgMIPStation, write_agmip
    from netcdf_io import nearest_cell
    from simple2full import saturation_vapour_pressure_hpa, vapour_pressure_to_dewpoint_c


def _find_var(ds, configured, aliases):
    names={str(n).lower():n for n in ds.data_vars}
    for n in [configured]+aliases:
        if n and n.lower() in names:return ds[names[n.lower()]]
    raise KeyError(f"None of these variables found: {[configured]+aliases}; found {list(ds.data_vars)}")


def _monthly_vector(da, ds, lat, lon):
    point, alat, alon, idx = nearest_cell(da, ds, lat, lon)
    month_dim=next((d for d in point.dims if d.lower() in ("month","months")),None)
    if month_dim is None:
        # Accept a single remaining dimension of length 12 (e.g. a 12-step 'time' axis).
        twelve=[d for d in point.dims if point.sizes[d]==12]
        if len(twelve)!=1:
            raise ValueError(f"Monthly climatology variable {da.name} must have a month dimension")
    vals=np.asarray(point.values,dtype=float).reshape(-1)
    if len(vals)!=12:raise ValueError(f"Expected 12 monthly values in {da.name}, got {len(vals)}")
    return vals,alat,alon,idx


def generate_farm_sites(seed_agmip, climatology_netcdf, sites, output_dir,
                        short_region="FS", header="Farm site climate series",
                        variables=None, temperature_scale=1.0, precipitation_scale=1.0):
    """Generate one AgMIP file per (name, latitude, longitude) farm site.

    `sites` is a sequence of dictionaries: {name, lat, lon}. The NetCDF must
    contain monthly mean temperature, monthly precipitation, and elevation.
    """
    if len(sites)>99:raise ValueError("At most 99 sites are supported by this station naming convention")
    seed=read_agmip(seed_agmip)
    v=variables or {"tmean":"tmean","precip":"prec","elevation":"elevation"}
    ds=xr.open_dataset(climatology_netcdf,decode_times=True)
    try:
        tda=_find_var(ds,v.get("tmean"),["tmean","tas","temperature"])
        pda=_find_var(ds,v.get("precip"),["prec","precip","precipitation","pr"])
        ada=_find_var(ds,v.get("elevation"),["alt","elevation","orog"])
        seed_t,_,_,_=_monthly_vector(tda,ds,seed.station.lat,seed.station.lon)
        seed_p,_,_,_=_monthly_vector(pda,ds,seed.station.lat,seed.station.lon)
        output_dir=Path(output_dir); output_dir.mkdir(parents=True,exist_ok=True)
        outputs=[]
        for i,site in enumerate(sites,1):
            lat=float(site["lat"]);lon=float(site["lon"])
            t,alat,alon,_=_monthly_vector(tda,ds,lat,lon)
            p,_,_,_=_monthly_vector(pda,ds,lat,lon)
            elev,_,_,_=nearest_cell(ada,ds,lat,lon)
            elevation=float(np.asarray(elev.values).squeeze())
            tdelta=(t-seed_t)*temperature_scale
            # A ratio of two values in the same units is unit-invariant, so no
            # precipitation scaling is needed (precipitation_scale is accepted
            # for backward compatibility only).
            ratio=np.divide(p,seed_p,out=np.ones(12),where=np.isfinite(p)&np.isfinite(seed_p)&(seed_p>0))
            ratio=np.clip(np.nan_to_num(ratio,nan=1.0,posinf=1.0,neginf=1.0),0,3)
            if not np.isfinite(tdelta).all():
                raise ValueError(f"Site {site.get('name',i)} at ({lat}, {lon}) has missing monthly temperature in the climatology (ocean/no-data cell?)")
            out=seed.data.copy().reset_index(drop=True)
            mi=out["month"].to_numpy(int)-1
            tx=out["tmax"].to_numpy(float); tn=out["tmin"].to_numpy(float); r=out["rain"].to_numpy(float)
            out["tmax"]=np.where(tx>-90,tx+tdelta[mi],tx)
            out["tmin"]=np.where(tn>-90,tn+tdelta[mi],tn)
            out["rain"]=np.where(r>-90,np.minimum(np.maximum(r,0)*ratio[mi],999.9),r)
            rh=out.rhum.to_numpy(float)
            valid=np.isfinite(rh)&(rh>-90)&(out.tmax.to_numpy(float)>-90)
            out.loc[~valid,["dewp","vprs"]]=-99.0
            es=saturation_vapour_pressure_hpa(out.loc[valid,"tmax"].to_numpy())
            e=np.maximum(0.1,out.loc[valid,"rhum"].to_numpy(float)/100*es)
            out.loc[valid,"vprs"]=e;out.loc[valid,"dewp"]=vapour_pressure_to_dewpoint_c(e)
            site_code=f"{short_region[:2]}{i:02d}"
            station=AgMIPStation(site_code,lat,lon,elevation,seed.station.tav,seed.station.amp,-99.0,-99.0)
            fname=f"{site_code}_{Path(seed_agmip).stem}_farmclimate.AgMIP"
            write_agmip(output_dir/fname,station,out,
                        f"{header}; {site.get('name',site_code)}; cast from seed {Path(seed_agmip).name} using NetCDF monthly climatology")
            outputs.append(output_dir/fname)
        return outputs
    finally:
        ds.close()
