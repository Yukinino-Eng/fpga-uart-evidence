"""Verify the included synthetic CAR-TLM1 fixture and evidence windows offline."""
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/pynq/scripts'))
from uart_monitor.profile import load_profile
from uart_monitor.hardware import compile_profile
from uart_monitor.transport import ReplayTransport
from uart_monitor.session import MonitorSession
from uart_monitor_cli import verify_result


def main():
    fixture=ROOT/'data/car/synthetic_35s'
    if not (fixture/'raw.bin').is_file():raise SystemExit('This check requires the full repository synthetic fixture')
    profile=load_profile(ROOT/'src/pynq/profiles/car_tlm1_tilt_demo.json')
    compile_profile(profile)
    target=ROOT/'out'/('car_protocol_'+uuid.uuid4().hex[:8])
    session=MonitorSession(profile,target)
    result=session.run(ReplayTransport(fixture/'raw.bin',profile,fixture/'timestamps.bin'))
    verified=verify_result(target)
    assert result['parser']['frames']==1750,result['parser']
    assert result['event_counts']=={'demo_pitch_limit':2},result['event_counts']
    assert result['evidence']['saved_count']==2 and result['evidence']['windows_integrity']=='PASS',result['evidence']
    for path in (target/'events').glob('*/event.json'):
        event=json.loads(path.read_text());assert not event['pre_clipped'] and not event['post_clipped']
    print(json.dumps(dict(status='PASS_CAR_SYNTHETIC_PROTOCOL',frames=verified['frames'],bytes=84000,
                         complete_windows=2,hardware_accessed=False,source='synthetic_fixture'),indent=2))


if __name__=='__main__':main()
