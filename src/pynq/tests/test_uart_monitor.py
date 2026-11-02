"""Contract tests: generic profiles, real trace compatibility, time and evidence failures."""
import copy
import json
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest
from contextlib import contextmanager
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from car_telemetry import TelemetryParser,encode_frame
from uart_monitor.profile import load_profile,checksum
from uart_monitor.decoder import Decoder,ByteChunk,register_decoder,make_decoder,DECODERS
from uart_monitor.rules import RuleEngine,HZ
from uart_monitor.archive import Archive,retry_saved_session
from uart_monitor.transport import ReplayTransport
from uart_monitor.session import MonitorSession


def car(sequence=0,uptime=None,**changes):
    values=dict(sequence=sequence,uptime_ms=sequence*20 if uptime is None else uptime,imu_sample_count=sequence*2,
                pitch_mdeg=-1234,rate_mdps=5678,encoder_e1=-42,encoder_e2=42,pwm_a_counts=8,pwm_b_counts=12,
                flags=35,fault_code=0,tx_skipped=0,imu_age_ms=4)
    values['imu_sample_count'] &= 0xffffffff
    values.update(changes)
    return encode_frame(values)


@contextmanager
def test_directory():
    # Inherit workspace ACLs: Python 3.13 private temp ACLs exclude this managed sandbox.
    path=ROOT/'build/pynq_z2/uart_monitor/tests_tmp'/uuid.uuid4().hex
    path.mkdir(parents=True)
    yield str(path)


def text(seq=0,ms=None,temp=25000,status=0,ending=b'\r\n'):
    body=('@LAB,%d,%d,%d,3300,%d'%(seq,seq*100 if ms is None else ms,temp,status)).encode('ascii')
    return body+('*%02X'%checksum(body[1:],'xor8')).encode('ascii')+ending


