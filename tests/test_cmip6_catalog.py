"""Catalogue / selection tests using the real CMIP6 file lists (empty placeholder files)."""
import sys, types
from pathlib import Path
import numpy as np, pandas as pd, pytest
from src import cmip6_catalog as cc

DATA = Path(__file__).parent / "data"
SSP_DIRS = ["ssp1_2_6", "ssp2_4_5", "ssp3_7_0", "ssp4_6_0", "ssp5_8_5"]

def _touch(root, res, exp, listing):
    d = root / res / exp; d.mkdir(parents=True, exist_ok=True)
    for name in listing: (d / name).touch()

@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    root = tmp_path_factory.mktemp("cmip6") / "data"
    hist = (DATA / "cmip6_model_historical.txt").read_text().split()
    ssp = (DATA / "cmip6_different_SSPs.txt").read_text().split()
    _touch(root, "daily", "historical", hist)
    for d in SSP_DIRS: _touch(root, "daily", d, ssp)
    # monthly: only two models, ssp245 only; plus one incomplete daily model (no pr in ssp585)
    keep = lambda lst, ms: [f for f in lst if cc.parse_filename(f)[0] in ms]
    _touch(root, "monthly", "historical", keep(hist, {"canesm5", "cesm2"}))
    _touch(root, "monthly", "ssp2_4_5", keep(ssp, {"canesm5", "cesm2"}))
    (root / "daily" / "ssp5_8_5" / "access_cm2_pr_lat2to16_lon32to49_20150101_21001231.nc").unlink()
    (root / "daily" / "unrelated_dir").mkdir()
    return root

def test_parse_filename_handles_multiword_models_and_vars():
    p = cc.parse_filename("canesm5_canoe_sfcwind_lat2to16_lon32to49_19800101_20141231.nc")
    assert p == ("canesm5_canoe", "sfcwind", "19800101", "20141231")
    assert cc.parse_filename("cesm2_waccm_fv2_tasmax_lat2to16_lon32to49_20150101_21001231.nc")[:2] == ("cesm2_waccm_fv2", "tasmax")
    assert cc.parse_filename("mymodel_lat2to16_lon32to49_19800101_20141231.nc")[:2] == ("mymodel", None)
    assert cc.parse_filename("readme.txt") is None

def test_normalizers():
    assert [cc.normalize_experiment(x) for x in ("ssp2_4_5", "SSP2-4.5", "ssp245", "245", "historical")] == \
           ["ssp245", "ssp245", "ssp245", "ssp245", "historical"]
    assert cc.normalize_model("EC-Earth3-Veg") == "ec_earth3_veg"
    with pytest.raises(ValueError): cc.normalize_experiment("rcp85")

def test_scan_finds_58_models_and_5_ssps(tree):
    cat = cc.Catalog.scan(tree)
    assert len(cat.models("daily")) == 58
    assert cat.scenarios() == ["ssp126", "ssp245", "ssp370", "ssp460", "ssp585"]
    assert cat.resolutions() == ["daily", "monthly"]

def test_model_matching_exact_wildcard_all_and_unmatched(tree):
    cat = cc.Catalog.scan(tree)
    m, u = cat.match_models(["canesm5"], "daily"); assert m == ["canesm5"] and not u     # not canesm5_canoe
    m, _ = cat.match_models(["EC-Earth3*"], "daily")
    assert set(m) == {"ec_earth3", "ec_earth3_aerchem", "ec_earth3_cc", "ec_earth3_veg", "ec_earth3_veg_lr"}
    m, u = cat.match_models(["cesm2", "nonsense"], "daily"); assert m == ["cesm2"] and u == ["nonsense"]
    assert len(cat.match_models(["all"], "daily")[0]) == 58 and len(cat.match_models([], "daily")[0]) == 58

def test_scenario_matching(tree):
    cat = cc.Catalog.scan(tree)
    s, u = cat.match_scenarios(["ssp2_4_5", "SSP5-8.5", "ssp999", "historical"], "daily")
    assert s == ["ssp245", "ssp585"] and u == ["ssp999", "historical"]

def test_select_resolution_rules(tree):
    cat = cc.Catalog.scan(tree)
    s = cat.select("canesm5", "ssp245")                       # auto -> daily preferred
    assert s.resolution == "daily" and len(s.historical) == 3 and len(s.future) == 3
    assert s.hist_range == ("19800101", "20141231") and s.future_range == ("20150101", "21001231")
    assert cat.select("canesm5", "ssp245", "monthly").resolution == "monthly"
    with pytest.raises(cc.CatalogError): cat.select("canesm5", "ssp585", "monthly")
    with pytest.raises(cc.CatalogError, match="pr"): cat.select("access_cm2", "ssp585", "daily")   # incomplete
    assert cat.select("access_cm2", "ssp245").resolution == "daily"

