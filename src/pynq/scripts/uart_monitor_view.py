"""Export a self-contained, interactive URX1 evidence window from a saved record."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from uart_monitor.viewer import export_record

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=export_record(args.record,args.output)
    print('VIEW_READY frames={} events={} output={}'.format(len(data['frames']),len(data['events']),args.output.resolve()))

if __name__=='__main__':main()
