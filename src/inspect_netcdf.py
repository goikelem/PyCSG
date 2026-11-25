"""Inspect CMIP NetCDF metadata before scenario generation."""
from pathlib import Path
import argparse, json
import pandas as pd
import xarray as xr


def inspect_file(path):
    ds=xr.open_dataset(path,decode_times=True)
    try:
        def coord_info(names):
            for n in names:
                if n in ds.coords:return {"name":n,"dims":list(ds[n].dims),"shape":list(ds[n].shape)}
            return None
        variables=[]
        for name,da in ds.data_vars.items():
            variables.append({"name":name,"dims":list(da.dims),"shape":list(da.shape),
                              "units":da.attrs.get("units"),"standard_name":da.attrs.get("standard_name"),
                              "long_name":da.attrs.get("long_name"),"cell_methods":da.attrs.get("cell_methods")})
        time_name=next((n for n in ("time","valid_time","T") if n in ds.coords),None)
        time_range=None
        if time_name and ds.sizes.get(time_name,0):
            t=ds[time_name].values
            time_range=[str(t[0]),str(t[-1])]
        return {"file":str(path),"dimensions":dict(ds.sizes),"latitude":coord_info(["lat","latitude","nav_lat"]),
                "longitude":coord_info(["lon","longitude","nav_lon"]),"time_range":time_range,
                "calendar":(ds[time_name].encoding.get("calendar",ds[time_name].attrs.get("calendar")) if time_name else None),
                "source_id":ds.attrs.get("source_id"),"institution_id":ds.attrs.get("institution_id"),
                "experiment_id":ds.attrs.get("experiment_id"),"variant_label":ds.attrs.get("variant_label"),
                "grid_label":ds.attrs.get("grid_label"),"variables":variables}
    finally:ds.close()


def main():
    p=argparse.ArgumentParser(description="Inspect model NetCDF metadata")
    p.add_argument("path",nargs="?",default="data/models",help="NetCDF file or directory")
    p.add_argument("--output",default="output/netcdf_inventory",help="Output filename stem")
    a=p.parse_args(); target=Path(a.path)
    files=[target] if target.is_file() else sorted(target.rglob("*.nc"))
    records=[]
    for f in files:
        try:records.append(inspect_file(f))
        except Exception as e:records.append({"file":str(f),"error":str(e)})
    stem=Path(a.output);stem.parent.mkdir(parents=True,exist_ok=True)
    (stem.with_suffix(".json")).write_text(json.dumps(records,indent=2))
    flat=[]
    for r in records:
        if "error" in r:flat.append({"file":r["file"],"error":r["error"]});continue
        flat.append({k:r.get(k) for k in ["file","source_id","institution_id","experiment_id","variant_label","grid_label","time_range","calendar","dimensions"]} |
                    {"variables":"; ".join(f"{v['name']}[{','.join(v['dims'])}] {v.get('units')}" for v in r["variables"])})
    pd.DataFrame(flat).to_csv(stem.with_suffix(".csv"),index=False)
    print(f"Inspected {len(records)} NetCDF files. Reports: {stem.with_suffix('.csv')} and {stem.with_suffix('.json')}")

if __name__=="__main__":main()
