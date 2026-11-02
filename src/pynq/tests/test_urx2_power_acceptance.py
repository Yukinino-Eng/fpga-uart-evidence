"""Recovery acceptance must detect missing IP, file loss, and missing reboot evidence."""
import json
from pathlib import Path
import sys
import types
import unittest
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import urx2_power_acceptance as power
from uart_monitor.urx2 import STARTUP2_PAIR


class PowerAcceptanceTests(unittest.TestCase):
    def fixture(self):
        root=ROOT/'build/power_acceptance_tests'/uuid.uuid4().hex
        (root/'scripts').mkdir(parents=True)
        (root/'scripts/driver.py').write_text('x = 1\n')
        (root/'notebooks').mkdir()
        notebook=dict(cells=[dict(cell_type='code',source=['x = 1\n'],outputs=[])])
        (root/'notebooks/test.ipynb').write_text(json.dumps(notebook))
        return root

    def test_snapshot_detects_changed_or_missing_files(self):
        root=self.fixture();before=dict(snapshot=power.snapshot(root))
        self.assertEqual(power.check_snapshot(root,before),1)
        (root/'scripts/driver.py').write_text('x = 2\n')
        with self.assertRaisesRegex(RuntimeError,'driver.py'):power.check_snapshot(root,before)
        (root/'scripts/driver.py').unlink()
        with self.assertRaisesRegex(RuntimeError,'driver.py'):power.check_snapshot(root,before)

    def test_notebook_outputs_can_change_but_source_cannot(self):
        root=self.fixture();before=dict(snapshot=power.snapshot(root))
        path=root/'notebooks/test.ipynb';notebook=json.loads(path.read_text())
        notebook['cells'][0]['outputs']=[{'text':'new display output'}]
        path.write_text(json.dumps(notebook));power.check_snapshot(root,before)
        notebook['cells'][0]['source']=['x = 2\n'];path.write_text(json.dumps(notebook))
        with self.assertRaisesRegex(RuntimeError,'test.ipynb'):power.check_snapshot(root,before)

    def test_missing_persistent_address_fails_before_any_repair(self):
        with patch.object(power,'command',return_value='2: eth0 inet 192.168.2.99/24') as command:
            with self.assertRaisesRegex(RuntimeError,'Persistent IP absent'):power.network('169.254.135.99',16)
            command.assert_called_once_with('ip','-o','-4','addr','show','dev','eth0')

    def test_same_boot_is_not_a_power_cycle(self):
        root=self.fixture();directory=root/'validation/test';directory.mkdir(parents=True)
        (directory/'before.json').write_text(json.dumps(dict(status='READY_FOR_ORDERLY_SHUTDOWN',boot_id='same',root=str(root))))
        args=types.SimpleNamespace(root=root,phase='after',address='169.254.135.99',prefix=16,port=9090)
        def mock_digest(path):return STARTUP2_PAIR[1] if str(path).endswith('.hwh') else STARTUP2_PAIR[0]
        with patch.dict(sys.modules,{'pynq':types.SimpleNamespace(PL=types.SimpleNamespace())}), \
             patch.object(power,'boot_id',return_value='same'),patch.object(power,'digest',side_effect=mock_digest):
            with self.assertRaisesRegex(RuntimeError,'No reboot observed'):power.execute(args,directory)

    def test_failure_receipts_do_not_overwrite_the_original(self):
        root=self.fixture();directory=root/'validation/test';directory.mkdir(parents=True)
        with patch('builtins.print'),patch.object(power.os,'sync',create=True):
            power.save_receipt(directory,'after_failed',dict(status='FAIL',error='original'))
            power.save_receipt(directory,'after_failed',dict(status='FAIL',error='retry'))
        self.assertEqual(json.loads((directory/'after_failed.json').read_text())['error'],'original')
        self.assertEqual(len(list(directory.glob('after_failed*.json'))),2)

    def test_limited_observation_also_requires_an_actual_changed_boot_id(self):
        root=self.fixture();directory=root/'validation/test';directory.mkdir(parents=True)
        args=types.SimpleNamespace(root=root,phase='observe',previous_boot_id='same',
                                  address='169.254.135.99',prefix=16,port=9090)
        def mock_digest(path):return STARTUP2_PAIR[1] if str(path).endswith('.hwh') else STARTUP2_PAIR[0]
        with patch.dict(sys.modules,{'pynq':types.SimpleNamespace(PL=types.SimpleNamespace())}), \
             patch.object(power,'boot_id',return_value='same'),patch.object(power,'digest',side_effect=mock_digest):
            with self.assertRaisesRegex(RuntimeError,'previously recorded boot ID'):power.execute(args,directory)

    def test_missing_baseline_does_not_silently_pass_the_full_after_stage(self):
        root=self.fixture();directory=root/'validation/test';directory.mkdir(parents=True)
        args=types.SimpleNamespace(root=root,phase='after',address='169.254.135.99',prefix=16,port=9090)
        def mock_digest(path):return STARTUP2_PAIR[1] if str(path).endswith('.hwh') else STARTUP2_PAIR[0]
        with patch.dict(sys.modules,{'pynq':types.SimpleNamespace(PL=types.SimpleNamespace())}), \
             patch.object(power,'boot_id',return_value='new'),patch.object(power,'digest',side_effect=mock_digest):
            with self.assertRaisesRegex(RuntimeError,'Before receipt missing'):power.execute(args,directory)


if __name__=='__main__':unittest.main()
