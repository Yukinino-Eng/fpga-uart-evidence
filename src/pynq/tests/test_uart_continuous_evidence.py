"""Overlapping windows, bounded capacity, durable retries and dynamic protocol preview."""
import contextlib
import copy
import io
import json
import struct
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from uart_monitor.archive import Archive,retry_saved_session
from uart_monitor.decoder import ByteChunk
from uart_monitor.profile import load_profile
from uart_monitor.transport import HZ,digest
from uart_monitor.viewer import profile_payload
from uart_monitor.session import MonitorSession
from uart_monitor.transport import ReplayTransport
from uart_monitor_cli import verify_result


class ContinuousEvidenceTests(unittest.TestCase):
    def root(self):
        root=ROOT/'build/uart_continuous_tests'/uuid.uuid4().hex
        root.parent.mkdir(parents=True,exist_ok=True)
        return root

    def profile(self,**limits):
        profile=load_profile(ROOT/'profiles/lab_ascii_v1.json')
        profile['evidence'].update(mode='continuous',pre_seconds=1,post_seconds=1,max_pending=8,max_windows=100)
        profile['evidence'].update(limits)
        return profile

    def event(self,n,tick):
        return dict(event_id=n,rule_id='status_fault',category='device',trigger_ticks=tick,evidence={})

    def archive(self,**limits):
        archive=Archive(self.root(),self.profile(**limits),0,{})
        ticks=[n*HZ//10 for n in range(101)]
        archive.append(ByteChunk(bytes(range(101)),ticks,0),[],[])
        return archive

    def test_overlapping_windows_are_independent_and_keep_raw_slices(self):
        archive=self.archive()
        archive.trigger(self.event(1,4*HZ));archive.trigger(self.event(2,4*HZ+HZ//2))
        archive.finish(10*HZ)
        status=archive.status();self.assertEqual(status['saved_count'],2)
        self.assertEqual(status['pending_count'],0);self.assertEqual(status['windows_integrity'],'PASS')
        windows=list((archive.root/'events').glob('*/event.json'))
        self.assertEqual(len(windows),2)
        for path in windows:
            event=json.loads(path.read_text())
            self.assertFalse(event['pre_clipped']);self.assertFalse(event['post_clipped'])
            self.assertEqual(event['covered_end_ticks']-event['covered_start_ticks'],2*HZ)
            self.assertEqual((path.parent/'raw.bin').read_bytes(),(archive.root/'raw.bin').read_bytes()[event['raw_start']:event['raw_end']])

    def test_default_records_three_separate_fault_episodes_without_manual_rearm(self):
        profile=load_profile(ROOT/'profiles/lab_ascii_v1.json')
        self.assertEqual(profile['evidence']['mode'],'continuous')
        folder=self.root();folder.mkdir()
        raw=bytearray();ticks=[]
        for n in range(310):
            body=('LAB,%d,%d,25000,3300,%d'%(n,n*100,int(n in (60,61,140,141,220,221)))).encode('ascii')
            check=0
            for value in body:check^=value
            packet=b'@'+body+('*%02X\r\n'%check).encode('ascii')
            raw.extend(packet);ticks.extend(n*HZ//10+(i+1)*10000 for i in range(len(packet)))
        (folder/'input.bin').write_bytes(raw)
        (folder/'ticks.bin').write_bytes(struct.pack('<'+'Q'*len(ticks),*ticks))
        report=MonitorSession(profile,folder/'record').run(ReplayTransport(folder/'input.bin',profile,folder/'ticks.bin'))
        self.assertEqual(report['event_counts'],{'status_fault':3})
        self.assertEqual(report['evidence']['saved_count'],3)
        windows=[json.loads(p.read_text()) for p in sorted((folder/'record/events').glob('*/event.json'))]
        self.assertEqual(len({w['trigger']['trigger_ticks'] for w in windows}),3)
        self.assertTrue(all(not w['pre_clipped'] and not w['post_clipped'] for w in windows))
        self.assertTrue(verify_result(folder/'record')['logical_events_match'])

    def test_pending_and_total_limits_never_hide_dropped_windows(self):
        archive=self.archive(max_pending=1,max_windows=1)
        archive.trigger(self.event(1,4*HZ));archive.trigger(self.event(2,5*HZ))
        archive.finish(10*HZ)
        status=archive.status();self.assertEqual(status['saved_count'],1)
        self.assertEqual(status['dropped_count'],1);self.assertEqual(status['windows_integrity'],'FAIL')
        self.assertEqual(len((archive.root/'events.jsonl').read_text().splitlines()),2)
        self.assertIn('LIMIT_REACHED',(archive.root/'window_index.jsonl').read_text())

    def test_failed_save_does_not_block_other_events_and_can_retry_after_stop(self):
        archive=self.archive();original=archive._export
        def fail_first(request):
            if request['trigger']['event_id']==1:raise IOError('injected storage failure')
            return original(request)
        archive._export=fail_first
        archive.trigger(self.event(1,4*HZ));archive.trigger(self.event(2,5*HZ))
        hashes=archive.finish(10*HZ)
        self.assertEqual(archive.status()['saved_count'],1)
        self.assertEqual(archive.status()['failed_count'],1)
        report=dict(evidence=archive.status(),files=hashes,error=None,status='FAILED')
        (archive.root/'report.json').write_text(json.dumps(report))
        retry_saved_session(archive.root)
        saved=json.loads((archive.root/'report.json').read_text())
        self.assertEqual(saved['evidence']['saved_count'],2)
        self.assertEqual(saved['evidence']['failed_count'],0)
        self.assertEqual(saved['status'],'COMPLETED')
        self.assertEqual(saved['files']['window_index.jsonl'],digest(archive.root/'window_index.jsonl'))
        self.assertEqual(len(list((archive.root/'events').glob('*/event.json'))),2)

    def test_live_retry_uses_a_new_attempt_without_resetting_capture(self):
        archive=self.archive();original=archive._export
        archive._export=lambda request: (_ for _ in ()).throw(IOError('first attempt'))
        archive.trigger(self.event(1,4*HZ));archive.poll(10*HZ)
        with self.assertRaises(IOError):archive.future.result()
        archive.poll(10*HZ)
        self.assertEqual(archive.status()['failed_count'],1)
        archive._export=original;archive.retry();archive.finish(10*HZ)
        self.assertEqual(archive.status()['saved_count'],1)
        self.assertEqual(archive.status()['failed_count'],0)
        self.assertTrue((archive.root/'events/event_0001_attempt_02/event.json').is_file())

    def test_total_limit_applies_after_previous_window_has_saved(self):
        archive=self.archive(max_pending=8,max_windows=1)
        archive.trigger(self.event(1,4*HZ));archive.poll(10*HZ);archive.future.result();archive.poll(10*HZ)
        self.assertEqual(archive.status()['pending_count'],0)
        archive.trigger(self.event(2,6*HZ));archive.finish(10*HZ)
        self.assertEqual(archive.status()['saved_count'],1)
        self.assertEqual(archive.status()['dropped_count'],1)

    def test_early_stop_clips_each_window_and_does_not_fabricate_post_data(self):
        archive=self.archive();archive.trigger(self.event(1,HZ//2));archive.trigger(self.event(2,9*HZ+HZ//2))
        archive.finish(10*HZ)
        windows=[json.loads(path.read_text()) for path in sorted((archive.root/'events').glob('*/event.json'))]
        self.assertTrue(windows[0]['pre_clipped']);self.assertTrue(windows[1]['post_clipped'])
        self.assertEqual(windows[1]['covered_end_ticks'],10*HZ)

    def test_invalid_capacity_and_mode_are_rejected_offline(self):
        for changes in ({'mode':'guess'},{'max_pending':0},{'max_pending':True},{'max_windows':1001}):
            profile=self.profile();profile['evidence'].update(changes)
            with self.assertRaises(ValueError):load_profile(profile)

    def test_protocol_preview_has_only_current_profile_fields(self):
        from uart_monitor.ui import launch
        with patch('IPython.display.display'),contextlib.redirect_stdout(io.StringIO()):
            ui=launch(ROOT)
            choose=ui['widgets']['profile'];options=dict(choose.options)
            for key,path in options.items():
                choose.value=path;ui['refresh']()
                payload=json.loads(ui['state']['viewer']['holder'].value.split('>',1)[1].rsplit('</pre>',1)[0].replace('&quot;','"').replace('&amp;','&').replace('&lt;','<').replace('&gt;','>'))
                names={f['name'] for f in payload['fields']}
                expected={f['name'] for f in load_profile(path)['fields']}
                self.assertEqual(names,expected)
            self.assertEqual(ui['widgets']['evidence_mode'].value,'continuous')
            ui['timer'].stop();ui['state']['viewer']['holder'].close();ui['state']['viewer']['panel'].close()


if __name__=='__main__':unittest.main()
