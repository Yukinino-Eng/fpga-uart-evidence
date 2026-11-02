"""Read-only evidence view, incremental boundaries, bounded storage and escaping."""
import ast
import base64
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
import uuid
import zlib
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from uart_monitor.viewer import RecordView,document,export_record,launch_view,notebook_payload


class ViewerTests(unittest.TestCase):
    def directory(self):
        path=ROOT/'build/uart_monitor_visualization/tests'/uuid.uuid4().hex
        path.mkdir(parents=True)
        return path

    def test_partial_line_is_not_lost_and_storage_is_bounded(self):
        path=self.directory();reader=RecordView(path,max_frames=3)
        first=json.dumps(dict(start_ticks=100,end_ticks=200,fields=dict(x=None),validity=dict(x=False)))
        file=path/'frames.jsonl';file.write_text(first[:15],encoding='utf-8')
        self.assertEqual(reader.update()['frames'],[])
        with file.open('a',encoding='utf-8') as stream:
            stream.write(first[15:]+'\n')
            for n in range(4):stream.write(json.dumps(dict(start_ticks=300+n,end_ticks=400+n,fields=dict(x=n),validity=dict(x=True)))+'\n')
        data=reader.update()
        self.assertEqual(data['view_frames_seen'],5)
        self.assertEqual(len(data['frames']),3)
        self.assertEqual(data['origin'],100)
        self.assertTrue(data['view_limited'])
        self.assertEqual(reader.update()['view_frames_seen'],5)

    def test_invalid_values_and_untrusted_labels_are_not_fabricated(self):
        path=self.directory()
        (path/'frames.jsonl').write_text(json.dumps(dict(start_ticks=1,end_ticks=2,fields={'</script><img>':None},validity={'</script><img>':False}))+'\n')
        data=RecordView(path).update();page=document(data)
        self.assertIsNone(data['frames'][0]['fields']['</script><img>'])
        self.assertNotIn('</script><img>',page)
        self.assertIn('\\u003c/script',page)

    def test_malformed_nonfinite_and_truncated_files_are_reported(self):
        path=self.directory();file=path/'frames.jsonl'
        file.write_text('{bad}\n{"x":NaN}\n')
        reader=RecordView(path);self.assertEqual(len(reader.update()['errors']),2)
        file.write_text('')
        with self.assertRaises(ValueError):reader.update()

    def test_real_fault_window_uses_saved_frames_and_clipping_flags(self):
        path=ROOT/'build/ego1_lab_source/live/20261030_link_02/board_records/ego1_overlimit_115200_20261030_01'
        if not path.is_dir():self.skipTest('Local physical acceptance record is not present')
        reader=RecordView(path);data=reader.update()
        while data['catching_up']:data=reader.update()
        target=next(e for e in data['events'] if e['rule_id']=='temperature_limit')
        window=data['windows'][str(target['event_id'])]
        self.assertFalse(window['manifest']['pre_clipped'])
        self.assertFalse(window['manifest']['post_clipped'])
        self.assertTrue(any(f['fields']['temperature_mdeg']==70 for f in window['frames']))
        self.assertLess(len(window['frames']),len(data['frames']))
        before=dict(reader.window_cache);reader.update();self.assertEqual(before,reader.window_cache)

    def test_notebook_view_is_hardware_free_and_can_refresh(self):
        path=self.directory()
        with patch('IPython.display.display'),contextlib.redirect_stdout(io.StringIO()):
            view=launch_view(path)
        self.assertIn('iframe',view['panel'].value)
        data=view['refresh'](live=True)
        self.assertTrue(data['live'])
        self.assertIn('&quot;live&quot;:true',view['holder'].value)
        view['holder'].close();view['panel'].close()

    def test_runtime_sources_parse_on_python36(self):
        for name in ['viewer.py','ui.py']:
            ast.parse((ROOT/'scripts/uart_monitor'/name).read_text(encoding='utf-8'),feature_version=(3,6))

    def test_embedded_view_uses_widget_children_without_output_capture(self):
        from uart_monitor.ui import launch
        with patch('IPython.display.display') as show,contextlib.redirect_stdout(io.StringIO()):
            view=launch_view(None,{},display_view=False)
            self.assertFalse(show.called)
            self.assertEqual(view['container'].children,(view['holder'],view['panel']))
            ui=launch(ROOT)
            live=ui['state']['viewer']
            self.assertIn(live['container'],show.call_args[0][0].children[-3].children)
        ui['timer'].stop()
        for item in (view,live):
            for name in ('holder','panel','container'):item[name].close()

    def test_full_notebook_snapshot_is_lossless_and_bounded_in_wire_size(self):
        frame=dict(start_ticks=123456789012,end_ticks=123456789212,
                   fields={'角度':1.234,'missing':None},raw_fields={'角度':1234,'missing':None},
                   validity={'角度':True,'missing':False})
        data=dict(frames=[frame]*2000,events=[{'rule_id':'角度越限'}],windows={})
        encoded=notebook_payload(data)
        self.assertTrue(encoded.startswith('URX-ZLIB1:'))
        self.assertEqual(json.loads(zlib.decompress(base64.b64decode(encoded[10:]))),data)
        self.assertLess(len(encoded),len(json.dumps(data,ensure_ascii=False))/5)
        data['frames'][0]['fields']['角度']=float('nan')
        with self.assertRaises(ValueError):notebook_payload(data)

    def test_main_notebook_can_open_a_record_without_hardware(self):
        from uart_monitor.ui import launch
        record=ROOT/'build/ego1_lab_source/live/20261030_link_02/board_records/ego1_overlimit_115200_20261030_01'
        if not record.is_dir():self.skipTest('Local physical acceptance record is not present')
        with patch('IPython.display.display'),contextlib.redirect_stdout(io.StringIO()):
            ui=launch(ROOT)
            ui['widgets']['records'].options=[('physical overlimit',str(record))]
            ui['widgets']['records'].value=str(record)
            ui['refresh']()
            ui['widgets']['inspect'].click()
            ui['refresh']()
        self.assertEqual(ui['state']['viewer']['reader'].root,record.resolve())
        self.assertIn('iframe',ui['state']['viewer']['panel'].value)
        ui['timer'].stop()
        ui['state']['viewer']['holder'].close();ui['state']['viewer']['panel'].close()

if __name__=='__main__':unittest.main()
