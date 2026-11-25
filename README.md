# AgMIP Climate Scenario Generator — Python + CMIP NetCDF

This project ports the core workflows in the supplied AgMIP Climate-Scenarios-Generator R v2.0 source. It removes the MATLAB `.mat` climatology and grid-coordinate dependencies and calculates the monthly model statistics directly from CMIP NetCDF.

## Source R functions mapped to Python

| Original R source | Python module/function |
|---|---|
| `acr_findspot.R` | `netcdf_io.nearest_cell()` (1-D and 2-D grids) |
| `agmip_simple_delta.R` | `scenario_methods.apply_delta()` |
| `agmip_simple_mandv.R` | `scenario_methods.apply_mandv()` |
| `run_agmip_simple_delta.R` | `main.py --method delta` |
| `run_agmip_simple_mandv.R` | `main.py --method mandv` |
| `agmip_simple2full.R` | `simple2full.convert_simple_to_full()` / `convert_simple_to_full.py` |
| `acr_agmip2metrics.R` | `climate_metrics.calculate_metrics()` |
| `agmip_farmclimate.R` | `farmclimate.generate_farm_sites()` with monthly NetCDF climatology |

The two scenario methods follow the source R definitions:

- **Delta:** monthly additive Tmax/Tmin changes; monthly multiplicative precipitation ratio capped at 3; ensure Tmax > Tmin.
- **M&V:** impose monthly temperature mean and standard deviation changes; adjust Tmin after applying the new Tmax while retaining baseline daily temperature range; adjust precipitation wet-day count, gamma shape/scale and monthly mean; reduce/increase solar radiation by 10% when days are converted dry/wet, as in the R code.

The Python M&V implementation is a deterministic, maintainable translation of the source method's statistical intent, not a line-by-line reproduction of its iterative CDF-fitting loops and random tie-breaking. Validate against R outputs before publication.

## NetCDF data requirements

For each model, configure either:

1. One combined NetCDF file containing `tasmax`, `tasmin`, `pr` and the required historical + future time coverage; or
2. Separate historical and SSP experiment files using `experiments` in YAML; each experiment may be a list of files to combine.

Required variables:
- `tasmax`: daily maximum temperature, Kelvin or Celsius
- `tasmin`: daily minimum temperature, Kelvin or Celsius
- `pr`: precipitation, preferably kg m-2 s-1 (converted to mm/day), or documented mm/day values

Coordinates: CF time plus 1-D latitude/longitude or 2-D curvilinear latitude/longitude. Common names (`latitude`, `longitude`, `nav_lat`, `nav_lon`, `valid_time`) are recognized. For non-standard names, edit `variables` or extend aliases in `src/netcdf_io.py`.

Daily data are required for M&V because monthly data cannot represent daily temperature variability or wet-day frequency. Monthly NetCDF can be used with `--method delta`.

## Setup

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/WSL: source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # optional, for the tests
python -m pytest                        # run from the project root
```

The supplied archive sample is copied to `input/USAM0XXX.AgMIP`. It is an Ames, Iowa station and is included only as a format/test example; replace it with your own station-specific daily baseline before producing research outputs.

Copy CMIP files to `data/models/`. The YAML contains all 37 model names supplied by the user. Edit paths to match the actual files. For separate experiment files, use for example:

```yaml
models:
  CCCma - CanESM6-0-MR:
    experiments:
      historical: [CanESM6_tasmax_historical.nc, CanESM6_tasmin_historical.nc, CanESM6_pr_historical.nc]
      ssp245: [CanESM6_tasmax_ssp245.nc, CanESM6_tasmin_ssp245.nc, CanESM6_pr_ssp245.nc]
    historical_experiment: historical
    scenario_experiments:
      ssp245: ssp245
```

When all variables and experiments are in a single NetCDF file, keep `file: model.nc`. Do not assume a single NetCDF file contains all variables or SSP experiments until its metadata has been inspected.

## Using the CMIP6 data directory (all or selected models / SSPs)

PyCSG discovers files automatically under `~/DATA/cmip6/data` (change with `cmip6.root` in `config/config.yaml`, `--cmip6-root`, or `$PYCSG_CMIP6_ROOT`):

```
~/DATA/cmip6/data/{daily,monthly}/{historical,ssp1_2_6,ssp2_4_5,ssp3_7_0,ssp4_6_0,ssp5_8_5}/
    <model>_<var>_lat2to16_lon32to49_19800101_20141231.nc     # historical
    <model>_<var>_lat2to16_lon32to49_20150101_21001231.nc     # every SSP
```

One file per model and variable is expected; `tasmax`, `tasmin` and `pr` are required (the others, e.g. `huss`, `psl`, `sfcwind`, `tas`, are ignored). Directory names `ssp1_2_6` are exposed as scenario `ssp126` (and so on up to `ssp585`). A model/scenario with a missing variable file is reported as failed in `generation_report.csv` and the rest continue.

```bash
python src/main.py --list-catalog                                   # what was found on disk
python src/main.py --dry-run --models "ec_earth3*" --scenarios ssp245 ssp585

# everything: all models, all SSPs, all periods, both methods
python src/main.py

# selected models and scenarios (names are case/punctuation-insensitive; SSP2-4.5, ssp2_4_5, ssp245, 245 all work)
python src/main.py --models canesm5 cesm2 ukesm1_0_ll --scenarios ssp245 ssp585 --periods mid end

# wildcards, exclusions, or a list file (model names OR CMIP6 file names, one per line)
python src/main.py --models "cesm2*" --exclude-models cesm2_fv2 cesm2_waccm_fv2
python src/main.py --models-file my_models.txt --scenarios ssp126 ssp370

