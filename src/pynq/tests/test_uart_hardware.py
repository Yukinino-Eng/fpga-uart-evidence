"""URX2 config compiler, source attribution, integer boundaries and UI compatibility."""
import contextlib
import copy
import io
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from uart_monitor.hardware import compile_profile,adapt_event,RULE_BASE
from uart_monitor.urx2 import URX2Transport,HardwareRuleEngine


class HardwareCompilerTests(unittest.TestCase):
    def profile(self):return json.loads((ROOT/'profiles/car_tlm1.json').read_text(encoding='utf-8'))
    def test_car_compiles_all_fields_four_rules_and_crc32(self):
        compiled=compile_profile(self.profile());cfg=compiled['words']
        self.assertEqual(len(cfg),284);self.assertEqual(cfg[0],48);self.assertEqual(cfg[3],4)
        self.assertEqual(cfg[14],13);self.assertEqual(cfg[15],15)
        self.assertTrue(all(0<=v<=0xffffffff for v in cfg))
    def test_unsupported_profiles_rejected_before_pynq_import(self):
        text=ROOT/'profiles/lab_ascii_v1.json'
        with self.assertRaisesRegex(ValueError,'fixed binary'):URX2Transport('missing.bit',text)
        for change in ('float','too_many','negative_scale','behavior'):
            p=self.profile()
            if change=='float':p['fields'][3]['type']='float32'
            elif change=='too_many':p['rules']=[dict(p['rules'][0],id='rule%d'%n) for n in range(9)]
            elif change=='negative_scale':p['fields'][3]['scale']=-.001
            else:p['analysis']={}
            with self.assertRaises((ValueError,KeyError)):compile_profile(p)
    def test_float_boundary_thresholds_match_existing_software_conversion(self):
        p=self.profile();p['fields'][3]['scale']=.1
        p['rules']=[dict(id='boundary',kind='compare',field='pitch_mdeg',op='gt',value=.3,duration_ms=0)]
        compiled=compile_profile(p);threshold=compiled['words'][RULE_BASE+1]
        # 3 * .1 is greater than .3 in the existing PS conversion.
        self.assertEqual(threshold,2)
        for op in ('lt','le','gt','ge'):
            p['rules'][0]['op']=op;cfg=compile_profile(p)['words'];raw=cfg[RULE_BASE+1]
            if raw&0x80000000:raw-=1<<32
            operation={'lt':lambda a,b:a<b,'le':lambda a,b:a<=b,'gt':lambda a,b:a>b,'ge':lambda a,b:a>=b}[op]
            for n in range(-10,11):self.assertEqual(operation(n,raw),operation(n*.1,.3),(op,n,raw))
    def test_simultaneous_bitmap_becomes_eight_distinct_events(self):
        p=self.profile();p['rules']=[dict(id='lane%d'%n,kind='compare',field='fault_code',op='gt',value=n,duration_ms=0) for n in range(8)]
        compiled=compile_profile(p);record=dict(mask=255,batch_id=3,ticks=123,raw_start=0,raw_end=48,values=[20]*8)
        events=adapt_event(record,compiled,100)
        self.assertEqual(len(events),8);self.assertEqual([e['event_id'] for e in events],list(range(100,108)))
        self.assertEqual({e['trigger_ticks'] for e in events},{123})
        self.assertEqual({e['hardware_batch_id'] for e in events},{3})
        self.assertTrue(all(e['source']=='fpga' for e in events))
    def test_hardware_bridge_does_not_duplicate_software_covered_events(self):
        p=compile_profile(self.profile())['profile'];engine=HardwareRuleEngine(p,0)
        record=dict(mask=512,batch_id=1,ticks=123,raw_start=0,raw_end=48,values=[0]*8)
        issues=[dict(kind='crc_errors',ticks=123),dict(kind='interframe_noise',ticks=124)]
        events=engine.update_hardware([],issues,[record],124,{})
        self.assertEqual([e['rule_id'] for e in events],['protocol:crc_errors','protocol:interframe_noise'])
        self.assertEqual([e['source'] for e in events],['fpga','software'])
    def test_ui_can_reject_text_hardware_choice_without_board(self):
        from uart_monitor.ui import launch
        with patch('IPython.display.display'),contextlib.redirect_stdout(io.StringIO()):
            ui=launch(ROOT)
            ui['widgets']['profile'].value=str(ROOT/'profiles/lab_ascii_v1.json')
            ui['widgets']['detector'].value='fpga'
            button=ui['widgets']['check']
            # Old board ipywidgets exposes the registered callback dispatcher only.
            if hasattr(button,'click'):button.click()
            else:button._click_handlers(button)
            self.assertIn('配置错误',ui['widgets']['status'].value)
            ui['timer'].stop();ui['state']['viewer']['holder'].close();ui['state']['viewer']['panel'].close()


if __name__=='__main__':unittest.main()
