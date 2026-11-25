"""CLI for NetCDF-based AgMIP farm-site climate generation."""
import argparse, yaml
try:
    from .farmclimate import generate_farm_sites
except ImportError:
    from farmclimate import generate_farm_sites


def main():
    p=argparse.ArgumentParser(description="Generate farm-site baseline AgMIP files from monthly NetCDF climatology")
    p.add_argument("--seed",required=True)
    p.add_argument("--climatology",required=True)
    p.add_argument("--sites",required=True,help="YAML file containing sites list")
    p.add_argument("--output",default="output/farms")
    a=p.parse_args();cfg=yaml.safe_load(open(a.sites,encoding="utf-8"))
    generate_farm_sites(a.seed,a.climatology,cfg["sites"],a.output,
        short_region=cfg.get("short_region","FS"),header=cfg.get("header","Farm site climate series"),
        variables=cfg.get("variables"),temperature_scale=cfg.get("temperature_scale",1.0),
        precipitation_scale=cfg.get("precipitation_scale",1.0))

if __name__=="__main__":main()
