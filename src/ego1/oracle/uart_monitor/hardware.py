"""URX2 integer protocol compiler and loss-aware hardware event adapter (Python 3.6)."""
from decimal import Decimal,ROUND_CEILING,ROUND_FLOOR
import math
from .profile import load_profile,TYPES
import struct

ID=0x32585255
CFG_BASE=0x1000
CFG_WORDS=284
FIELD_BASE=16
FIELD_STRIDE=12
RULE_BASE=208
RULE_STRIDE=8
CHECKS={'none':0,'xor8':1,'sum8':2,'crc16_modbus':3,'crc32_iso_hdlc':4}
OPS={'eq':0,'ne':1,'lt':2,'le':3,'gt':4,'ge':5}
KINDS={'range':1,'compare':2,'bits':3,'invalid':4}
PROTOCOL_BITS={8:'valid_frame_timeout',9:'protocol:crc_errors',10:'protocol:sequence_missing',
               11:'protocol:duplicates',12:'protocol:restart_or_out_of_order',13:'protocol:semantic_errors'}


def compile_profile(source):
    p=load_profile(source)
    if p['framing']['kind']!='binary':raise ValueError('URX2 requires fixed binary framing; use URX1 software for text/plugins')
    if p.get('analysis'):raise ValueError('URX2 does not execute optional behavior models')
    sync=bytes.fromhex(p['framing']['sync']);fields=p['fields'];rules=p['rules'];constants=p['framing'].get('constants',[])
    if not 1<=len(sync)<=4 or len(fields)>16 or len(rules)>8 or len(constants)>4:
        raise ValueError('URX2 limits: sync<=4 bytes, 16 fields, 8 rules, 4 constant segments')
    if any(f['type'] not in ('u8','i8','u16','i16','u32','i32') for f in fields):
        raise ValueError('URX2 hardware fields are 8/16/32-bit integers')
    names={f['name']:i for i,f in enumerate(fields)};cfg=[0]*CFG_WORDS
    cfg[0]=p['framing']['length'];cfg[1]=int.from_bytes(sync,'little');cfg[2]=len(sync)
    c=p['checksum'];cfg[3]=CHECKS[c['kind']]
    if c['kind']!='none':
        cfg[4:8]=[c['start'],c['end'],c['offset'],int(c['byte_order']=='big')]
    seq=p.get('sequence',{})
    cfg[8:14]=[names[seq['field']] if seq else 255,seq.get('bits',32),
              names[seq['time_field']] if seq.get('time_field') else 255,seq.get('time_bits',32),0,0]
    if seq and (seq['bits']>32 or seq.get('time_bits',32)>32):raise ValueError('URX2 sequence/time fields <=32 bits')
    timeout=int(p['timing']['valid_frame_timeout_ms']*100000000/1000)
    cfg[12:14]=[timeout&0xffffffff,timeout>>32];cfg[14]=len(fields);cfg[15]=(1<<len(rules))-1
    for i,f in enumerate(fields):
        width=struct.calcsize(TYPES[f['type']]);signed=f['type'].startswith('i');flags=0
        lower=-(1<<(width*8-1)) if signed else 0;upper=(1<<(width*8-int(signed)))-1
        if 'min' in f:lower=f['min'];flags|=1
        if 'max' in f:upper=f['max'];flags|=2
        if int(lower)!=lower or int(upper)!=upper:raise ValueError('Hardware semantic bounds must be integers')
        allowed=f.get('allowed_mask',0xffffffff)
        if 'allowed_mask' in f:flags|=4
        forbidden=f.get('forbidden_mask_values',[]);invalid=f.get('invalid_values',[])
        if len(forbidden)>1 or any(len(x['values'])!=1 for x in forbidden) or len(invalid)>1:
            raise ValueError('URX2 supports one forbidden mask/value and one invalid sentinel per field')
        if forbidden:flags|=8
        if invalid:flags|=16
        condition=f.get('valid_when');ref=names[condition['field']] if condition else 255
        descriptor=f['offset']|(width<<10)|(int(f['byte_order']=='big')<<13)|(int(signed)<<14)|(flags<<16)
        cfg[FIELD_BASE+i*FIELD_STRIDE:FIELD_BASE+(i+1)*FIELD_STRIDE]=[
            descriptor,int(lower)&0xffffffff,int(upper)&0xffffffff,allowed,
            forbidden[0]['mask'] if forbidden else 0,forbidden[0]['values'][0] if forbidden else 0,
            ref,condition['mask'] if condition else 0,condition['equals'] if condition else 0,
            invalid[0] if invalid else 0,0,0]
    for i,r in enumerate(rules):
        f=fields[names[r['field']]];scale=Decimal(str(f['scale']));bias=Decimal(str(f['bias']))
        if scale<=0:raise ValueError('URX2 rule fields require positive scale')
        signed=f['type'].startswith('i')
        minimum=-(1<<31) if signed else 0;maximum=(1<<31)-1 if signed else (1<<32)-1
        def converted(n):return n*f['scale']+f['bias']
        # Compile against the exact PS float conversion, including boundary rounding.
        # At runtime only integer comparisons execute in PL.
        if not all(math.isfinite(converted(n)) for n in (minimum,maximum)):
            raise ValueError('URX2 scale/bias produces nonfinite boundary values')
        def raw(value,rounding):
            lo,hi=minimum,maximum+1
            while lo<hi:
                mid=(lo+hi)//2
                before=converted(mid)<value if rounding==ROUND_CEILING else converted(mid)<=value
                if before:lo=mid+1
                else:hi=mid
            return lo if rounding==ROUND_CEILING else lo-1
        kind=KINDS[r['kind']];op=OPS.get(r.get('op'),0);a=b=0
        if kind==1:a=raw(r['min'],ROUND_CEILING);b=raw(r['max'],ROUND_FLOOR)
        elif kind==2:
            exact=raw(r['value'],ROUND_CEILING)
            if op in (0,1) and (not minimum<=exact<=maximum or converted(exact)!=r['value'] or
                                exact<maximum and converted(exact+1)==r['value']):
                raise ValueError('URX2 equality requires a unique representable raw value')
            if op==2:a=raw(r['value'],ROUND_CEILING)
            elif op==3:a=raw(r['value'],ROUND_FLOOR)
            elif op==4:a=raw(r['value'],ROUND_FLOOR)
            else:a=raw(r['value'],ROUND_CEILING)
        elif kind==3:a=r['mask'];b=r['equals']
        signed=f['type'].startswith('i')
        if kind in (1,2):
            low=-(1<<31) if signed else 0;high=(1<<31)-1 if signed else (1<<32)-1
            if not low<=a<=high or kind==1 and not low<=b<=high:raise ValueError('Threshold outside hardware integer range')
        duration=int(r['duration_ms']*100000000/1000)
        cfg[RULE_BASE+i*RULE_STRIDE:RULE_BASE+(i+1)*RULE_STRIDE]=[
            names[r['field']]|(kind<<8)|(op<<12),a&0xffffffff,b&0xffffffff,
            duration&0xffffffff,duration>>32,0,0,0]
    for i,item in enumerate(constants):
        value=bytes.fromhex(item['hex'])
        if not 1<=len(value)<=4:raise ValueError('URX2 constant segment <=4 bytes')
        cfg[272+i*3:275+i*3]=[item['offset'],int.from_bytes(value,'little'),len(value)]
    cfg=[word&0xffffffff for word in cfg]
    return dict(format='URX2-config-v1',identity=ID,profile=p,words=cfg,
                rule_ids=[r['id'] for r in rules],field_names=[f['name'] for f in fields],
                constraints='Fixed binary; positive-scale integer rules; no float/text/behavior model',hardware_accessed=False)


