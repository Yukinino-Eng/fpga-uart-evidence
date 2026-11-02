"""Read the scoped XSim VCD to prove eight rule fires share the frame-evaluation cycle."""
import argparse
import json
from pathlib import Path
import re

def verify(path):
    codes={};state={};last_fire=False;pulses=[];timestamp=0;ended=False
    def sample():
        nonlocal last_fire
        value=state.get(codes.get('lane_fire'));pulse=value=='11111111'
        if pulse and not last_fire:
            assert state.get(codes['frame_pulse'])=='1','Rule fire must coincide with frame evaluation'
            pulses.append(timestamp)
        last_fire=pulse
    with path.open() as stream:
        for line in stream:
            line=line.strip()
            if not ended:
                match=re.match(r'\$var\s+\w+\s+(\d+)\s+(\S+)\s+(\S+)',line)
                if match:codes[match[3]]=match[2]
                if line=='$enddefinitions $end':ended=True
                continue
            if line.startswith('#'):
                sample();timestamp=int(line[1:])
            elif line.startswith('b'):
                value,code=line[1:].split();state[code]=value
            elif line and line[0] in '01xz':state[line[1:]]=line[0]
    sample();assert len(pulses)==2,(codes,pulses)
    return dict(status='PASS_EIGHT_LANES_SAME_FRAME_CYCLE',pulses=pulses,
                wave_time_unit='VCD_declared_timescale',hardware_accessed=False,
                note='RTL wave proves concurrent lane evaluation; static timing is checked separately')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('vcd',type=Path);a=p.parse_args()
    result=verify(a.vcd);a.vcd.with_suffix('.verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