def test_read_names_file_accepts_filenames_and_names(tmp_path):
    f = tmp_path / "m.txt"
    f.write_text("# comment\naccess_cm2_tas_lat2to16_lon32to49_19800101_20141231.nc\naccess_cm2_pr_lat2to16_lon32to49_19800101_20141231.nc\nEC-Earth3-Veg\n\n")
    assert cc.read_names_file(f) == ["access_cm2", "ec_earth3_veg"]
    assert len(cc.read_names_file(DATA / "cmip6_model_historical.txt")) == 58

def test_missing_root_error(tmp_path):
    with pytest.raises(cc.CatalogError): cc.Catalog.scan(tmp_path / "nope")

# ---- main.py wiring (no xarray needed: statistics extraction is stubbed) ----------
@pytest.fixture
def main_mod(monkeypatch):
    if "xarray" not in sys.modules:
        try: import xarray  # noqa
        except ImportError: monkeypatch.setitem(sys.modules, "xarray", types.ModuleType("xarray"))
    import importlib; sys.modules.pop("main", None)
    return importlib.import_module("main")

def _project(tmp_path, tree, station_lat=8.0, station_lon=38.0):
    from src.agmip_io import AgMIPStation, write_agmip
    from test_methods import sample_base
    (tmp_path / "config").mkdir(); (tmp_path / "input").mkdir()
    import shutil; shutil.copy(Path(__file__).parents[1] / "config" / "config.yaml", tmp_path / "config" / "config.yaml")
    write_agmip(tmp_path / "input" / "USAM0XXX.AgMIP", AgMIPStation("ETHA", station_lat, station_lon, 1500, -99, -99, 2, 2),
                sample_base().iloc[:400].copy(), "test")
    return tmp_path / "config" / "config.yaml"

def _fake_stats(daily=True):
    def st(mean, std=1.0, wet=0.3): return {"stats": {"mean": np.full(12, mean), "std": np.full(12, std), "wet_frequency": np.full(12, wet), "daily": daily}}
    def fake(model_cfg, exp, model_dir, cfg, station, start, end):
        fut = exp != "historical"
        return {"tasmax": st(25 + 2 * fut), "tasmin": st(15 + 2 * fut), "pr": st(3 * (1.1 if fut else 1)),
                "grid": {"lat": 8.0, "lon": 38.0, "index": {}}}
    return fake

def test_main_runs_selected_models_and_scenarios(tmp_path, tree, main_mod, monkeypatch):
    cfgp = _project(tmp_path, tree)
    monkeypatch.setattr(main_mod, "_extract_stats", _fake_stats())
    monkeypatch.setattr(sys, "argv", ["main", "--config", str(cfgp), "--cmip6-root", str(tree),
        "--models", "canesm5", "cesm2", "--scenarios", "ssp2_4_5", "ssp585", "--periods", "mid", "--method", "delta"])
    assert main_mod.main() == 0
    rep = pd.read_csv(tmp_path / "output" / "generation_report.csv")
    assert set(rep.model) == {"canesm5", "cesm2"} and set(rep.scenario) == {"ssp245", "ssp585"}
    assert (rep.status == "success").all() and len(rep) == 4
    assert (tmp_path / "output" / "ETHA_ssp245_canesm5_mid_delta.AgMIP").exists()

def test_main_reports_unavailable_without_aborting(tmp_path, tree, main_mod, monkeypatch):
    cfgp = _project(tmp_path, tree)
    monkeypatch.setattr(main_mod, "_extract_stats", _fake_stats())
    monkeypatch.setattr(sys, "argv", ["main", "--config", str(cfgp), "--cmip6-root", str(tree),
        "--models", "access_cm2", "bogus_model", "--scenarios", "ssp585", "ssp245", "--periods", "end", "--method", "delta"])
    assert main_mod.main() == 0
    rep = pd.read_csv(tmp_path / "output" / "generation_report.csv")
    bad = rep[rep.status == "failed"]
    assert "bogus_model" in set(bad.model) and any("pr" in str(e) for e in bad.error)
    assert ((rep.model == "access_cm2") & (rep.scenario == "ssp245") & (rep.status == "success")).any()

def test_main_monthly_resolution_blocks_mandv_but_allows_delta(tmp_path, tree, main_mod, monkeypatch):
    cfgp = _project(tmp_path, tree)
    monkeypatch.setattr(main_mod, "_extract_stats", _fake_stats(daily=False))
    monkeypatch.setattr(sys, "argv", ["main", "--config", str(cfgp), "--cmip6-root", str(tree), "--resolution", "monthly",
        "--models", "cesm2", "--scenarios", "ssp245", "--periods", "mid", "--method", "both"])
    main_mod.main()
    rep = pd.read_csv(tmp_path / "output" / "generation_report.csv").set_index("method")
    assert rep.loc["delta", "status"] == "success" and rep.loc["mandv", "status"] == "failed"
    assert (tmp_path / "output" / "ETHA_ssp245_cesm2_mid_delta_monthly.AgMIP").exists()

