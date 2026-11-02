"""Receive ownership, blocked consumer, boundary drain and fail-closed capacity."""
from pathlib import Path
import sys
import threading
import time
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uart_monitor.buffered import BufferedTransport
from uart_monitor.decoder import ByteChunk


class Source:
    hardware_accessed = True
    detection_source = 'fpga'
    provenance = {'receive_only': True}

    def __init__(self, payload=b'abcdef', fail=False):
        self.payload = payload
        self.offset = 0
        self.running = False
        self.stopped_ticks = None
        self.drained = threading.Event()
        self.fail = fail
        self.readers = set()

    def start(self):
        self.running = True
        return 100

    def now_ticks(self):
        return 100 + self.offset

    def registers(self):
        return dict(control=int(self.running), level=0, received=self.offset,
                    consumed=self.offset, overflows=0, framing_errors=0)

    def read(self):
        self.readers.add(threading.current_thread().name)
        if self.fail and self.running:
            raise IOError('Injected hardware read failure')
        offset = self.offset
        data = self.payload[offset:offset+1]
        self.offset += len(data)
        if self.offset == len(self.payload):
            self.drained.set()
        chunk = ByteChunk(data, [100+offset] if data else [], offset, self.registers())
        chunk.hardware_events = [{'raw_end': self.offset}] if data else []
        return chunk

    def stop(self):
        self.running = False
        self.stopped_ticks = self.now_ticks()

    def close(self):
        pass


class BufferedTests(unittest.TestCase):
    def test_session_preserves_queued_frames_when_storage_outlasts_capture(self):
        from car_telemetry import encode_frame
        from uart_monitor.archive import Archive
        from uart_monitor.profile import load_profile
        from uart_monitor.session import MonitorSession
        from uart_monitor_cli import verify_result
        class Frames(Source):
            supports_buffered_capture = True
            detection_source = 'software'
            def read(self):
                self.readers.add(threading.current_thread().name)
                offset = self.offset
                data = self.payload[offset:offset+48]
                self.offset += len(data)
                if self.offset == len(self.payload):
                    self.drained.set()
                return ByteChunk(data, list(range(100+offset,100+self.offset)), offset, self.registers())
        payload = b''.join(encode_frame(dict(sequence=n,uptime_ms=n*20,imu_sample_count=n,
            pitch_mdeg=0,rate_mdps=0,encoder_e1=0,encoder_e2=0,pwm_a_counts=0,pwm_b_counts=0,
            flags=35,fault_code=0,tx_skipped=0,imu_age_ms=4)) for n in range(10))
        source = Frames(payload)
        original = Archive.append
        blocked = []
        def slow_append(archive, chunk, frames, issues):
            if not blocked:
                blocked.append(True)
                self.assertTrue(source.drained.wait(1))
                time.sleep(.08)
            return original(archive, chunk, frames, issues)
        root = Path(__file__).resolve().parents[1]
        output = root/'build/uart_buffered_tests'/uuid.uuid4().hex
        with patch.object(Archive, 'append', slow_append):
            report = MonitorSession(load_profile(root/'profiles/car_tlm1.json'), output, .05).run(source)
        self.assertEqual(report['status'], 'COMPLETED')
        self.assertEqual(report['capture_integrity'], 'PASS')
        self.assertEqual(report['parser']['frames'], 10)
        self.assertEqual((output/'raw.bin').read_bytes(), payload)
        self.assertEqual(report['end_ticks'], 100+len(payload))
        self.assertEqual(source.readers, {'URX-receive'})
        self.assertTrue(verify_result(output)['logical_events_match'])

    def test_reader_runs_while_consumer_is_blocked_and_keeps_observation_time(self):
        source = Source()
        transport = BufferedTransport(source, 5, capacity=32)
        self.assertEqual(transport.start(), 100)
        try:
            # Deliberately do not call read: represents blocked disk/UI work.
            self.assertTrue(source.drained.wait(1))
            first = transport.read()
            self.assertEqual(first.data, source.payload)
            self.assertEqual(first.raw_offset, 0)
            self.assertEqual(transport.now_ticks(), 106)
            self.assertEqual(first.hardware_events, [{'raw_end': n} for n in range(1,7)])
            transport.stop()
            chunks = [first]
            while True:
                chunk = transport.read()
                if transport.eof:
                    break
                chunks.append(chunk)
            self.assertEqual(b''.join(c.data for c in chunks), source.payload)
            self.assertEqual(transport.stopped_ticks, 106)
            self.assertEqual(transport.registers()['control'], 0)
            self.assertEqual(source.readers, {'URX-receive'})
        finally:
            transport.close()

    def test_full_buffer_stops_and_preserves_bytes_before_reporting_failure(self):
        source = Source(b'a'*520)
        transport = BufferedTransport(source, 5, capacity=1)
        transport.start()
        self.assertTrue(transport.done.wait(1))
        chunks = []
        with self.assertRaisesRegex(RuntimeError, 'buffer full'):
            while True:
                chunks.append(transport.read())
        self.assertEqual(b''.join(c.data for c in chunks), source.payload)
        self.assertEqual(transport.registers()['control'], 0)
        self.assertLessEqual(transport.high_water, 1)
        transport.close()

    def test_tiny_fragments_do_not_exhaust_capacity_and_keep_exact_byte_timestamps(self):
        source = Source(bytes(range(256))*20)
        transport = BufferedTransport(source, 5, capacity=32)
        transport.start()
        self.assertTrue(source.drained.wait(1))
        transport.stop()
        chunks = []
        while True:
            chunk = transport.read()
            if transport.eof:
                break
            if chunk.data:
                chunks.append(chunk)
        self.assertEqual(b''.join(chunk.data for chunk in chunks), source.payload)
        self.assertEqual([tick for chunk in chunks for tick in chunk.ticks], list(range(100,5220)))
        self.assertTrue(all(len(chunk.data)<=256 for chunk in chunks))
        self.assertEqual(len(chunks), 20)
        self.assertEqual(transport.high_water, 20)
        self.assertIsNone(transport.error)
        transport.close()

    def test_hardware_exception_is_propagated_and_receiver_stops(self):
        transport = BufferedTransport(Source(fail=True), 5)
        transport.start()
        self.assertTrue(transport.done.wait(1))
        chunks = []
        with self.assertRaisesRegex(RuntimeError, 'Injected hardware read failure'):
            while True:
                chunks.append(transport.read())
        self.assertEqual(b''.join(c.data for c in chunks), transport.transport.payload)
        self.assertEqual(transport.registers()['control'], 0)
        transport.close()

    def test_deadline_stops_receiver_even_without_a_consumer(self):
        transport = BufferedTransport(Source(), .03, capacity=32)
        transport.start()
        self.assertTrue(transport.done.wait(1))
        self.assertIsNotNone(transport.stopped_ticks)
        self.assertEqual(transport.registers()['control'], 0)
        transport.close()

    def test_capacity_must_be_positive(self):
        with self.assertRaises(ValueError):
            BufferedTransport(Source(), 5, capacity=0)


if __name__ == '__main__':
    unittest.main()
