"""Generate AgMIP scenarios from CMIP NetCDF files."""
from __future__ import annotations
import argparse, json, logging, os, re
from pathlib import Path
import numpy as np, pandas as pd, yaml
from agmip_io import read_agmip, write_agmip
from netcdf_io import open_model_dataset, extract_station_series, monthly_statistics, as_12_months
from scenario_methods import apply_delta, apply_mandv, calculate_change_factors
import cmip6_catalog as cc
import stations as stn

LOG=logging.getLogger("agmip")

def _period_for_experiment(model_cfg, scenario, periods, cfg):
    # CMIP6 historical and SSP data may be stored in separate files. If so, use
    # historical for the baseline and the requested SSP file for future period.
    hist_exp=model_cfg.get("historical_experiment","historical")
    future_exp=model_cfg.get("scenario_experiments",{}).get(scenario,scenario)
    return hist_exp,future_exp

def _extract_stats(model_cfg, exp, model_dir, cfg, station, start, end):
    ds=open_model_dataset(model_cfg,exp,model_dir)
    result={}
    try:
        actual=None
        for v in ("tasmax","tasmin","pr"):
            da,alat,alon,idx=extract_station_series(ds,v,cfg,station.lat,station.lon)
            stats=monthly_statistics(da,start,end,cfg.get("wet_day_threshold_mm",1.0))
            result[v]={"stats":{k:(as_12_months(val) if hasattr(val,"dims") and "month" in val.dims else val) for k,val in stats.items()}}
            actual=(alat,alon,idx)
        result["grid"]={"lat":actual[0],"lon":actual[1],"index":actual[2]}
        return result
    finally: ds.close()

def _calculate_factors(model_cfg, scenario, model_dir, cfg, station, base_period, future_period, hist_cache=None):
    hist_exp,future_exp=_period_for_experiment(model_cfg,scenario,[future_period],cfg)
    # Historical statistics do not depend on scenario or future period: compute once per model.
    key=(repr(sorted(model_cfg.get("experiments",{}).get(hist_exp,[model_cfg.get("file")]) or [], key=str)),hist_exp,base_period["start"],base_period["end"],station.lat,station.lon)
    if hist_cache is not None and key in hist_cache: h=hist_cache[key]
    else:
        h=_extract_stats(model_cfg,hist_exp,model_dir,cfg,station,base_period["start"],base_period["end"])
        if hist_cache is not None: hist_cache[key]=h
    f=_extract_stats(model_cfg,future_exp,model_dir,cfg,station,future_period["start"],future_period["end"])
    factors=calculate_change_factors(h,f,cfg.get("wet_day_threshold_mm",1.0))
    factors["grid"]=h["grid"]
    return factors

def _output_name(station_code, scenario, model_key, period_key, method):
    safe=re.sub(r"[^A-Za-z0-9]+","-",model_key).strip("-")
    return f"{station_code}_{scenario}_{safe}_{period_key}_{method}.AgMIP"


def _years_covered(req, rng):
    """req={'start','end'} ISO dates; rng=(YYYYMMDD,YYYYMMDD) from the file names."""
    return int(rng[0][:4])<=pd.Timestamp(req["start"]).year and int(rng[1][:4])>=pd.Timestamp(req["end"]).year

def _cmip6_runs(args, cfg, cat, report):
    """Expand --models/--scenarios/--models-file/--exclude-models/--resolution into runs."""
    res=args.resolution or cfg.get("cmip6",{}).get("resolution","auto")
    patterns=list(args.models or [])
    if args.models_file: patterns+=cc.read_names_file(args.models_file)
    models,unmatched=cat.match_models(patterns,res)
    for u in unmatched: report.append({"model":u,"status":"failed","error":f"No CMIP6 model matches '{u}' (see --list-catalog)"})
    if args.exclude_models:
        drop,_=cat.match_models(args.exclude_models,res); models=[m for m in models if m not in drop]
    requested=args.scenarios or cfg.get("cmip6",{}).get("default_scenarios") or ["all"]
    scenarios,bad=cat.match_scenarios(requested,res)
    for b in bad: report.append({"scenario":str(b),"status":"failed","error":f"Scenario '{b}' not available under {cat.root}"})
    runs=[]
    for m in models:
        for sc in scenarios:
            try: sel=cat.select(m,sc,res,tuple(cfg.get("cmip6",{}).get("required_variables",cc.REQUIRED_VARS)))
            except cc.CatalogError as e:
                report.append({"model":m,"scenario":sc,"status":"failed","error":f"Data not available: {e}"}); continue
            mc={"combine":"by_variable","historical_experiment":"historical","scenario_experiments":{sc:sc},
                "experiments":{"historical":[str(p) for p in sel.historical],sc:[str(p) for p in sel.future]}}
            runs.append({"model":m,"scenario":sc,"resolution":sel.resolution,"cfg":mc,"sel":sel})
    return runs