def test_dry_run_and_list_do_not_need_baseline_or_write(tmp_path, tree, main_mod, monkeypatch, capsys):
    cfgp = _project(tmp_path, tree)
    (tmp_path / "input" / "USAM0XXX.AgMIP").unlink()
    monkeypatch.setattr(sys, "argv", ["main", "--config", str(cfgp), "--cmip6-root", str(tree), "--list-catalog"])
    assert main_mod.main() == 0 and "canesm5" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["main", "--config", str(cfgp), "--cmip6-root", str(tree), "--dry-run",
        "--models", "ec_earth3*", "--exclude-models", "ec_earth3_cc", "--scenarios", "ssp126"])
    assert main_mod.main() == 0
    out = capsys.readouterr().out
    assert "ec_earth3_veg_lr" in out and "ec_earth3_cc" not in out and "4 model/scenario runs" in out
    assert not (tmp_path / "output" / "generation_report.csv").exists()

def test_models_file_option(tmp_path, tree, main_mod, monkeypatch, capsys):
    cfgp = _project(tmp_path, tree)
    lst = tmp_path / "sel.txt"; lst.write_text("noresm2_lm\nmiroc6_tas_lat2to16_lon32to49_19800101_20141231.nc\n")
    monkeypatch.setattr(sys, "argv", ["main", "--config", str(cfgp), "--cmip6-root", str(tree), "--dry-run",
        "--models-file", str(lst), "--scenarios", "ssp245"])
    main_mod.main(); out = capsys.readouterr().out
    assert "noresm2_lm" in out and "miroc6" in out and "2 model/scenario runs" in out


# ---- station selection -------------------------------------------------------
CODES = ["ETAD", "ETCH", "ETHA", "ETKR", "ETRO", "ETAL", "ETDE", "ETKE", "ETMA"]

def _stations(tmp_path):
    from src.agmip_io import AgMIPStation, write_agmip
    from test_methods import sample_base
    d = tmp_path / "input"; d.mkdir(exist_ok=True)
    for i, c in enumerate(CODES):
        write_agmip(d / f"{c}0QXX.AgMIP", AgMIPStation(c, 8.0 + 0.1 * i, 38.0, 1500, -99, -99, 2, 2),
                    sample_base().iloc[:400].copy(), "t")
    return d

def test_station_matching(tmp_path):
    from src import stations as stn
    d = _stations(tmp_path)
    names = lambda r: [p.name for p in r[0]]
    assert names(stn.match_stations(d, ["ETHA"])) == ["ETHA0QXX.AgMIP"]
    assert names(stn.match_stations(d, ["etha0qxx.agmip", "ETAD0QXX"])) == ["ETHA0QXX.AgMIP", "ETAD0QXX.AgMIP"]
    assert names(stn.match_stations(d, ["ETA*"])) == ["ETAD0QXX.AgMIP", "ETAL0QXX.AgMIP"]
    assert len(stn.match_stations(d, ["all"])[0]) == len(CODES)
    assert stn.match_stations(d, ["ETXX"])[1] == ["ETXX"]

def test_main_multiple_stations(tmp_path, tree, main_mod, monkeypatch, capsys):
    cfgp = _project(tmp_path, tree); _stations(tmp_path)
    monkeypatch.setattr(main_mod, "_extract_stats", _fake_stats())
    monkeypatch.setattr(sys, "argv", ["main", "--config", str(cfgp), "--list-stations"])
    assert main_mod.main() == 0 and "ETKE0QXX.AgMIP" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["main", "--config", str(cfgp), "--cmip6-root", str(tree), "--stations", "ETHA", "ETKE0QXX.AgMIP", "ETBAD",
        "--exclude-stations", "ETKE", "--models", "cesm2", "--scenarios", "ssp245", "--periods", "mid", "--method", "delta"])
    assert main_mod.main() == 0
    rep = pd.read_csv(tmp_path / "output" / "generation_report.csv")
    ok = rep[rep.status == "success"]
    assert list(ok.station) == ["ETHA"] and (tmp_path / "output" / "ETHA_ssp245_cesm2_mid_delta.AgMIP").exists()
    assert "ETBAD" in set(rep.station)

def test_stations_file_and_all(tmp_path, tree, main_mod, monkeypatch, capsys):
    cfgp = _project(tmp_path, tree); _stations(tmp_path)
    f = tmp_path / "st.txt"; f.write_text("ETAD0QXX.AgMIP, ETCH0QXX.AgMIP  # two\nETRO\n")
    monkeypatch.setattr(sys, "argv", ["main", "--config", str(cfgp), "--cmip6-root", str(tree), "--dry-run",
        "--stations-file", str(f), "--models", "cesm2", "--scenarios", "ssp245"])
    main_mod.main(); out = capsys.readouterr().out
    assert "ETAD0QXX.AgMIP, ETCH0QXX.AgMIP, ETRO0QXX.AgMIP" in out and "3 station(s)" in out
