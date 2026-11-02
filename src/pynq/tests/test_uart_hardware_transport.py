"""Driver contract using a fake MMIO; never imports a real board SDK."""
from pathlib import Path
import shutil
import sys
import types
import unittest
import uuid
from unittest.mock import patch
import hashlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from uart_monitor.urx2 import URX2Transport,URX2RawTransport,KNOWN_URX2_SHAS,BOOT_BASE_SHA,STARTUP2_PAIR
from uart_monitor.hardware import ID


class FakeMMIO:
    def __init__(self):
        self.reg={0xfc:ID,0x30:0x20000,0x34:0x1ff,0x20:100000000,0x28:4096,0x1a4:64,0:0,0x24:115200}
        self.raw=[];self.events=[];self.snapshot=[0]*24;self.last_time=0
    def read(self,offset):
        if offset==12:return len(self.raw)
        if offset==0x100:return len(self.events)
        if offset==8:
            b,self.last_time=self.raw.pop(0);self.reg[20]=self.reg.get(20,0)+1
            return 0x80000000|b
        if offset==0x38:return self.last_time&0xffffffff
        if offset==0x3c:return self.last_time>>32
        if offset==0x108:
            if not self.events:return 0
            self.snapshot=self.events.pop(0);return 0x80000000
        if 0x110<=offset<0x170:return self.snapshot[(offset-0x110)//4]
        return self.reg.get(offset,0)
    def write(self,offset,value):
        if offset==0 and value==2:
            self.raw=[];self.events=[];self.reg.update({0:0,16:0,20:0,0x104:0})
        elif offset==0x1f0:self.reg[offset]=3
        else:self.reg[offset]=value
        if offset==0 and value==1:self.reg[0x180]=123;self.reg[0x184]=0


class HardwareTransportTests(unittest.TestCase):
    def make(self,mmio,raw_mode=False,clock_mhz=100):
        path=ROOT/'build/urx2_transport_tests'/uuid.uuid4().hex;path.mkdir(parents=True)
        bit=path/'uart_detector2.bit';bit.write_bytes(b'MOCK_ONLY_NOT_A_BITSTREAM')
        shutil.copyfile(ROOT/'tests/fixtures/mock_urx2_hwh.xml',bit.with_suffix('.hwh'))
        module=types.SimpleNamespace(MMIO=lambda *a:mmio,Clocks=types.SimpleNamespace(fclk0_mhz=clock_mhz),
                                     PL=types.SimpleNamespace(bitfile_name=str(bit)),Bitstream=None)
        with patch.dict(sys.modules,{'pynq':module}):
            return URX2RawTransport(bit,ROOT/'profiles/lab_ascii_v1.json') if raw_mode else URX2Transport(bit,ROOT/'profiles/car_tlm1.json')
    def test_configure_before_enable_and_hardware_arm_timestamp(self):
        mmio=FakeMMIO();transport=self.make(mmio)
        self.assertEqual(transport.start(),123)
        self.assertEqual(mmio.reg[0x1000],48);self.assertEqual(mmio.reg[0x1f0],3)
        self.assertEqual(mmio.reg[0],1)
        with self.assertRaisesRegex(RuntimeError,'Preserve'):transport.start()
        transport.stop();self.assertEqual(mmio.reg[0],0)
    def test_events_wait_until_corresponding_raw_bytes_have_been_read(self):
        mmio=FakeMMIO();transport=self.make(mmio);transport.start()
        mmio.raw=[(n,(1<<32)+n*8680) for n in range(96)]
        def event(batch,end):
            w=[0]*24;w[0]=1;w[1]=batch;w[2]=end*8680;w[3]=1;w[4]=end-48;w[5]=end;w[12]=1
            return w
        mmio.events=[event(1,48),event(2,96)]
        first=transport.read(16);self.assertEqual(first.hardware_events,[])
        second=transport.read(32);self.assertEqual([r['batch_id'] for r in second.hardware_events],[1])
        self.assertGreater(second.ticks[-1],1<<32)
        third=transport.read(48);self.assertEqual([r['batch_id'] for r in third.hardware_events],[2])
        self.assertEqual(transport.registers()['host_pending_events'],0)
        self.assertEqual(len(transport.read().hardware_events),0)
    def test_incompatible_identity_rejected(self):
        mmio=FakeMMIO();mmio.reg[0xfc]=0x31585255
        with self.assertRaisesRegex(RuntimeError,'ID/ABI'):self.make(mmio)
    def test_same_bit_can_use_text_profile_with_detector_bypassed(self):
        mmio=FakeMMIO();transport=self.make(mmio,raw_mode=True);transport.start()
        self.assertEqual(transport.detection_source,'software')
        self.assertEqual(mmio.reg[0x1f4],0)
        self.assertNotIn(0x1000,mmio.reg)
        self.assertIsNone(transport.compiled)
    def test_faster_than_constrained_clock_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'100MHz'):self.make(FakeMMIO(),clock_mhz=100.5)

    def test_background_sync_keeps_same_baud_start_immediate(self):
        mmio=FakeMMIO();mmio.reg[0x34]=0x3ff
        transport=self.make(mmio)
        with patch('uart_monitor.urx2.time.sleep') as sleep:
            transport.start()
        sleep.assert_not_called()
        self.assertEqual(transport.provenance['uart_sync_policy'],'free_running_capture_gate')

    def test_baud_change_settles_before_capture_is_enabled(self):
        mmio=FakeMMIO();mmio.reg[0x34]=0x3ff
        transport=self.make(mmio);transport.baud=9600
        observations=[]
        def settle(seconds):
            observations.append((seconds,mmio.reg[0],mmio.reg[0x24],mmio.reg[0x1f0]))
        with patch('uart_monitor.urx2.time.sleep',side_effect=settle):
            transport.start()
        self.assertEqual(len(observations),1)
        self.assertAlmostEqual(observations[0][0],2*50*10/9600)
        self.assertEqual(observations[0][1:],(0,9600,3))
        self.assertEqual(mmio.reg[0],1)

    def test_legacy_firmware_remains_supported_without_new_sync_claim(self):
        mmio=FakeMMIO();transport=self.make(mmio);transport.baud=9600
        with patch('uart_monitor.urx2.time.sleep') as sleep:
            transport.start()
        sleep.assert_not_called()
        self.assertEqual(transport.provenance['uart_sync_policy'],'legacy_reset_on_capture')

    def upgrade(self,mmio):
        folder=ROOT/'build/urx2_transport_tests'/uuid.uuid4().hex;folder.mkdir(parents=True)
        old=folder/'previous.bit';old.write_bytes(b'PREVIOUS_MOCK')
        new=folder/'updated.bit';new.write_bytes(b'UPDATED_MOCK')
        shutil.copyfile(ROOT/'tests/fixtures/mock_urx2_hwh.xml',new.with_suffix('.hwh'))
        downloaded=[]
        module=types.SimpleNamespace(MMIO=lambda *a:mmio,Clocks=types.SimpleNamespace(fclk0_mhz=100),
            PL=types.SimpleNamespace(bitfile_name=str(old)),
            Bitstream=lambda path:types.SimpleNamespace(download=lambda:downloaded.append(path)))
        def known_digest(path):
            return next(iter(KNOWN_URX2_SHAS)) if Path(path)==old else hashlib.sha256(Path(path).read_bytes()).hexdigest()
        with patch.dict(sys.modules,{'pynq':module}),patch('uart_monitor.urx2.digest',side_effect=known_digest):
            transport=URX2Transport(new,ROOT/'profiles/car_tlm1.json',program=True)
        return transport,downloaded

    def test_known_urx2_upgrade_checks_identity_and_preserves_pending_data(self):
        for condition in ('running','raw','events','detector','wrong_identity'):
            mmio=FakeMMIO()
            if condition=='running':mmio.reg[0]=1
            elif condition=='raw':mmio.raw=[(0,1)]
            elif condition=='events':mmio.events=[[0]*24]
            elif condition=='detector':mmio.reg[0x190]=256
            else:mmio.reg[0xfc]=0x31585255
            with self.subTest(condition=condition),self.assertRaises(RuntimeError):self.upgrade(mmio)

    def test_known_idle_urx2_can_upgrade_to_a_new_image(self):
        transport,downloaded=self.upgrade(FakeMMIO())
        self.assertEqual(len(downloaded),1)
        self.assertTrue(transport.provenance['reprogrammed'])

    def boot_recovery(self,allow=True,program=True,bad_pair=False,unknown_base=False,bad_path=False):
        folder=ROOT/'build/urx2_transport_tests'/uuid.uuid4().hex
        old=folder/('other/base.bit' if bad_path else 'pynq/overlays/base/base.bit')
        old.parent.mkdir(parents=True);old.write_bytes(b'BOOT_MOCK')
        bit=folder/'uart_detector2.bit';bit.write_bytes(b'TARGET_MOCK')
        shutil.copyfile(ROOT/'tests/fixtures/mock_urx2_hwh.xml',bit.with_suffix('.hwh'))
        downloaded=[]
        mmio=FakeMMIO()
        module=types.SimpleNamespace(MMIO=lambda *a:mmio,Clocks=types.SimpleNamespace(fclk0_mhz=100),
            PL=types.SimpleNamespace(bitfile_name=str(old)),
            Bitstream=lambda path:types.SimpleNamespace(download=lambda:downloaded.append(path)))
        def mock_digest(path):
            path=Path(path)
            if path==old:return 'UNKNOWN_BASE' if unknown_base else BOOT_BASE_SHA
            if path==bit:return STARTUP2_PAIR[0]
            if path==bit.with_suffix('.hwh'):return 'TAMPERED_HWH' if bad_pair else STARTUP2_PAIR[1]
            return hashlib.sha256(path.read_bytes()).hexdigest()
        with patch.dict(sys.modules,{'pynq':module}),patch('uart_monitor.urx2.digest',side_effect=mock_digest):
            receiver=URX2Transport(bit,ROOT/'profiles/car_tlm1.json',program=program,allow_boot_recovery=allow)
        self.assertEqual(len(downloaded),1)
        return receiver

    def test_explicit_recovery_accepts_only_verified_system_boot_and_firmware_pair(self):
        receiver=self.boot_recovery()
        self.assertTrue(receiver.provenance['verified_boot_recovery'])
        for condition in ({'allow':False},{'program':False},{'bad_pair':True},{'unknown_base':True},{'bad_path':True}):
            with self.subTest(condition=condition),self.assertRaises(RuntimeError):self.boot_recovery(**condition)


if __name__=='__main__':unittest.main()
