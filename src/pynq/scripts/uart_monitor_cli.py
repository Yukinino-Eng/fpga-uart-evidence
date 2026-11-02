"""Configurable receive-only UART capture, replay and independent archive verification."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from uart_monitor.profile import load_profile
from uart_monitor.transport import Transport,ReplayTransport,digest
from uart_monitor.session import MonitorSession


def verify_result(root):
    root=Path(root);report=json.loads((root/'report.json').read_text())
    for name,expected in report['files'].items():
        if digest(root/name)!=expected:raise ValueError('Archive mismatch: '+name)
    from uart_monitor.decoder import make_decoder
    from uart_monitor.rules import RuleEngine
    profile=load_profile(root/'profile.json');decoder=make_decoder(profile)
    engine=RuleEngine(profile,report['start_ticks']);logical=[]
    local_ok=not any(report['hardware_registers'].get(k,0) for k in ('overflows','framing_errors','event_overflows','parser_overflows'))
    source=ReplayTransport(root/'raw.bin',profile,root/'timestamps.bin')
    stored=(root/'frames.jsonl').open(encoding='utf-8')
    matched=0
    try:
        source.start()
        while True:
            chunk=source.read();frames,issues=decoder.feed(chunk)
            logical.extend(engine.update(frames,issues,source.now_ticks(),local_ok=local_ok))
            for frame in frames:
                if json.loads(next(stored))!=frame:raise ValueError('Decoded frame mismatch')
                matched+=1
            if source.eof:break
        if next(stored,None) is not None:raise ValueError('Extra saved frames')
        tail=decoder.finish()
        logical.extend(engine.update([],tail,report['end_ticks'],local_ok=local_ok))
        if decoder.summary()!=report['parser']:raise ValueError('Parser report mismatch')
    finally:source.close();stored.close()
    for event in (root/'events').glob('*/event.json') if (root/'events').exists() else []:
        data=json.loads(event.read_text())
        for name,expected in data['files'].items():
            if digest(event.parent/name)!=expected:raise ValueError('Event mismatch: '+str(event))
    recorded=[json.loads(line) for line in (root/'events.jsonl').read_text().splitlines()]
    def identity(event):return (event['rule_id'],event['trigger_ticks'],event['evidence'])
    comparable=local_ok
    hardware_rules=report.get('detection_source')=='fpga'
    if hardware_rules:
        from uart_monitor.hardware import compile_profile,adapt_event
        compiled=compile_profile(profile)
        def canonical(e):
            value=e['evidence'].get('raw_value') if e['category']=='device' else e['evidence'].get('count') if e['rule_id']=='protocol:sequence_missing' else None
            return e['rule_id'],e['trigger_ticks'],value
        batches=[json.loads(line) for line in (root/'hardware_events.jsonl').read_text().splitlines()]
        adapted=[e for batch in batches for e in adapt_event(batch,compiled)]
        if Counter(map(canonical,adapted))!=Counter(canonical(e) for e in recorded if e.get('source')=='fpga'):
            raise ValueError('Hardware event ledger/adapter mismatch')
        if comparable and Counter(map(canonical,logical))!=Counter(canonical(e) for e in recorded if e['category']!='capture'):
            raise ValueError('Independent software/hardware event replay mismatch')
    elif comparable and [identity(e) for e in logical]!=[identity(e) for e in recorded if e['category']!='capture']:
        raise ValueError('Logical event replay mismatch')
    return dict(status='VERIFIED',frames=matched,hardware_accessed=False,
                logical_events_match=True if comparable else None,
                event_replay_note='Local capture degradation prevents complete target-side attribution' if not comparable else 'Rules replayed from raw bytes and timestamp index',
                note='File verification/replay; no new physical acquisition')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['validate','capture','replay','verify','retry-save'])
    parser.add_argument('--profile',default='profiles/car_tlm1.json')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--raw',type=Path)
    parser.add_argument('--timestamps',type=Path)
    parser.add_argument('--bit',type=Path,default=Path('firmware/uart_monitor_rx.bit'))
    parser.add_argument('--program',action='store_true')
    parser.add_argument('--detector',choices=['software','fpga','software-urx2'],default='software')
    parser.add_argument('--seconds',type=float,default=180)
    parser.add_argument('--baud',type=int)
    parser.add_argument('--require-clean',action='store_true',help='Fail if capture or protocol integrity is not PASS')
    args=parser.parse_args(argv)
    if args.action=='retry-save':
        if not args.output:parser.error('--output is required')
        from uart_monitor.archive import retry_saved_session
        print(json.dumps(retry_saved_session(args.output),indent=2));return 0
    if args.action=='verify':
        if not args.output:parser.error('--output is required')
        print(json.dumps(verify_result(args.output),indent=2));return 0
    profile=load_profile(args.profile)
    if args.baud:profile['transport']['baud']=args.baud;profile=load_profile(profile)
    if args.action=='validate':
        if args.detector=='fpga':
            from uart_monitor.hardware import compile_profile
            compile_profile(profile)
        print(json.dumps(dict(status='VALID',profile=profile),indent=2));return 0
    if not args.output:parser.error('--output is required and must be a new directory')
    session=MonitorSession(profile,args.output,args.seconds)
    if args.action=='replay':
        if not args.raw:parser.error('--raw is required for replay')
        report=session.run(ReplayTransport(args.raw,profile,args.timestamps))
    else:
        from pynq_hardware_lease import HardwareLease
        transport_class=Transport
        if args.detector=='fpga':
            from uart_monitor.urx2 import URX2Transport
            transport_class=URX2Transport
        elif args.detector=='software-urx2':
            from uart_monitor.urx2 import URX2RawTransport
            transport_class=URX2RawTransport
        with HardwareLease():report=session.run(transport_class(args.bit,profile,args.program))
    print(json.dumps(report,indent=2))
    good=report['status']=='COMPLETED' and report['capture_integrity']!='FAIL'
    if args.require_clean:good=good and report['capture_integrity']=='PASS' and report['protocol_integrity']=='PASS'
    return 0 if good else 1


if __name__=='__main__':raise SystemExit(main())
