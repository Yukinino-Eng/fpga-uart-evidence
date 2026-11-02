"""Match observed RTL events to the independent software rules, not a mirrored RTL model."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from uart_monitor.hardware import adapt_event
ROOT=Path(__file__).resolve().parents[1]


def record(words):
    return dict(mask=words[0],batch_id=words[1],ticks=words[2]|words[3]<<32,
                raw_start=words[4],raw_end=words[5],start_ticks=words[6]|words[7]<<32,
                last_valid_ticks=words[8]|words[9]<<32,missing=words[10],sequence=words[11],values=words[12:20],
                semantic_mask=words[20],frame_end_ticks=words[21]|words[22]<<32)


def verify(attempt,name):
    base=ROOT/'build/uart_detector2';expected=json.loads((base/'vectors'/(name+'_expected.json')).read_text())
    records=[];stats=None
    for line in (attempt/(name+'.txt')).read_text().splitlines():
        parts=line.split()
        if parts[0]=='E':records.append(record([int(x,16) for x in parts[1:]]))
        elif parts[0]=='S':stats=[int(x) for x in parts[1:]]
    if stats is None:raise ValueError('Missing terminal statistics')
    actual=[]
    for item in records:actual.extend(adapt_event(item,expected['compiled'],len(actual)+1))
    if expected.get('expect_parser_overflow'):
        assert stats[4]>0 and not actual and stats[0]==0
        output=dict(status='PASS_LOCAL_PARSER_OVERLOAD_NO_DEVICE_ATTRIBUTION',case=name,hardware_accessed=False,
                    bytes=expected['bytes'],frames=0,events=0,batches=0,overflows=stats[4],simultaneous_rule_lanes=0)
        (attempt/(name+'_verification.json')).write_text(json.dumps(output,indent=2)+'\n')
        return output
    def identity(e):
        value=e['evidence'].get('raw_value') if e['category']=='device' else e['evidence'].get('count') if e['rule_id']=='protocol:sequence_missing' else None
        return e['rule_id'],e['trigger_ticks'],value
    if Counter(map(identity,actual))!=Counter(map(identity,expected['events'])):
        raise AssertionError(dict(case=name,extra=list((Counter(map(identity,actual))-Counter(map(identity,expected['events']))).elements())[:12],
                                  missing=list((Counter(map(identity,expected['events']))-Counter(map(identity,actual))).elements())[:12]))
    assert stats[0]==expected['frames'],(name,stats[0],expected['frames'])
    assert stats[1]==expected['parser']['crc_errors'],(name,'CRC count',stats[1],expected['parser']['crc_errors'])
    assert stats[2]==expected['parser']['semantic_errors'] and stats[4]==0
    assert stats[5]==expected['parser']['sequence_missing'] and stats[6]==expected['parser']['duplicates'] and stats[7]==expected['parser']['restart_or_out_of_order']
    if name=='parallel8':assert sum((r['mask']&255)==255 for r in records)==2
    for e in actual:
        if e['category']=='device':
            match=next(x for x in expected['events'] if identity(x)==identity(e))
            assert e['evidence']==match['evidence'],(name,e,match)
    output=dict(status='PASS_RTL_SOFTWARE_EVENT_EQUIVALENCE',case=name,hardware_accessed=False,
                bytes=expected['bytes'],frames=stats[0],events=len(actual),batches=len(records),
                simultaneous_rule_lanes=max([bin(r['mask']&255).count('1') for r in records] or [0]),
                event_records=records,events_adapted=actual)
    (attempt/(name+'_verification.json')).write_text(json.dumps(output,indent=2)+'\n')
    return {k:v for k,v in output.items() if k not in ('event_records','events_adapted')}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--attempt',required=True,type=Path);parser.add_argument('--case')
    args=parser.parse_args();attempt=args.attempt.resolve()
    names=[args.case] if args.case else [c['name'] for c in json.loads((ROOT/'build/uart_detector2/vectors/cases.json').read_text())]
    results=[verify(attempt,n) for n in names]
    summary=dict(status='PASS_URX2_RTL_AND_SOFTWARE_ORACLE',hardware_accessed=False,cases=results)
    (attempt/'verification.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
