"""Convert a basic AgMIP scenario into a full humidity-consistent scenario.

This ports the central calculation in the original agmip_simple2full.R:
future Tmax + baseline RH -> future vapour pressure and dewpoint.
"""
from pathlib import Path
import numpy as np
try:
    from .agmip_io import read_agmip, write_agmip
except ImportError:
    from agmip_io import read_agmip, write_agmip

EOS_HPA = 6.11
LV = 2.5e6
RV = 461.0
T0 = 273.16


def saturation_vapour_pressure_hpa(t_c):
    t_k = np.asarray(t_c, dtype=float) + T0
    return EOS_HPA * np.exp((LV / RV) * (1.0 / T0 - 1.0 / t_k))


def vapour_pressure_to_dewpoint_c(e_hpa):
    e = np.maximum(np.asarray(e_hpa, dtype=float), 0.1)
    return 1.0 / ((1.0 / T0) - (RV / LV) * np.log(e / EOS_HPA)) - T0


def convert_simple_to_full(baseline_file, simple_scenario_file, output_file, header=None):
    baseline = read_agmip(baseline_file)
    future = read_agmip(simple_scenario_file)
    b = baseline.data.copy()
    f = future.data.copy()
    if len(b) != len(f) or not np.array_equal(b.date_code.to_numpy(), f.date_code.to_numpy()):
        raise ValueError("Baseline and simple scenario must have identical daily DATE codes")
    # As in R, copy baseline wind/dewpoint/vapour pressure/RH, then recompute
    # vapour pressure and dewpoint from future Tmax and baseline RH.
    out = f.copy()
    out["wind"] = b["wind"].to_numpy()
    out["rhum"] = b["rhum"].to_numpy()
    valid = (np.isfinite(out.rhum.to_numpy(float)) & (out.rhum.to_numpy(float) > -90)
             & (out.tmax.to_numpy(float) > -90))
    out.loc[~valid, ["dewp", "vprs"]] = -99.0
    es = saturation_vapour_pressure_hpa(out.loc[valid, "tmax"].to_numpy())
    e = np.maximum(0.1, out.loc[valid, "rhum"].to_numpy(float) / 100.0 * es)
    out.loc[valid, "vprs"] = e
    out.loc[valid, "dewp"] = vapour_pressure_to_dewpoint_c(e)
    write_agmip(output_file, baseline.station, out,
                header or f"Full scenario derived from {Path(simple_scenario_file).name}")
    return out