def chunk(data,offset=0,tick=0,step=10000):
    return ByteChunk(data,[tick+n*step for n in range(len(data))],offset)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.car=load_profile(ROOT/'profiles/car_tlm1.json')
        self.text=load_profile(ROOT/'profiles/lab_ascii_v1.json')
        # These original tests explicitly exercise the retained single-shot API.
        self.text['evidence']['mode']='single'

    def test_checksum_independent_known_vectors(self):
        self.assertEqual(checksum(b'123456789','crc32_iso_hdlc'),0xcbf43926)
        self.assertEqual(checksum(b'123456789','crc16_modbus'),0x4b37)
        self.assertEqual(checksum(b'123','xor8'),0x30)
        self.assertEqual(checksum(b'\xff\x02','sum8'),1)
        self.assertIsNone(checksum(b'any','none'))

    def test_profile_preflight_rejects_bad_references_bounds_settings(self):
        mutations=[lambda p:p['transport'].update(baud=12345),lambda p:p['framing'].update(length=513),
                   lambda p:p['fields'][0].update(offset=100),lambda p:p['rules'][0].update(field='missing'),
                   lambda p:p['checksum'].update(offset=100),lambda p:p['fields'][0].update(scale=float('nan')),
                   lambda p:p['rules'][0].update(op='eval'),lambda p:p['sequence'].update(field='missing'),
                   lambda p:p['fields'][3].update(valid_when=dict(field='absent',mask=1,equals=1))]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                p=copy.deepcopy(self.car);mutate(p)
                with self.assertRaises((ValueError,KeyError)):load_profile(p)

    def test_real_9024_frame_replay_matches_legacy(self):
        path=ROOT/'build/pynq_z2/car_link/live_checks/20261028_motor_run_01/evidence/raw.bin'
        if not path.is_file():path=ROOT/'evidence/baseline_car_9024/raw.bin'
        if not path.is_file():self.skipTest('Optional real car trace not included')
        raw=path.read_bytes();legacy=TelemetryParser();decoder=Decoder(self.car)
        expected=[];actual=[]
        for i in range(0,len(raw),997):
            block=raw[i:i+997];expected.extend(legacy.feed(block))
            frames,issues=decoder.feed(chunk(block,i,i*1000,1000));self.assertFalse(issues)
            actual.extend(f['raw_fields'] for f in frames)
        self.assertEqual(len(actual),9024);self.assertEqual(actual,expected)
        for key,value in legacy.summary().items():
            if key!='edge_trim_note':self.assertEqual(decoder.summary()[key],value,key)

    def test_binary_fragment_noise_crc_and_semantics_match_legacy(self):
        bad=bytearray(car(1));bad[20]^=1
        raw=b'boot\xa5'+car(0)+bytes(bad)+car(2)+car(3,pwm_a_counts=401)+car(4,flags=0)+car(5)
        for seed in range(4):
            rng=random.Random(seed);p=Decoder(self.car);old=TelemetryParser();a=[];b=[];index=0
            while index<len(raw):
                block=raw[index:index+rng.randint(1,83)]
                frames,_=p.feed(chunk(block,index,index*10000));a.extend(f['raw_fields'] for f in frames)
                b.extend(old.feed(block));index+=len(block)
            self.assertEqual(a,b)
            for key,value in old.summary().items():
                if key!='edge_trim_note':self.assertEqual(p.summary()[key],value,key)

    def test_sequence_wrap_duplicate_and_restart(self):
        d=Decoder(self.car)
        raw=car(0xffffffff,0xfffffff8)+car(0,12)+car(0,12)+car(0,0)
        _,issues=d.feed(chunk(raw))
        self.assertEqual([i['kind'] for i in issues],['duplicates','restart_or_out_of_order'])

    def test_text_lf_crlf_fields_checksum_and_long_line_recovery(self):
        d=Decoder(self.text);raw=text(0,ending=b'\n')+text(1,temp=-1250)+b'x'*4096+b'\n'+text(2)
        frames=[];issues=[]
        for i in range(0,len(raw),113):
            f,e=d.feed(chunk(raw[i:i+113],i,i*10000));frames.extend(f);issues.extend(e)
            self.assertLessEqual(len(d.buffer),512)
        self.assertEqual([f['sequence'] for f in frames],[0,1,2])
        self.assertEqual(frames[1]['fields']['temperature_mdeg'],-1.25)
        self.assertTrue(any(i['kind']=='header_errors' for i in issues))
        broken=bytearray(text(3));broken[-4]=ord('Z')
        _,issues=d.feed(chunk(broken,len(raw),len(raw)*10000))
        self.assertEqual(issues[0]['kind'],'crc_errors')

    def test_big_endian_float_scaled_and_invalid_values(self):
        p=dict(profile_version=1,id='endian',framing=dict(kind='binary',sync='abcd',length=10),checksum=dict(kind='none'),
               fields=[dict(name='n',offset=2,type='i32',byte_order='big',scale=.5),
                       dict(name='f',offset=6,type='float32',byte_order='big')])
        d=Decoder(p);raw=b'\xab\xcd'+struct.pack('>if',-10,1.25)
        frames,_=d.feed(chunk(raw));self.assertEqual(frames[0]['fields'],dict(n=-5,f=1.25))
        _,issues=d.feed(chunk(b'\xab\xcd'+struct.pack('>if',0,float('nan')),10,100000))
        self.assertEqual(issues[0]['kind'],'semantic_errors')

    def test_invalid_field_is_none_and_not_zero(self):
        d=Decoder(self.car);frames,_=d.feed(chunk(car(flags=0,pitch_mdeg=-2147483648)))
        self.assertIsNone(frames[0]['fields']['pitch_mdeg'])
        self.assertFalse(frames[0]['validity']['pitch_mdeg'])

    def test_plugin_is_explicit_and_validated(self):
        p=copy.deepcopy(self.text);p['framing']['kind']='test_plugin'
        with self.assertRaises(ValueError):load_profile(p)
        def validate(profile):
            q=copy.deepcopy(profile);q['framing']['kind']='text';load_profile(q);return profile
        def create(profile):
            q=copy.deepcopy(profile);q['framing']['kind']='text';return Decoder(q)
        try:
            register_decoder('test_plugin',create,validate)
            d=make_decoder(load_profile(p));f,_=d.feed(chunk(text()));self.assertEqual(len(f),1)
        finally:DECODERS.pop('test_plugin',None)

    def _frame(self,temp=25,tick=0,valid=True):
        return dict(fields=dict(temperature_mdeg=temp,status=0),raw_fields=dict(temperature_mdeg=int(temp*1000),status=0),
                    validity=dict(temperature_mdeg=valid,status=True),start_ticks=tick,end_ticks=tick,raw_start=0,raw_end=1)

    def test_persistence_glitch_recovery_and_invalid_continuity(self):
        e=RuleEngine(self.text)
        self.assertFalse(e.update([self._frame(70,0)],[],0))
        self.assertFalse(e.update([self._frame(25,int(.05*HZ))],[],int(.05*HZ)))
        self.assertFalse(e.update([self._frame(70,int(.1*HZ))],[],int(.1*HZ)))
        self.assertFalse(e.update([self._frame(70,int(.15*HZ),False)],[],int(.15*HZ)))
        self.assertFalse(e.update([self._frame(70,int(.2*HZ))],[],int(.2*HZ)))
        events=e.update([self._frame(70,int(.3*HZ))],[],int(.3*HZ))
        self.assertEqual([x['rule_id'] for x in events],['temperature_limit'])
        self.assertFalse(e.update([self._frame(70,int(.4*HZ))],[],int(.4*HZ)))
        e.update([self._frame(25,int(.5*HZ))],[],int(.5*HZ));self.assertTrue(e.recovered())

    def test_timeout_and_local_backlog_are_distinct(self):
        e=RuleEngine(self.text)
        self.assertFalse(e.update([],[],HZ,drained=False))
        self.assertFalse(e.recovered())
        events=e.update([],[],HZ,drained=True)
        self.assertEqual(events[0]['rule_id'],'valid_frame_timeout')
        self.assertFalse(e.update([],[],HZ+1))
        e.update([self._frame(25,HZ+2)],[],HZ+2);self.assertTrue(e.recovered())

    def test_recorded_gap_triggers_same_timeout_without_realtime_wait(self):
        e=RuleEngine(self.text)
        e.update([self._frame(25,0)],[],0)
        events=e.update([self._frame(25,HZ)],[],HZ)
        self.assertEqual([x['rule_id'] for x in events],['valid_frame_timeout'])
        self.assertEqual(events[0]['trigger_ticks'],HZ//4)

    def test_timeout_latch_survives_backlog_until_a_valid_frame_recovers(self):
        # Hardware polling can alternate drained/not-drained while the first
        # post-silence UART frame is still incomplete. The deadline is unchanged.
        e=RuleEngine(self.text)
        due=HZ//4
        first=e.update([],[],due)
        self.assertEqual([x['rule_id'] for x in first],['valid_frame_timeout'])
        for n in range(1,5):
            self.assertFalse(e.update([],[],due+n,drained=False))
            self.assertFalse(e.update([],[],due+n,drained=True))
            self.assertFalse(e.update([],[],due+n,local_ok=False))
            self.assertFalse(e.update([],[],due+n,local_ok=True))
        self.assertEqual(e.history_counts['valid_frame_timeout'],1)
        self.assertFalse(e.update([self._frame(25,HZ)],[],HZ))
        self.assertTrue(e.recovered())
        after_recovery=e.update([],[],HZ+due)
        self.assertEqual([x['rule_id'] for x in after_recovery],['valid_frame_timeout'])
        self.assertEqual(e.history_counts['valid_frame_timeout'],2)

    def test_incomplete_windows_are_explicit(self):
        with test_directory() as temp:
            a=Archive(Path(temp)/'out',self.text,0,{})
            a.append(ByteChunk(b'abc',[0,HZ//10,HZ//5]),[],[])
            a.trigger(dict(event_id=1,trigger_ticks=HZ//10,rule_id='x'))
            a.finish(HZ//5)
            self.assertTrue(a.saved['manifest']['pre_clipped'])
            self.assertTrue(a.saved['manifest']['post_clipped'])

    def test_archive_precise_window_early_stop_and_rearm(self):
        with test_directory() as temp:
            p=copy.deepcopy(self.text);p['evidence']=dict(pre_seconds=1,post_seconds=1,mode='single')
            a=Archive(Path(temp)/'out',p,0,{})
            raw=b'abcdefghij';times=[n*HZ//2 for n in range(10)]
            a.append(ByteChunk(raw,times),[],[])
            a.trigger(dict(event_id=1,trigger_ticks=2*HZ,rule_id='x'))
            a.trigger(dict(event_id=2,trigger_ticks=2*HZ+1,rule_id='y'))
            a.finish(4*HZ)
            self.assertEqual(a.state,'SAVED_LOCKED')
            directory=Path(a.saved['path']);self.assertEqual((directory/'raw.bin').read_bytes(),b'cdefg')
            self.assertFalse(a.saved['manifest']['pre_clipped']);self.assertFalse(a.saved['manifest']['post_clipped'])
            with self.assertRaises(RuntimeError):a.rearm(False)
            a.rearm(True);self.assertEqual(a.state,'ARMED')

    def test_archive_save_failure_is_retained_and_retryable(self):
        with test_directory() as temp:
            a=Archive(Path(temp)/'out',self.text,0,{})
            a.trigger(dict(event_id=1,trigger_ticks=0,rule_id='x'))
            with patch.object(a,'_export',side_effect=IOError('disk full')):
                a.poll(6*HZ);a.future.result if False else None
                try:a.future.result()
                except IOError:pass
                a.poll(6*HZ)
            self.assertEqual(a.state,'SAVE_FAILED');self.assertIsNotNone(a.pending)
            a.retry();a.finish(6*HZ);self.assertEqual(a.state,'SAVED_LOCKED')

    def test_replay_session_unknown_capabilities_and_sha_archive(self):
        with test_directory() as temp:
            root=Path(temp);(root/'in.bin').write_bytes(text(0)+text(1))
            p=copy.deepcopy(self.text);p.pop('sequence');p['checksum']=dict(kind='none')
            raw=b'@LAB,0,0,25000,3300,0\n';(root/'plain.bin').write_bytes(raw)
            session=MonitorSession(p,root/'out')
            result=session.run(ReplayTransport(root/'plain.bin',p))
            self.assertEqual(result['status'],'COMPLETED');self.assertEqual(result['protocol_integrity'],'UNKNOWN')
            self.assertEqual(result['capture_integrity'],'UNKNOWN')
            self.assertEqual((root/'out/raw.bin').read_bytes(),raw)
            self.assertEqual((root/'out/timestamps.bin').stat().st_size,len(raw)*8)

    def test_post_session_retry_advances_after_another_failed_attempt(self):
        with test_directory() as temp:
            root=Path(temp);(root/'input.bin').write_bytes(text(0,status=1)+text(1))
            with patch.object(Archive,'_export',side_effect=IOError('first save failed')):
                result=MonitorSession(self.text,root/'out').run(ReplayTransport(root/'input.bin',self.text))
            self.assertEqual(result['evidence']['state'],'SAVE_FAILED')
            self.assertIn('profile.json',result['files']);self.assertIn('provenance.json',result['files'])
            with patch.object(Archive,'_export',side_effect=IOError('retry failed')):
                with self.assertRaises(IOError):retry_saved_session(root/'out')
            saved=json.loads((root/'out/report.json').read_text())
            self.assertEqual(saved['evidence']['retry_request']['attempt'],2)
            retried=retry_saved_session(root/'out')
            self.assertEqual(retried['manifest']['attempt'],3)
            self.assertTrue(retried['readback_verified'])

    def test_hardware_counter_error_does_not_become_device_timeout(self):
        class Fake:
            hardware_accessed=True;provenance={};eof=False
            def __init__(self,status=0):self.offset=0;self.stopped=False;self.device_status=status
            def registers(self):return dict(control=0,level=0,overflows=int(self.offset>0),framing_errors=0,received=self.offset+int(self.offset>0),consumed=self.offset)
            def now_ticks(self):return HZ
            def start(self):return 0
            def read(self):
                data=text(status=self.device_status) if self.offset==0 else b''
                result=ByteChunk(data,[0]*len(data),self.offset,self.registers())
                self.offset+=len(data);self.eof=True;return result
            def stop(self):self.stopped=True
            def close(self):pass
        with test_directory() as temp:
            for status,health in ((0,'UNKNOWN'),(1,'FAIL')):
                f=Fake(status);result=MonitorSession(self.text,Path(temp)/('out_'+str(status))).run(f)
                self.assertEqual(result['capture_integrity'],'FAIL');self.assertTrue(f.stopped)
                self.assertEqual(result['device_health'],health)
                self.assertEqual(result['event_counts'].get('status_fault',0),status)


if __name__=='__main__':unittest.main()
