"""Portable Vivado build wrapper. No board programming."""
import argparse
import re
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from run_sender_tests import tool
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--vivado-bin',type=Path,required=True)
p.add_argument('--label',default='release1')
p.add_argument('--fps',type=int,choices=[10,50],default=10)
p.add_argument('--case',type=int,choices=range(-1,11),default=-1)
p.add_argument('--seconds',type=int,choices=[0,20,60,180],default=0)
a=p.parse_args()
if not re.fullmatch('[A-Za-z0-9_]+',a.label):raise ValueError('Invalid label')
work=ROOT/'build';work.mkdir(exist_ok=True)
logs=ROOT/'verification';logs.mkdir(exist_ok=True)
text=tool(a.vivado_bin,'vivado',['-mode','batch','-log',logs/('build_'+a.label+'.log'),'-journal',logs/('build_'+a.label+'.jou'),'-source',ROOT/'scripts/build.tcl','-tclargs',a.label,str(a.fps),str(a.case),str(a.seconds)],work,logs/('console_'+a.label+'.log'))
if 'BUILD_PASS WNS=' not in text:raise SystemExit('Build did not finish: inspect logs')
print('BUILD_PASS '+a.label)
