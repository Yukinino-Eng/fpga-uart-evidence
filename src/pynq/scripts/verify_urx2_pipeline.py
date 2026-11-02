"""Observed RTL events -> shared session -> multiple windows -> independent replay -> existing viewer."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from uart_monitor.urx2 import RTLReplayTransport
from uart_monitor.session import MonitorSession
from uart_monitor_cli import verify_result
from uart_monitor.viewer import export_record
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--attempt',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--extra-attempt',type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False);results=[]
    cases=json.loads((ROOT/'build/uart_detector2/vectors/cases.json').read_text())
    for case in cases:
        if case.get('expect_parser_overflow'):continue
        name=case['name'];base=ROOT/'build/uart_detector2/vectors'
        expected=json.loads((base/(name+'_expected.json')).read_text())
        observed_path=args.attempt/(name+'_verification.json')
        if not observed_path.exists() and args.extra_attempt:observed_path=args.extra_attempt/(name+'_verification.json')
        observed=json.loads(observed_path.read_text())
        p=expected['compiled']['profile'];p['evidence'].update(mode='continuous',max_pending=32,max_windows=100)
        transport=RTLReplayTransport(base/(name+'_raw.bin'),p,base/(name+'_ticks.bin'),observed['event_records'],case['end_ticks'])
        report=MonitorSession(p,args.output/name,3600).run(transport)
        verification=verify_result(args.output/name)
        assert report['status']=='COMPLETED' and verification['logical_events_match'],(name,report.get('error'),verification)
        assert report['parser']['frames']==expected['frames'] and report['detection_source']=='fpga'
        assert report['events_total']==len(expected['events'])+(report['event_counts'].get('protocol:interframe_noise',0))
        assert report['evidence']['dropped_count']==0 and report['evidence']['failed_count']==0
        if name=='parallel8':
            assert report['events_total']==16 and report['evidence']['saved_count']==16
            export_record(args.output/name,args.output/'fpga_parallel8.html')
        if name=='parallel8_windows':
            assert report['events_total']==16 and report['evidence']['saved_count']==16
            windows=list((args.output/name/'events').glob('*/event.json'))
            assert len(windows)==16
            for path in windows:
                window=json.loads(path.read_text());assert not window['pre_clipped'] and not window['post_clipped']
                assert window['covered_end_ticks']-window['covered_start_ticks']==1000000000
            payload=export_record(args.output/name,args.output/'fpga_parallel8_complete_windows.html')
            from uart_monitor.viewer import document
            payload['default_field']='fault_code'
            (args.output/'fpga_parallel8_complete_windows.html').write_text(document(payload),encoding='utf-8')
        results.append(dict(name=name,frames=report['parser']['frames'],events=report['events_total'],
                            saved_windows=report['evidence']['saved_count'],verification=verification))
    receipt=dict(status='PASS_RTL_TO_SHARED_CORE_AND_VISUALIZATION',hardware_accessed=False,
                 note='Events were observed in XSim RTL; this is not physical board acceptance',cases=results)
    (args.output/'completion.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