def adapt_event(record,compiled,first_event_id=1):
    """One batch can produce eight simultaneous rule events; no priority loss."""
    p=compiled['profile'];events=[];mask=record['mask']
    for lane,rule in enumerate(p['rules']):
        if not mask&(1<<lane):continue
        raw=record['values'][lane];f=next(f for f in p['fields'] if f['name']==rule['field'])
        if f['type'].startswith('i') and raw&(1<<31):raw-=1<<32
        events.append(dict(event_id=first_event_id+len(events),rule_id=rule['id'],category='device',
             trigger_ticks=record['ticks'],source='fpga',hardware_batch_id=record.get('batch_id'),
             evidence=dict(field=rule['field'],value=None if rule['kind']=='invalid' else raw*f['scale']+f['bias'],
                           raw_value=raw,raw_start=record['raw_start'],raw_end=record['raw_end'])))
    for bit,identity in PROTOCOL_BITS.items():
        if mask&(1<<bit):
            evidence=dict(raw_start=record['raw_start'],raw_end=record['raw_end'])
            if bit==8:evidence=dict(last_valid_ticks=record['last_valid_ticks'],deadline_ticks=record['ticks'])
            if bit==10:evidence['count']=record['missing']
            events.append(dict(event_id=first_event_id+len(events),rule_id=identity,category='protocol',
                               trigger_ticks=record['ticks'],source='fpga',hardware_batch_id=record.get('batch_id'),evidence=evidence))
    return events