# time resolution: auto (daily, else monthly) | daily | monthly
python src/main.py --resolution monthly --method delta
```

Choose station baseline files with `--stations ETHA ETKE`, `--stations "ET*"`, `--stations all` or `--stations-file FILE` (see `--list-stations`, `--exclude-stations`, `--input-dir`); see `docs/USER_GUIDE.md`.

Notes:
- `--models canesm5` matches exactly `canesm5` (not `canesm5_canoe`); use `canesm5*` for both.
- Historical and scenario files for one run always come from the same resolution. M&V needs `daily`; monthly data run Delta only (outputs get a `_monthly` suffix so they never overwrite daily results).
- The data are a regional subset (lat 2-16, lon 32-49). A station outside this box now raises a clear error rather than silently using an edge cell. The bundled sample station (Ames, Iowa) is outside it: use a station inside the domain.
- File-name date ranges are checked against the baseline and future periods before any NetCDF is read.
- `--source config` restores the old behaviour of using the `models:` block in the YAML.

## Period defaults

- Historical model baseline: 1980-2009 (matches the original R runner's `basedecs <- c(1980, 2009)`).
- CMIP6 near: 2021-2050.
- CMIP6 mid: 2041-2070.
- CMIP6 end: 2071-2100.

These periods are configurable and must be checked against each model's coverage. The source R runner was designed for CMIP5 RCPs and used 2010-2039, 2040-2069, 2070-2099. The Python defaults are shifted to CMIP6 SSP era and should be changed if your research protocol requires the original windows.

## Inspect the CMIP files before running

Run this first to inventory variable names, dimensions, units, experiment IDs, calendars and time coverage for all model files:

```bash
python src/inspect_netcdf.py data/models --output output/netcdf_inventory
```

Review the CSV/JSON inventory. The supplied model filenames do not establish whether each file contains all three required variables or both historical and SSP time periods.

## Run

```bash
# All configured models, SSPs, periods, both methods
python src/main.py

# One model, pathway and period
python src/main.py --models "CCCma - CanESM6-0-MR" --scenarios ssp245 --periods mid

# Delta only (monthly model data allowed)
python src/main.py --method delta

# M&V only (daily model data required)
python src/main.py --method mandv
```

Outputs are `.AgMIP` files and `output/generation_report.csv` / `.json`. Following the original R workflow, Delta outputs contain the basic eight weather columns. Convert a Delta output to a full 12-column file using:

```bash
python src/convert_simple_to_full.py --baseline input/USAM0XXX.AgMIP --simple output/YOUR_DELTA_FILE.AgMIP --output output/YOUR_FULL_FILE.AgMIP
```

M&V outputs are written as full 12-column AgMIP files.

## Additional converted workflows

- **Simple-to-full humidity conversion:** `python src/convert_simple_to_full.py --baseline input/USAM0XXX.AgMIP --simple output/BASIC_DELTA.AgMIP --output output/FULL_DELTA.AgMIP`.
- **Farm-site climate generation:** use `python src/run_farmclimate.py --seed input/USAM0XXX.AgMIP --climatology data/worldclim_monthly.nc --sites config/farm_sites.example.yaml --output output/farms`. The NetCDF must contain monthly mean temperature, precipitation and elevation. This replaces the WorldClim `.mat` inputs in the original farmclimate R script. Configure temperature scaling if the source grid stores tenths of degrees Celsius.

## Metrics

`climate_metrics.calculate_metrics(file, jdstart, jdend, column, analysis_type, reference, special_operator)` ports the original metrics options: mean, count, exceedance, max, min, standard deviation, mean consecutive days and maximum consecutive days. Column numbering follows the R script (1-12; 13 is derived daily mean temperature). Day-of-year windows may wrap around year-end.

## Missing values

AgMIP missing values (`-99`) in the baseline are preserved: Delta/M&V never shift them and they are excluded from monthly means, standard deviations, gamma fits and climate metrics.

## Important checks before running

1. Inspect every NetCDF's `source_id`, `institution_id`, `experiment_id`, `variant_label`, `grid_label`, calendar, variable names, units and `cell_methods`.
2. If historical and SSP data are separate, configure both experiments. A file containing only historical data cannot produce a future scenario.
3. If multiple files are provided, confirm they have compatible grids and time coordinates.
4. The station baseline must be a daily AgMIP file with the 12 columns: DATE, YYYY, MM, DD, SRAD, TMAX, TMIN, RAIN, WIND, DEWP, VPRS, RHUM.
5. Check whether precipitation is a flux, daily total or monthly accumulation. The conversion assumes CMIP `pr` in kg m-2 s-1 is a rate and converts it to mm/day. For monthly accumulated values, do not use the automatic rate conversion without correcting the unit metadata.
6. Compare monthly means, standard deviations, wet-day frequencies and annual totals against independent calculations. Review Tmax/Tmin consistency and missing values.
7. The original M&V R algorithm includes iterative fit tolerances and fallback behavior. This port's gamma quantile adjustment is a reproducible approximation and should be validated against the R code before impact assessment.

## `simple2full` humidity calculations

The original R script uses baseline RH and future Tmax to recompute vapour pressure and dewpoint:

`es = 6.11 * exp((2.5e6 / 461) * (1/273.16 - 1/(Tmax + 273.16)))`

`VPRS = RHUM/100 * es`, minimum 0.1 hPa; dewpoint is then derived by inverting the same Clausius-Clapeyron relation. This can be added after the basic scenario is generated; the core generator retains the baseline wind/humidity fields, so M&V outputs (which are written as full files) keep baseline DEWP/VPRS/RHUM that are not recomputed from the new Tmax. Run `convert_simple_to_full.py` on an M&V file if you need humidity consistent with the new temperatures. See the original `r/agmip_simple2full.R` for exact legacy file semantics.
