import numpy as np, pandas as pd
from src.scenario_methods import apply_delta, apply_mandv

def sample_base():
    n=365*2
    dates=pd.date_range('2001-01-01',periods=n,freq='D')
    df=pd.DataFrame({"date_code":dates.year*1000+dates.dayofyear,"year":dates.year,"month":dates.month,"day":dates.day,
      "srad":np.full(n,15.0),"tmax":25+8*np.sin(2*np.pi*dates.dayofyear/365),"tmin":15+6*np.sin(2*np.pi*dates.dayofyear/365),
      "rain":np.where(np.arange(n)%4==0,5.0,0.0),"wind":2.0,"dewp":10.0,"vprs":12.0,"rhum":60.0})
    return df

def factors():
    return {"tasmax":{"mean_change":np.ones(12)*2,"std_ratio":np.ones(12)*1.2},
      "tasmin":{"mean_change":np.ones(12)*1,"std_ratio":np.ones(12)*0.9},
      "pr":{"mean_ratio":np.ones(12)*1.1,"wet_ratio":np.ones(12)*1.2}}

def test_delta():
    b=sample_base(); o=apply_delta(b,factors())
    assert np.all(o.tmax>o.tmin)
    assert np.allclose(o.tmax-b.tmax,2)

def test_mandv():
    b=sample_base(); o=apply_mandv(b,factors(),seed=1)
    assert np.all(o.tmax>o.tmin)
    assert np.isfinite(o.rain).all()
    assert (o.rain>=0).all()

def test_basic_and_full_io(tmp_path):
    from src.agmip_io import AgMIPStation, write_agmip, read_agmip
    df=sample_base().iloc[:30].copy()
    station=AgMIPStation('TEST01',10,40,1500,20,5,2,2)
    basic=tmp_path/'basic.AgMIP'
    write_agmip(basic,station,df,'basic scenario',full=False)
    parsed=read_agmip(basic)
    assert len(parsed.data)==30
    assert (parsed.data.wind==-99).all()
    full=tmp_path/'full.AgMIP'
    write_agmip(full,station,df,'full scenario',full=True)
    parsed_full=read_agmip(full)
    assert np.isfinite(parsed_full.data.rhum).all()

def test_curvilinear_grid_nearest_cell():
    import pytest
    xr=pytest.importorskip('xarray')
    from src.netcdf_io import nearest_cell
    lat=np.array([[10.0,10.0],[11.0,11.0]])
    lon=np.array([[39.0,40.0],[39.0,40.0]])
    ds=xr.Dataset(coords={"nav_lat":(("y","x"),lat),"nav_lon":(("y","x"),lon)})
    da=xr.DataArray(np.arange(4).reshape(2,2),dims=("y","x"))
    point,alat,alon,idx=nearest_cell(da,ds,10.8,39.1)
    assert (alat,alon)==(11.0,39.0)
    assert float(point.values)==2


def test_delta_and_mandv_preserve_missing_values():
    b=sample_base().iloc[:400].copy()
    b.loc[5,["tmax","tmin","rain","srad"]]=-99.0
    for o in (apply_delta(b,factors()), apply_mandv(b,factors())):
        assert (o.loc[5,["tmax","tmin","rain","srad"]]==-99.0).all()
        assert np.all(o.tmax.drop(5)>o.tmin.drop(5))

def test_delta_works_with_non_default_index():
    b=sample_base().iloc[100:200]          # index does not start at 0
    o=apply_delta(b,factors())
    assert len(o)==100 and np.allclose(o.tmax-b.tmax.to_numpy(),2)

def test_nan_factor_is_rejected():
    f=factors(); f["tasmax"]["mean_change"][3]=np.nan
    import pytest
    with pytest.raises(ValueError):
        apply_delta(sample_base(),f)

def test_calculate_change_factors_and_daily_flag():
    from src.scenario_methods import calculate_change_factors
    def st(mean,std=None,wet=None,daily=True):
        return {"stats":{"mean":np.full(12,mean),"std":np.full(12,std if std is not None else 1.0),
                         "wet_frequency":None if wet is None else np.full(12,wet),"daily":daily}}
    hist={"tasmax":st(20,2),"tasmin":st(10,2),"pr":st(2,wet=0.3)}
    fut={"tasmax":st(23,3),"tasmin":st(12,2),"pr":st(5,wet=0.3)}   # 2.5x rain
    f=calculate_change_factors(hist,fut)
    assert np.allclose(f["tasmax"]["mean_change"],3) and np.allclose(f["tasmax"]["std_ratio"],1.5)
    assert np.allclose(f["pr"]["mean_ratio"],2.5) and f["daily_model_data"] is True
    fut["pr"]=st(7,wet=0.3); assert np.allclose(calculate_change_factors(hist,fut)["pr"]["mean_ratio"],3)  # capped
    hist["pr"]=st(2,daily=False); assert calculate_change_factors(hist,fut)["daily_model_data"] is False

def test_metrics_ignore_missing_and_require_reference(tmp_path):
    import pytest
    from src.agmip_io import AgMIPStation, write_agmip
    from src.climate_metrics import calculate_metrics
    df=sample_base().iloc[:365].copy(); df["tmax"]=20.0; df["tmin"]=10.0; df.loc[2,"tmax"]=-99.0
    st=AgMIPStation('T',10,40,100,20,5,2,2); f=tmp_path/'m.AgMIP'
    write_agmip(f,st,df,'m')
    assert calculate_metrics(f,1,10,6,"mean").value[0]==pytest.approx(20.0)
    assert calculate_metrics(f,1,10,13,"mean").value[0]==pytest.approx(15.0, abs=0.6)
    with pytest.raises(ValueError):
        calculate_metrics(f,1,10,6,"count")

def test_simple_to_full_humidity(tmp_path):
    from src.agmip_io import AgMIPStation, write_agmip, read_agmip
    from src.simple2full import convert_simple_to_full
    st=AgMIPStation('T',10,40,100,20,5,2,2); b=sample_base().iloc[:30].copy()
    base=tmp_path/'b.AgMIP'; simple=tmp_path/'s.AgMIP'; out=tmp_path/'o.AgMIP'
    write_agmip(base,st,b,'b'); write_agmip(simple,st,apply_delta(b,factors()),'s',full=False)
    r=convert_simple_to_full(base,simple,out,"x")
    assert (r.vprs>0).all() and (r.dewp<r.tmax).all()
    assert len(read_agmip(out).data)==30
