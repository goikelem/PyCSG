# PyCSG User Guide — CMIP6 models and SSP scenarios

PyCSG turns CMIP6 model output into AgMIP daily weather files for one station, using the **Delta** or **M&V** (mean and variability) method. This guide covers day-to-day use with the data in `~/DATA/cmip6/data`.

## 1. What you need

| Item | Details |
|---|---|
| Python packages | `pip install -r requirements.txt` (numpy, pandas, xarray, netCDF4, cftime, scipy, PyYAML) |
| CMIP6 data | `~/DATA/cmip6/data/{daily,monthly}/{historical,ssp1_2_6,ssp2_4_5,ssp3_7_0,ssp4_6_0,ssp5_8_5}/` |
| File names | `<model>_<var>_lat2to16_lon32to49_<start>_<end>.nc` (historical 19800101–20141231; SSPs 20150101–21001231) |
| Variables | `tasmax`, `tasmin`, `pr` are required. `tas`, `huss`, `psl`, `sfcwind` are ignored. |
| Station baseline | A daily AgMIP file in `input/`, named in `config/config.yaml` (`baseline.file`). |

**The station must lie inside the data box (lat 2–16, lon 32–49).** The bundled Ames, Iowa sample is outside it and will fail with a "outside the model domain" error. Put your own station file in `input/` and set `baseline.file`.

## 2. Quick start

```bash
cd PyCSG
python src/main.py --list-catalog                 # 1. what PyCSG found on disk
python src/main.py --dry-run --stations ETHA --models cesm2 --scenarios ssp245   # 2. preview, nothing written
python src/main.py --models cesm2 --scenarios ssp245 --periods mid --method delta   # 3. one small run
python src/main.py                                # 4. everything
```

Start with step 3 on one model before launching step 4. A full run is every model × SSP × period × method.

## 3. Command-line options

| Option | Meaning |
|---|---|
| `--models A B …` | Models to run. Case/punctuation-insensitive (`EC-Earth3-Veg` = `ec_earth3_veg`). Wildcards allowed (`"ec_earth3*"`). `all` or omitted = every model. |
| `--exclude-models A B …` | Skip these (wildcards allowed). |
| `--models-file FILE` | Text file, one entry per line, `#` comments. Entries can be model names **or** CMIP6 file names; the model is parsed out. Combines with `--models`. |
| `--scenarios …` | `ssp126 ssp245 ssp370 ssp460 ssp585`; any spelling works (`ssp2_4_5`, `SSP2-4.5`, `245`). Omitted = all SSPs found on disk. |
| `--periods near mid end` | Future windows from the config (default 2021–50, 2041–70, 2071–2100). |
| `--method delta\|mandv\|both` | Default `both`. |
| `--resolution daily\|monthly\|auto` | Default `auto` (daily, else monthly). |
| `--cmip6-root DIR` | Data directory. Also `$PYCSG_CMIP6_ROOT` or `cmip6.root` in the config. |
| `--source cmip6\|config` | `config` uses the hand-written `models:` block in the YAML (legacy). |
| `--list-catalog` | Print discovered models, scenarios and which are complete. Exits. |
| `--dry-run` | Print planned runs and any skipped/unmatched ones. Exits. Needs no station file. |
| `--stations A B …` | Station baseline files in `input/` to run: file names (`ETHA0QXX`, `ETHA0QXX.AgMIP`), 4-letter codes (`ETHA`), wildcards (`"ET?A*"`) or `all`. Omitted = `baseline.file` from the config. |
| `--stations-file FILE` | Text file of station names (spaces, commas or lines; `#` comments). Combines with `--stations`. |
| `--exclude-stations …` | Skip these stations (wildcards allowed). |
| `--list-stations` | List the `.AgMIP` files found in the input dir. Exits. |
| `--input-dir DIR` | Folder with the station files (default `paths.input_dir`). |
| `--config FILE` | Alternative YAML (default `config/config.yaml`). |

Matching notes: `--models canesm5` matches only `canesm5`; use `"canesm5*"` to include `canesm5_canoe`. Quote wildcards so the shell doesn't expand them.

## 4. Recipes

