# Changelog

## Fixes

- Default station: if `baseline.file` is missing, use the only `.AgMIP` in `input/`, otherwise stop with the list of available stations.
- `main.py` exits via `os._exit` after writing results (avoids a native-library crash at interpreter shutdown seen with some conda installs).

## Station selection

- New `--stations`, `--stations-file`, `--exclude-stations`, `--list-stations`, `--input-dir` (`src/stations.py`); results cache now keyed by station location; report has a `station` column.

## CMIP6 directory support

- New `src/cmip6_catalog.py`: scans `~/DATA/cmip6/data/{daily,monthly}/<experiment>/` and indexes `<model>_<var>_lat.._lon.._<start>_<end>.nc`.
- `main.py`: new `--models` (wildcards, `all`), `--exclude-models`, `--models-file`, `--scenarios` (any SSP spelling), `--resolution`, `--cmip6-root`, `--source`, `--list-catalog`, `--dry-run`. Report now includes `resolution`; unmatched/incomplete models are reported, not fatal.
- `netcdf_io.py`: per-variable files are merged with strict grid/time checks; stations outside a regional grid raise an error.
- `config.yaml`: `data_source`, `cmip6:` block, SSP4-6.0 (`ssp460`).
- Tests: `tests/test_cmip6_catalog.py` (uses the supplied file lists as fixtures).


## Review / fix update

- **Missing values:** `-99` values are no longer shifted by Delta/M&V, averaged into monthly statistics, or counted in metrics (previously a missing Tmax became e.g. `-96`, missing rain became `0`).
- **Validation:** change factors with NaN/missing months now raise a clear error instead of writing `nan` to output files.
- **Performance:** unit conversion now happens after the nearest grid cell is selected (previously it loaded the entire global field); historical statistics are computed once per model instead of once per scenario/period.
- **Calendars:** whole-year periods are sliced by year, fixing `2070-12-31`-style slices on `360_day` calendars (e.g. UKESM).
- **main.py:** reuses `calculate_change_factors` (removed duplicated logic), validates `--periods`, logs a success/failure summary and returns a non-zero exit code if every run failed.
- **climate_metrics:** `count`/`exceedance`/consecutive-day metrics now require a reference value; Tave ignores missing days.
- **farmclimate:** vectorised (was a per-row `.loc` loop), preserves missing values, errors on no-data cells, accepts a 12-step non-`month` axis. `precipitation_scale` is a no-op (it cancelled in the ratio) and is kept only for compatibility.
- `apply_delta`/`apply_mandv` work with any DataFrame index; unused RNG removed (M&V is deterministic; `seed` kept for compatibility).
- Added `pytest.ini`, `requirements-dev.txt`, fuller `.gitignore`, and 6 new tests (9 total; the NetCDF grid test skips when xarray is absent).

## NetCDF conversion update

- Replaced MATLAB `.mat` grid lookups with xarray NetCDF coordinate discovery and nearest-cell extraction.
- Added CMIP model inventory for all 37 model entries supplied by the user.
- Added historical/SSP experiment-file configuration support.
- Implemented AgMIP delta and deterministic M&V statistical adjustment workflows.
- Added basic Delta output and full M&V output consistent with the original AgMIP workflow; added simple-to-full humidity conversion.
- Added farm-site NetCDF climatology generation and climate metrics.
- Added NetCDF metadata inventory utility.
- Added unit tests and synthetic NetCDF end-to-end validation.

## Validation status

The Python modules compile and four unit tests pass. An end-to-end run was also completed using a synthetic daily NetCDF model. The user's 37 actual CMIP NetCDF files were not included in the supplied materials, so model-specific variable names, calendars, experiment coverage, units and outputs still require validation against those files.
