"""Build either FPGA independently; never program hardware."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--board', choices=['pynq', 'ego1'], required=True)
p.add_argument('--vivado-bin', type=Path, required=True)
p.add_argument('--label', required=True)
a = p.parse_args()
if not re.fullmatch(r'[a-z0-9_]+', a.label):
    p.error('Use a new label containing lowercase ASCII letters, numbers and underscores')
bin_dir = a.vivado_bin.resolve()
sys.path.insert(0, str(ROOT / 'src/ego1/tools'))
from run_sender_tests import tool
source = ROOT / 'src' / a.board
work = source / 'build' / ('invoke_' + a.label)
work.mkdir(parents=True, exist_ok=False)
script = source / 'scripts' / ('build_urx2.tcl' if a.board == 'pynq' else 'build.tcl')
text = tool(bin_dir, 'vivado', ['-mode', 'batch', '-nojournal', '-nolog', '-source', script,
                             '-tclargs', a.label], work, work / 'build_console.log')
marker = 'URX2_BUILD_PASS' if a.board == 'pynq' else 'BUILD_PASS WNS='
if marker not in text:
    raise SystemExit('Build did not report completion: ' + str(work))
print(a.board.upper() + '_BUILD_PASS label=' + a.label)