```bash
# Two models, two SSPs, mid and end of century
python src/main.py --models canesm5 ukesm1_0_ll --scenarios ssp245 ssp585 --periods mid end

# All CESM2 variants except the FV2 ones
python src/main.py --models "cesm2*" --exclude-models cesm2_fv2 cesm2_waccm_fv2

# Your own shortlist (can be a copy of cmip6_model_historical.txt, edited)
python src/main.py --models-file shortlist.txt --scenarios ssp126 ssp370 --method delta

# Monthly data, Delta only
python src/main.py --resolution monthly --method delta

# Data stored elsewhere
python src/main.py --cmip6-root /data/cmip6 --list-catalog
```

### Choosing stations

Put all baseline files (`ETAD0QXX.AgMIP`, `ETCH0QXX.AgMIP`, …) in `input/`.

```bash
python src/main.py --list-stations
python src/main.py --stations ETHA ETKE ETRO --models cesm2 --scenarios ssp245
python src/main.py --stations "ETA*" --exclude-stations ETAL          # ETAD, ETAS
python src/main.py --stations all --method delta
python src/main.py --stations-file my_stations.txt
```

Each station is run for every selected model/scenario/period. Output files and report rows carry the station code from the file header (e.g. `ETHA_ssp245_cesm2_mid_delta.AgMIP`). A station that is unreadable, outside the model domain, or shares its header code with another selected station is reported as failed and the others continue. Every station must lie inside lat 2–16, lon 32–49.

## 5. Daily vs monthly data

- **Delta** works with daily or monthly data.
- **M&V** needs daily data (it uses day-to-day variability and wet-day frequency). With monthly data M&V is reported as failed and Delta still runs.
- For each run the historical and scenario files come from the **same** resolution. In `auto` mode a model/scenario uses daily when both are complete, otherwise monthly.
- Monthly outputs are named `…_delta_monthly.AgMIP`, so they never overwrite daily results.

## 6. Outputs

In `output/`:

- `<STATION>_<scenario>_<model>_<period>_<method>.AgMIP`, e.g. `ETHA_ssp245_cesm2_mid_delta.AgMIP`. Delta files have the 8 basic weather columns; M&V files are full 12-column.
- `generation_report.csv` / `.json`: one row per run with `station, model, scenario, period, resolution, method, status, output, grid_lat, grid_lon` and `error` for failures.

Check `generation_report.csv` after every run. Failures do not stop the batch. Typical `error` messages:

| Message | Cause / fix |
|---|---|
| `No CMIP6 model matches 'x'` | Typo or model absent. Check `--list-catalog`. |
| `Scenario 'x' not available` | No such directory under the chosen resolution. |
| `Data not available: … missing variable file(s) ['pr']` | That model lacks a required file for that experiment. |
| `Historical files cover … baseline needs …` | File names don't span the baseline or future period. |
| `Station latitude/longitude … outside the model domain` | Station is outside lat 2–16 / lon 32–49. |
| `Per-variable files have different grids or time axes` | A model's variable files don't line up; inspect with `src/inspect_netcdf.py`. |
| `M&V requires daily model data` | Run with `--resolution daily` or `--method delta`. |

## 7. Configuration (`config/config.yaml`)

```yaml
data_source: cmip6
cmip6:
  root: ~/DATA/cmip6/data
  resolution: auto
  required_variables: [tasmax, tasmin, pr]
  # default_scenarios: [ssp245, ssp585]   # optional default instead of "all"
baseline: {file: YOUR_STATION.AgMIP, period: {start: '1980-01-01', end: '2009-12-31'}}
future_periods: {near: …, mid: …, end: …}
wet_day_threshold_mm: 1.0
```

The baseline period must fall inside the historical files (1980–2014). Command-line options override the config.

## 8. Next steps and checks

- Convert Delta output to a full 12-column file: `python src/convert_simple_to_full.py --baseline input/<station>.AgMIP --simple output/<delta file> --output output/<full file>`.
- Inspect NetCDF metadata (units, calendars, variable names): `python src/inspect_netcdf.py <dir> --output output/netcdf_inventory`.
- Compute climate metrics from an output file: see `src/run_metrics.py`.
- Run the tests: `python -m pytest`.
- Validate a few models against independent calculations before using results (the M&V port is an approximation of the R method; see the README).

## 9. Troubleshooting

- **Nothing found:** run `--list-catalog`; confirm the root and that folders are named `daily`/`monthly` and `historical`/`ssp1_2_6`…
- **Run is slow:** each model/scenario/period reads the station time series from the files; narrow with `--models`, `--scenarios`, `--periods`.
- **Unexpected model chosen/missed:** use `--dry-run` to see exactly what will run.
