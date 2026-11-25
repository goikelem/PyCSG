"""CLI wrapper for AgMIP seasonal climate metrics."""
import argparse
try:
    from .climate_metrics import calculate_metrics
except ImportError:
    from climate_metrics import calculate_metrics


def main():
    p=argparse.ArgumentParser(description="Calculate AgMIP daily climate metrics")
    p.add_argument("--file",required=True)
    p.add_argument("--jdstart",type=int,required=True)
    p.add_argument("--jdend",type=int,required=True)
    p.add_argument("--column",type=int,required=True,help="1-12; 13 calculates Tave")
    p.add_argument("--type",dest="analysis_type",required=True,choices=["mean","count","exceedance","max","min","std","meanconsecutivedays","maxconsecutivedays"])
    p.add_argument("--reference",type=float,default=float("nan"))
    p.add_argument("--operator",type=int,default=1,choices=[-1,1])
    p.add_argument("--output",default="output/climate_metrics.csv")
    a=p.parse_args()
    result=calculate_metrics(a.file,a.jdstart,a.jdend,a.column,a.analysis_type,a.reference,a.operator)
    result.to_csv(a.output,index=False)
    print(f"Saved {a.analysis_type} metrics to {a.output}")

if __name__=="__main__":main()
