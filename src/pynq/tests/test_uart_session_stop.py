"""A slow post-stop drain must not extend the hardware acquisition timeline."""
import json
from pathlib import Path
import sys
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from car_telemetry import encode_frame
from uart_monitor.decoder import ByteChunk
from uart_monitor.profile import load_profile
from uart_monitor.session import MonitorSession
from uart_monitor_cli import verify_result


class DelayedDrain:
    hardware_accessed=False
    detection_source='fpga'
    def __init__(self,drain_frame):
        self.drain_frame=drain_frame;self.stopped=False;self.eof=False;self.read_once=False
        self.tick=0;self.consumed=0;self.offset=0;self.enabled=False
        self.provenance=dict(detection_source='fpga',timestamp_source='fake_unit_test_clock')
        self.data=encode_frame(dict(sequence=0,uptime_ms=0,imu_sample_count=0,pitch_mdeg=-1234,
            rate_mdps=5678,encoder_e1=-42,encoder_e2=42,pwm_a_counts=8,pwm_b_counts=12,
            flags=35,fault_code=0,tx_skipped=0,imu_age_ms=4))
    def now_ticks(self):return self.tick
    def registers(self):
        return dict(control=int(self.enabled),level=0,received=48,consumed=self.consumed,
                    overflows=0,framing_errors=0,event_overflows=0,parser_overflows=0,host_pending_events=0)
    def start(self):self.enabled=True;return 0
    def read(self,maximum=256):
        due=(self.stopped if self.drain_frame else not self.stopped) and not self.read_once
        self.eof=True
        if not self.stopped:self.tick=1000000
        data=self.data if due else b''
        ticks=[500000+n*1000 for n in range(48)] if due else []
        result=ByteChunk(data,ticks,self.offset,self.registers());result.hardware_events=[]
        if due:
            self.read_once=True;self.consumed=48;self.offset=48
            result.state=self.registers()
        return result
    def stop(self):
        self.enabled=False;self.stopped=True;self.stopped_ticks=2000000
        self.tick=100000000  # CPU/drain completes much later than UART disable.
    def close(self):pass


class StopTimelineTests(unittest.TestCase):
    def check_delayed_drain(self,drain_frame):
        p=load_profile(ROOT/'profiles/car_tlm1.json')
        dest=ROOT/'build/uart_stop_tests'/uuid.uuid4().hex
        result=MonitorSession(p,dest,1).run(DelayedDrain(drain_frame))
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual(result['end_ticks'],2000000)
        self.assertEqual(result['parser']['frames'],1)
        self.assertEqual(result['event_counts'],{})
        self.assertTrue(verify_result(dest)['logical_events_match'])
    def test_cleanup_clock_does_not_create_a_phantom_hardware_timeout(self):
        self.check_delayed_drain(False)
    def test_frame_drained_after_disable_keeps_original_time_and_stop_boundary(self):
        self.check_delayed_drain(True)


if __name__=='__main__':unittest.main()
