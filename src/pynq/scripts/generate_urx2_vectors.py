"""Independent software oracle and input recipes for URX2 RTL verification."""
import json
from pathlib import Path
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from car_telemetry import encode_frame
from uart_monitor.hardware import compile_profile
from uart_monitor.decoder import Decoder,ByteChunk
from uart_monitor.rules import RuleEngine
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'build/uart_detector2/vectors'

def car(n,**changes):
    values=dict(sequence=n,uptime_ms=n*20,imu_sample_count=n*2,pitch_mdeg=-1234,rate_mdps=5678,
                encoder_e1=-42,encoder_e2=42,pwm_a_counts=8,pwm_b_counts=12,flags=35,
                fault_code=0,tx_skipped=0,imu_age_ms=4)
    values.update(changes)
    return encode_frame(values)

def scenario(name,profile,packets,final_tick=None):
    compiled=compile_profile(profile);p=compiled['profile'];raw=bytearray();ticks=[]
    for tick,packet in packets:
        raw.extend(packet);ticks.extend(tick+(i+1)*8680 for i in range(len(packet)))
    decoder=Decoder(p);engine=RuleEngine(p,0);events=[];frames=[]
    for i,b in enumerate(raw):
        accepted,issues=decoder.feed(ByteChunk(bytes([b]),[ticks[i]],i))
        frames.extend(accepted);events.extend(engine.update(accepted,issues,ticks[i]))
    if final_tick is None:final_tick=(ticks[-1] if ticks else 0)
    events.extend(engine.update([],decoder.finish(),final_tick))
    (OUT/(name+'_cfg.hex')).write_text(''.join('%08x\n'%(v&0xffffffff) for v in compiled['words']))
    # Timestamp and byte are one 72-bit token; no host arrival timestamps are substituted.
    (OUT/(name+'_wire.hex')).write_text(''.join('%016x%02x\n'%(t,b) for t,b in zip(ticks,raw)))
    (OUT/(name+'_raw.bin')).write_bytes(raw)
    (OUT/(name+'_ticks.bin')).write_bytes(struct.pack('<'+'Q'*len(ticks),*ticks))
    expected=dict(name=name,compiled=compiled,bytes=len(raw),frames=len(frames),end_ticks=final_tick,
                  events=[e for e in events if e['rule_id']!='protocol:interframe_noise'],parser=decoder.summary())
    (OUT/(name+'_expected.json')).write_text(json.dumps(expected,indent=2)+'\n')
    return expected

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'axi_frame.hex').write_text(''.join('%02x\n'%value for value in car(0)))
    profile=json.loads((ROOT/'profiles/car_tlm1.json').read_text(encoding='utf-8'))
    cases=[]
    cases.append(scenario('car_rules',profile,[(n*2000000,car(n,
         fault_code=1 if 6<=n<9 else 0,imu_age_ms=40 if 10<=n<12 else 4,
         tx_skipped=1 if n==14 else 0,flags=0 if n==16 else 35)) for n in range(24)]))
    p=json.loads(json.dumps(profile));p['rules']=[dict(id='parallel_%d'%i,kind='compare',field='fault_code',op='gt',value=i,duration_ms=0) for i in range(8)]
    cases.append(scenario('parallel8',p,[(n*2000000,car(n,fault_code=20 if n in (3,4,7) else 0)) for n in range(10)]))
    cases.append(scenario('parallel8_windows',p,[(n*10000000,car(n,fault_code=20 if n in (60,61,140,141) else 0)) for n in range(210)]))
    p=json.loads(json.dumps(profile));p['rules']=[dict(id='pitch_limit',kind='range',field='pitch_mdeg',min=-10,max=10,duration_ms=100)]
    cases.append(scenario('persistence',p,[(n*2000000,car(n,pitch_mdeg=20000 if 5<=n<7 or 12<=n<20 else -1234)) for n in range(25)]))
    packets=[]
    for n in range(25):
        packet=car(n+(1 if n>=12 else 0),fault_code=1 if n in (8,9) else 0)
        if n==5:
            packet=bytearray(packet);packet[22]^=1;packet=bytes(packet)
        if n==10:packet=car(9)
        if n==18:packet=car(0,uptime_ms=0)
        packets.append((n*2000000,packet))
    cases.append(scenario('protocol',profile,packets))
    cases.append(scenario('timeout',profile,[(n*2000000+(60000000 if n>=6 else 0),car(n)) for n in range(12)],110000000))
    cases.append(scenario('timestamp64',profile,[(0x100000000+n*2000000,car(n,fault_code=1 if n==3 else 0)) for n in range(6)]))
    malformed=[]
    for n in range(15):
        packet=car(n,fault_code=1 if n in (3,8) else 0)
        if n==2:packet=car(n,pwm_a_counts=401)
        if n==5:packet=b'\x00\xaa\x55'+packet
        if n==7:packet=b'\xa5\x5a\x01\x30'+bytes(5)
        malformed.append((n*2000000,packet))
    cases.append(scenario('semantic_resync',profile,malformed))
    for check in ('none','xor8','sum8','crc16_modbus','crc32_iso_hdlc'):
        p=dict(profile_version=1,id='integer_endian_'+check,transport=dict(baud=115200,format='8N1'),
               framing=dict(kind='binary',sync='a55a',length=16),fields=[dict(name='value',type='i16',offset=2,byte_order='big',scale=.1),
               dict(name='sequence',type='u8',offset=4),dict(name='flags',type='u8',offset=5)],
               sequence=dict(field='sequence',bits=8),rules=[dict(id='range',kind='range',field='value',min=-2.5,max=2.5,duration_ms=0),
               dict(id='bits',kind='bits',field='flags',mask=2,equals=2,duration_ms=0)],
               timing=dict(valid_frame_timeout_ms=250),evidence=dict(pre_seconds=5,post_seconds=5),
               checksum=dict(kind=check,start=0,end=12,offset=12,byte_order='big'))
        from uart_monitor.profile import checksum
        packets=[]
        width={'none':0,'xor8':1,'sum8':1,'crc16_modbus':2,'crc32_iso_hdlc':4}[check]
        for n in range(10):
            body=bytearray(16);body[:2]=b'\xa5\x5a';struct.pack_into('>h',body,2,-100 if n in (3,4) else 10)
            body[4]=(n+252)&255;body[5]=2 if n==6 else 0
            if width:body[12:12+width]=checksum(body[:12],check).to_bytes(width,'big')
            packets.append((n*2000000,bytes(body)))
        cases.append(scenario('checksum_'+check,p,packets))
    p=dict(profile_version=1,id='float_boundary',transport=dict(baud=115200,format='8N1'),
        framing=dict(kind='binary',sync='a55a',length=8),checksum=dict(kind='none'),
        fields=[dict(name='value',type='i16',offset=2,scale=.1),dict(name='flags',type='u8',offset=4)],
        rules=[dict(id='gt',kind='compare',field='value',op='gt',value=.3,duration_ms=0),
               dict(id='le',kind='compare',field='value',op='le',value=.3,duration_ms=0)],
        timing=dict(valid_frame_timeout_ms=250),evidence=dict(pre_seconds=5,post_seconds=5))
    packets=[]
    for n,value in enumerate([0,2,3,4,2,-10,3]):
        packet=bytearray(b'\xa5\x5a'+bytes(6));struct.pack_into('<h',packet,2,value)
        packets.append((n*2000000,packet))
    cases.append(scenario('float_boundary',p,packets))
    p=json.loads(json.dumps(profile));p['fields'][3]['invalid_values']=[-1234]
    p['rules']=[dict(id='sentinel',kind='invalid',field='pitch_mdeg',duration_ms=0)]
    cases.append(scenario('invalid_sentinel',p,[(n*2000000,car(n,pitch_mdeg=-1234 if n in (2,3,7) else 1000)) for n in range(10)]))
    # Complete historical real car bytes with the originally recorded URX1 per-byte times.
    real=ROOT/'build/pynq_z2/uart_monitor/board_20261028/connected_180s_evidence'
    raw=(real/'raw.bin').read_bytes();ts=struct.unpack('<'+'Q'*len(raw),(real/'timestamps.bin').read_bytes())
    origin=ts[0]-8680
    packets=[(ts[i]-origin-8680,raw[i:i+1]) for i in range(len(raw))]
    cases.append(scenario('real_car_9027',profile,packets))
    overload=scenario('parser_overload',profile,[(0,bytes(3000))])
    overload.update(expect_parser_overflow=True)
    (OUT/'parser_overload_expected.json').write_text(json.dumps(overload,indent=2)+'\n')
    cases.append(overload)
    (OUT/'cases.json').write_text(json.dumps([dict(name=c['name'],bytes=c['bytes'],end_ticks=c['end_ticks'],
         expect_parser_overflow=c.get('expect_parser_overflow',False)) for c in cases],indent=2))
    print('URX2_ORACLE_READY cases=%d real_frames=9027'%(len(cases)))

if __name__=='__main__':main()