def _print_catalog(cat):
    print(f"CMIP6 root: {cat.root}")
    print(f"resolutions: {cat.resolutions()}   scenarios: {cat.scenarios()}")
    print(f"{'resolution':<9} {'model':<28} {'complete experiments':<48} incomplete")
    for r in cat.summary_rows():
        print(f"{r['resolution']:<9} {r['model']:<28} {r['complete_experiments']:<48} {r['incomplete_experiments']}")

def main():
    ap=argparse.ArgumentParser(description="AgMIP climate scenario generation from CMIP NetCDF")
    ap.add_argument("--config",default="config/config.yaml")
    ap.add_argument("--models",nargs="*")
    ap.add_argument("--scenarios",nargs="*")
    ap.add_argument("--periods",nargs="*")
    ap.add_argument("--method",choices=["delta","mandv","both"],default=None)
    ap.add_argument("--models-file",help="Text file with model names or CMIP6 file names, one per line (e.g. cmip6_model_historical.txt)")
    ap.add_argument("--exclude-models",nargs="*",help="Models (or wildcards) to skip")
    ap.add_argument("--cmip6-root",help="CMIP6 data directory (default: config cmip6.root, $PYCSG_CMIP6_ROOT or ~/DATA/cmip6/data)")
    ap.add_argument("--resolution",choices=["daily","monthly","auto"],help="Time resolution of the CMIP6 data (default: config, else auto = daily, falling back to monthly)")
    ap.add_argument("--source",choices=["cmip6","config"],help="cmip6 = discover files under the CMIP6 directory; config = models listed in config.yaml")
    ap.add_argument("--list-catalog",action="store_true",help="Print the discovered CMIP6 models/scenarios and exit")
    ap.add_argument("--dry-run",action="store_true",help="Show the runs that would be performed and exit")
    ap.add_argument("--stations",nargs="*",help="Station baseline files in the input dir: names (ETHA0QXX, ETHA0QXX.AgMIP), 4-letter codes (ETHA), wildcards (ET*) or 'all'. Default: baseline.file from the config")
    ap.add_argument("--stations-file",help="Text file with station names (whitespace/comma/line separated, '#' comments)")
    ap.add_argument("--exclude-stations",nargs="*",help="Stations (or wildcards) to skip")
    ap.add_argument("--input-dir",help="Directory holding the station .AgMIP files (default: config paths.input_dir)")
    ap.add_argument("--list-stations",action="store_true",help="List the station files found in the input dir and exit")
    ap.add_argument("--seed",type=int,default=42,help="Kept for compatibility; M&V is deterministic")
    args=ap.parse_args()
    config_path=Path(args.config).resolve(); cfg=yaml.safe_load(config_path.read_text())
    project=config_path.parent.parent
    input_dir=Path(args.input_dir).expanduser() if args.input_dir else project/cfg["paths"]["input_dir"]; model_dir=project/cfg["paths"]["model_dir"]; output_dir=project/cfg["paths"]["output_dir"]
    methods=["delta","mandv"] if (args.method or cfg.get("method","both"))=="both" else [args.method or cfg.get("method")]
    periods=args.periods or list(cfg["future_periods"])
    unknown=[p for p in periods if p not in cfg["future_periods"]]
    if unknown: ap.error(f"Unknown period(s) {unknown}; configured: {list(cfg['future_periods'])}")
    report=[]; hist_cache={}
    if args.list_stations:
        for p in stn.list_stations(input_dir): print(p.name)
        return 0
    wanted=list(args.stations or [])
    if args.stations_file: wanted+=stn.read_station_names(args.stations_file)
    if wanted:
        station_paths,bad=stn.match_stations(input_dir,wanted)
        for b in bad: report.append({"station":b,"status":"failed","error":f"No station file matches '{b}' in {input_dir} (see --list-stations)"})
    else:
        default=input_dir/cfg["baseline"]["file"]; found=stn.list_stations(input_dir)
        if default.exists(): station_paths=[default]
        elif len(found)==1: station_paths=found
        elif args.list_catalog or args.dry_run: station_paths=[default]
        else: ap.error(f"Default station file {default.name} not found in {input_dir}. Choose station(s) with --stations "
                       f"(e.g. --stations {found[0].name if found else 'ETAD0QXX.AgMIP'}); available: "
                       +(", ".join(p.name for p in found) if found else "none"))
    if args.exclude_stations:
        drop,_=stn.match_stations(input_dir,args.exclude_stations); station_paths=[p for p in station_paths if p not in drop]
    if not station_paths: ap.error("No station files selected")
    source=args.source or cfg.get("data_source") or ("cmip6" if (args.cmip6_root or cfg.get("cmip6")) else "config")
    if source=="cmip6":
        root=args.cmip6_root or os.environ.get("PYCSG_CMIP6_ROOT") or cfg.get("cmip6",{}).get("root") or cc.DEFAULT_ROOT
        try: cat=cc.Catalog.scan(root)
        except cc.CatalogError as e: ap.error(str(e))
        if args.list_catalog: _print_catalog(cat); return 0
        runs=_cmip6_runs(args,cfg,cat,report)
        model_dir=cat.root
    else:
        if args.list_catalog: ap.error("--list-catalog needs --source cmip6")
        models=args.models or list(cfg["models"]); scenarios=args.scenarios or list(cfg["scenarios"])
        runs=[]
        for model in models:
            if model not in cfg["models"]: report.append({"model":model,"status":"failed","error":"Model not configured"});continue
            for scenario in scenarios:
                if scenario not in cfg["scenarios"]: LOG.warning("Unknown scenario %s",scenario);continue
                runs.append({"model":model,"scenario":scenario,"resolution":cfg["models"][model].get("resolution","config"),"cfg":cfg["models"][model],"sel":None})
    if args.dry_run:
        for r in runs: print(f"{r['model']:<28} {r['scenario']:<7} {r['resolution']:<8} periods={','.join(periods)}")
        print("stations:",", ".join(p.name for p in station_paths))
        print(f"{len(runs)} model/scenario runs x {len(periods)} period(s) x {len(station_paths)} station(s); {len([x for x in report if x.get('status')=='failed'])} unavailable/unmatched")
        for x in report: print("  skipped:",x.get("model",""),x.get("scenario",""),x.get("error",""))
        return 0
    output_dir.mkdir(parents=True,exist_ok=True)
    codes=[]
    for sp in station_paths:
        try: basefile=read_agmip(sp)
        except Exception as e:
            report.append({"station":sp.name,"status":"failed","error":f"Cannot read station file: {e}"}); continue
        if basefile.station.code in codes:
            report.append({"station":sp.name,"status":"failed","error":f"Duplicate station code {basefile.station.code}; outputs would overwrite each other"}); continue
        codes.append(basefile.station.code)
        for run in runs:
            model,scenario,mc=run["model"],run["scenario"],run["cfg"]
            for period_key in periods:
                fp=cfg["future_periods"][period_key]
                base={"station":basefile.station.code,"model":model,"scenario":scenario,"period":period_key,"resolution":run["resolution"]}
                try:
                    sel=run["sel"]
                    if sel is not None:
                        if not _years_covered(cfg["baseline"]["period"],sel.hist_range):
                            raise ValueError(f"Historical files cover {sel.hist_range[0]}-{sel.hist_range[1]}, baseline needs {cfg['baseline']['period']['start']} to {cfg['baseline']['period']['end']}")
                        if not _years_covered(fp,sel.future_range):
                            raise ValueError(f"{scenario} files cover {sel.future_range[0]}-{sel.future_range[1]}, period '{period_key}' needs {fp['start']} to {fp['end']}")
                    factors=_calculate_factors(mc,scenario,model_dir,cfg,basefile.station,cfg["baseline"]["period"],fp,hist_cache)
                    for method in methods:
                        try:
                            if method=="mandv" and not factors["daily_model_data"]:
                                raise ValueError("M&V requires daily model data for temperature variability and wet-day frequency. Use --method delta (or --resolution daily).")
                            if method=="delta": adjusted=apply_delta(basefile.data,factors)
                            else: adjusted=apply_mandv(basefile.data,factors,cfg.get("wet_day_threshold_mm",1.0),cfg.get("gamma_factor",1.0),args.seed)
                            name=_output_name(basefile.station.code,scenario,model,period_key,method+("_monthly" if run["resolution"]=="monthly" else ""))
                            header=(f"{model} | {scenario} | {fp['start']} to {fp['end']} | "
                                    f"AgMIP {method} method | grid {factors['grid']['lat']:.4f}, {factors['grid']['lon']:.4f}")
                            write_agmip(output_dir/name,basefile.station,adjusted,header,full=(method == "mandv"))
                            report.append({**base,"method":method,"status":"success","output":name,"grid_lat":factors["grid"]["lat"],"grid_lon":factors["grid"]["lon"]})
                        except Exception as e:
                            LOG.exception("Failed %s %s %s %s",model,scenario,period_key,method)
                            report.append({**base,"method":method,"status":"failed","error":str(e)})
                except Exception as e:
                    LOG.exception("Could not calculate factors for %s %s %s",model,scenario,period_key)
                    report.append({**base,"status":"failed","error":str(e)})
    pd.DataFrame(report).to_csv(output_dir/"generation_report.csv",index=False)
    (output_dir/"generation_report.json").write_text(json.dumps(report,indent=2))
    failed=[r for r in report if r.get("status")!="success"]
    for r in failed: LOG.error("FAILED %s",{k:v for k,v in r.items() if k in ("station","model","scenario","period","method","error")})
    LOG.info("Completed: %d succeeded, %d failed. Results: %s",len(report)-len(failed),len(failed),output_dir)
    return 1 if failed and len(failed)==len(report) else 0

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    rc=main()
    # All outputs/reports are written and every dataset closed by now. Some conda installs mix
    # incompatible HDF5/netCDF libraries, which makes the interpreter crash ("free(): invalid
    # pointer") during shutdown; exiting directly avoids that teardown.
    import sys; logging.shutdown(); sys.stdout.flush(); sys.stderr.flush()
    os._exit(rc or 0)
