"""Behavior tests use independent nominal, fault and near-threshold sequences."""
import copy
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import struct
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from car_telemetry import encode_frame
from uart_behavior import read_frames, select_frames, main as behavior_cli
from uart_monitor.behavior import BehaviorEngine, feature_value, fit_baseline
from uart_monitor.profile import load_profile, checksum
from uart_monitor.decoder import Decoder, ByteChunk
from uart_monitor.rules import HZ, RuleEngine
from uart_monitor.session import MonitorSession
from uart_monitor.transport import ReplayTransport
from uart_monitor_cli import verify_result


def frame(index, pitch=0, rate=0, active=True, counter=None, valid=True):
    flags = 35 | (4 if active else 0)
    if not valid:
        flags &= ~3
    fields = dict(sequence=index, uptime_ms=index * 20, imu_sample_count=index * 2 if counter is None else counter,
                  pitch_mdeg=pitch if valid else None, rate_mdps=rate if valid else None,
                  encoder_e1=0, encoder_e2=0, pwm_a_counts=0, pwm_b_counts=0,
                  flags=flags, fault_code=0, tx_skipped=0, imu_age_ms=4)
    raw = dict(fields)
    raw['pitch_mdeg'] = int(pitch * 1000) if valid else -2147483648
    raw['rate_mdps'] = int(rate * 1000) if valid else -2147483648
    validity = {k: True for k in fields}
    validity['pitch_mdeg'] = validity['rate_mdps'] = valid
    return dict(fields=fields, raw_fields=raw, validity=validity, start_ticks=index * HZ // 50,
                end_ticks=index * HZ // 50, raw_start=index * 48, raw_end=(index + 1) * 48,
                sequence=index, device_time=index * 20)


class BehaviorTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(ROOT / 'profiles/car_tlm1.json')
        self.profile['analysis'] = json.loads((ROOT / 'profiles/analysis/car_behavior_v1.json').read_text(encoding='utf-8'))
        self.profile = load_profile(self.profile)

    def trained(self):
        return fit_baseline(self.profile, (frame(i, pitch=.02 * (i % 3 - 1), rate=.1 * (i % 5 - 2))
                                           for i in range(400)), dict(source='independent_test_nominal'))

    def events(self, profile, frames):
        engine = RuleEngine(profile, frames[0]['end_ticks'])
        events = []
        for item in frames:
            events.extend(engine.update([item], [], item['end_ticks']))
        return engine, events

    def test_freshness_without_reported_fault_and_recovers(self):
        frames = [frame(i, counter=7) for i in range(11)]
        engine, events = self.events(self.profile, frames)
        self.assertEqual([e['rule_id'] for e in events], ['behavior:freshness:imu_progress'])
        self.assertEqual(events[0]['trigger_ticks'], HZ // 10)
        self.assertEqual(events[0]['evidence']['stale_ms'], 100)
        self.assertFalse(engine.recovered())
        engine.update([frame(11, counter=8)], [], 11 * HZ // 50)
        self.assertTrue(engine.recovered())
        self.assertEqual(engine.behavior_status()['baseline_assessment'], 'UNKNOWN')

    def test_unsigned_counter_wrap_is_progress(self):
        frames = [frame(i, counter=((1 << 32) - 6 + i * 2) % (1 << 32)) for i in range(20)]
        _, events = self.events(self.profile, frames)
        self.assertFalse(events)

    def test_same_analysis_core_accepts_text_protocol_by_config_only(self):
        profile = load_profile(ROOT / 'profiles/lab_ascii_v1.json')
        profile['analysis'] = json.loads((ROOT / 'profiles/analysis/lab_behavior_v1.json').read_text(encoding='utf-8'))
        profile = load_profile(profile)
        decoder = Decoder(profile); frames = []; offset = 0
        for i in range(200):
            # 35 C stays below the existing 60 C limit; only learned behavior triggers.
            body = ('@LAB,%d,%d,%d,3300,0' % (i, i * 100, 25000 if i < 150 else 35000)).encode('ascii')
            raw = body + ('*%02X\r\n' % checksum(body[1:], 'xor8')).encode('ascii')
            decoded, issues = decoder.feed(ByteChunk(raw, [i * HZ // 10] * len(raw), offset))
            self.assertFalse(issues); frames.extend(decoded); offset += len(raw)
        trained = fit_baseline(profile, frames[:100], dict(source='synthetic_text_nominal'))
        _, events = self.events(trained, frames[100:])
        self.assertEqual([e['rule_id'] for e in events], ['behavior:baseline:normal:temperature_level'])

    def test_invalid_mode_and_protocol_break_restart_freshness(self):
        engine, events = self.events(self.profile, [frame(i, counter=5) for i in range(4)])
        engine.update([frame(4, counter=5, valid=False)], [], 4 * HZ // 50)
        for i in range(5, 10):
            self.assertFalse(engine.update([frame(i, counter=5)], [], i * HZ // 50))
        hit = engine.update([frame(10, counter=5)], [], HZ // 5)
        self.assertEqual(hit[0]['rule_id'], 'behavior:freshness:imu_progress')
        engine = RuleEngine(self.profile)
        for i in range(8):
            item = frame(i, counter=5, active=i >= 3)
            self.assertFalse(engine.update([item], [], item['end_ticks']))
        self.assertTrue(engine.update([frame(8, counter=5)], [], 8 * HZ // 50))
        engine = RuleEngine(self.profile)
        for i in range(9):
            issues = [dict(kind='crc_errors', ticks=i * HZ // 50)] if i == 4 else []
            events = engine.update([frame(i, counter=5)], issues, i * HZ // 50)
            self.assertFalse(any(e['rule_id'].startswith('behavior:') for e in events))
        self.assertTrue(any(e['rule_id'].startswith('behavior:') for e in engine.update([frame(9, counter=5)], [], 9 * HZ // 50)))

    def test_local_loss_and_time_restart_do_not_accumulate_fault_time(self):
        engine = RuleEngine(self.profile)
        for i in range(20):
            self.assertFalse(engine.update([frame(i, counter=0)], [], i * HZ // 50, local_ok=False))
        self.assertFalse(engine.recovered())
        for i in range(20, 25):
            self.assertFalse(engine.update([frame(i, counter=0)], [], i * HZ // 50))
        self.assertFalse(engine.update([frame(1, counter=0)], [], HZ // 50))
        self.assertFalse(engine.update([frame(2, counter=0)], [], 2 * HZ // 50))

    def test_robust_statistics_and_single_spike_do_not_trigger(self):
        self.assertEqual(feature_value([1, 2, 3, 4, 100], 'median'), 3)
        self.assertEqual(feature_value([1, 2, 3, 4, 100], 'mad'), 1)
        self.assertEqual(feature_value([1, 2, 3, 4, 100], 'iqr'), 2)
        profile = self.trained()
        frames = [frame(i) for i in range(500, 800)]
        frames[100] = frame(600, pitch=100)
        engine, events = self.events(profile, frames)
        self.assertFalse(events)
        self.assertEqual(engine.behavior_status()['baseline_assessment'], 'OBSERVED')

    def test_level_shift_and_oscillation_are_not_fault_code_rules(self):
        profile = self.trained()
        frames = [frame(i, pitch=0 if i < 600 else 4) for i in range(500, 750)]
        _, events = self.events(profile, frames)
        hit = next(e for e in events if e['rule_id'].endswith(':pitch_level'))
        self.assertEqual(hit['category'], 'behavior')
        self.assertEqual(hit['evidence']['finding_type'], 'baseline_deviation')
        self.assertGreater(hit['evidence']['value'], hit['evidence']['upper'])
        self.assertGreaterEqual(hit['trigger_ticks'] - hit['evidence']['first_suspect_ticks'], .4 * HZ)
        self.assertEqual(hit['evidence']['model_id'], profile['analysis']['model']['model_id'])
        frames = [frame(i, pitch=0 if i < 600 else (4 if i % 2 else -4)) for i in range(500, 750)]
        _, events = self.events(profile, frames)
        self.assertTrue(any(e['rule_id'].endswith(':pitch_variation') for e in events))

    def test_stopped_behavior_is_not_compared_with_active_baseline(self):
        profile = self.trained()
        frames = [frame(i, pitch=0) for i in range(500, 600)]
        frames += [frame(i, pitch=90, active=False) for i in range(600, 800)]
        _, events = self.events(profile, frames)
        self.assertFalse(events)

    def test_missing_invalid_samples_and_gaps_interrupt_persistence(self):
        profile = self.trained(); engine = RuleEngine(profile)
        for i in range(100, 180):
            engine.update([frame(i, pitch=4)], [], i * HZ // 50)
        engine.update([frame(180, valid=False)], [], 180 * HZ // 50)
        self.assertFalse(any(k.startswith('behavior:baseline:') for k in engine.behavior.states))
        for i in range(181, 220):
            self.assertFalse(engine.update([frame(i, pitch=4)], [], i * HZ // 50))
        engine.update([frame(300, pitch=4)], [], 300 * HZ // 50)
        self.assertEqual(len(engine.behavior.window), 1)

    def test_untrained_and_ambiguous_modes_remain_unknown(self):
        engine, _ = self.events(self.profile, [frame(i) for i in range(100)])
        self.assertEqual(engine.behavior_status()['baseline_assessment'], 'UNKNOWN')
        self.assertEqual(engine.behavior_status()['current_baseline_state'], 'UNTRAINED')
        profile = copy.deepcopy(self.profile)
        profile['analysis']['modes'][1]['when']['equals'] = 0
        engine, events = self.events(load_profile(profile), [frame(i, active=False) for i in range(20)])
        self.assertFalse(events)
        self.assertIsNone(engine.behavior_status()['mode'])

    def test_sparse_window_breaks_persistence_and_reports_warmup(self):
        profile = self.trained()
        engine, _ = self.events(profile, [frame(i) for i in range(500, 600)])
        self.assertEqual(engine.behavior_status()['current_baseline_state'], 'MONITORING')
        # 5 Hz remains below the frame timeout but cannot fill a 40-sample window.
        for i in range(600, 700, 10):
            engine.update([frame(i, pitch=4)], [], i * HZ // 50)
        self.assertEqual(engine.behavior_status()['current_baseline_state'], 'WARMUP')
        self.assertFalse(engine.behavior.states)

    def test_config_rejects_bad_field_type_threshold_and_tampered_model(self):
        for change in ('field', 'counter', 'margin', 'stat'):
            profile = copy.deepcopy(self.profile)
            if change == 'field':profile['analysis']['freshness'][0]['field'] = 'absent'
            if change == 'counter':profile['analysis']['freshness'][0]['field'] = 'pitch_mdeg'
            if change == 'margin':profile['analysis']['baseline']['features'][0]['margin_floor'] = 0
            if change == 'stat':profile['analysis']['baseline']['features'][0]['stat'] = 'eval'
            with self.assertRaises(ValueError):load_profile(profile)
        profile = self.trained()
        profile['analysis']['model']['modes']['control_active']['pitch_level']['center'] += 1
        with self.assertRaises(ValueError):load_profile(profile)
        profile = self.trained(); profile['fields'][3]['scale'] = 1
        with self.assertRaises(ValueError):load_profile(profile)

    def test_training_requires_duration_and_rejects_freshness_anomaly(self):
        with self.assertRaises(ValueError):fit_baseline(self.profile, [frame(i) for i in range(100)], {})
        with self.assertRaises(ValueError):fit_baseline(self.profile, [frame(i, counter=0) for i in range(400)], {})
        # Separate short segments cannot be counted as one long nominal period.
        frames = [frame(i + block * 1000) for block in range(10) for i in range(60)]
        with self.assertRaises(ValueError):fit_baseline(self.profile, frames, {})

    def test_chunking_does_not_change_events(self):
        profile = self.trained()
        frames = [frame(i, pitch=0 if i < 600 else 4) for i in range(500, 750)]
        _, expected = self.events(profile, frames)
        engine = RuleEngine(profile, frames[0]['end_ticks'])
        actual = engine.update(frames, [], frames[-1]['end_ticks'])
        self.assertEqual(actual, expected)
        backlog = RuleEngine(profile, frames[0]['end_ticks'])
        delayed = []
        for item in frames:
            delayed.extend(backlog.update([item], [], frames[-1]['end_ticks'], drained=False))
        self.assertEqual(delayed, expected)

    def test_behavior_event_uses_existing_archive_and_independent_replay(self):
        profile = self.trained(); profile['evidence'] = dict(pre_seconds=1, post_seconds=1)
        for scenario in ('baseline', 'freshness'):
            with self.subTest(scenario=scenario):
                root = ROOT / 'build/pynq_z2/uart_monitor/behavior_tests' / uuid.uuid4().hex
                root.mkdir(parents=True)
                raw = bytearray(); ticks = []
                for i in range(250):
                    item = frame(i, pitch=4 if scenario=='baseline' and i>=100 else 0,
                                 counter=200 if scenario=='freshness' and 100<=i<150 else None)
                    packet = encode_frame(item['raw_fields'])
                    end = HZ + item['end_ticks']; step = 8680
                    raw.extend(packet); ticks.extend(end - (47 - n) * step for n in range(48))
                (root / 'raw.bin').write_bytes(raw)
                (root / 'timestamps.bin').write_bytes(struct.pack('<' + 'Q' * len(ticks), *ticks))
                report = MonitorSession(profile, root / 'out').run(ReplayTransport(root / 'raw.bin', profile, root / 'timestamps.bin'))
                self.assertEqual(report['device_health'], 'UNKNOWN' if scenario=='baseline' else 'FAIL')
                if scenario=='baseline':
                    self.assertEqual(report['behavior']['baseline_assessment'], 'DEVIATION_OBSERVED')
                else:
                    self.assertEqual(report['event_counts'], {'behavior:freshness:imu_progress':1})
                self.assertEqual(report['evidence']['mode'], 'continuous')
                self.assertEqual(report['evidence']['state'], 'COMPLETED')
                self.assertGreaterEqual(report['evidence']['saved_count'], 1)
                self.assertTrue(verify_result(root / 'out')['logical_events_match'])
                saved = Path(report['evidence']['saved']['path'])
                self.assertFalse(report['evidence']['saved']['manifest']['pre_clipped'])
                self.assertFalse(report['evidence']['saved']['manifest']['post_clipped'])
                self.assertGreater((saved / 'raw.bin').stat().st_size, 48)
                archived = json.loads((root / 'out/profile.json').read_text(encoding='utf-8'))
                self.assertEqual(archived['analysis']['model'], profile['analysis']['model'])

    def test_device_time_reconstruction_is_explicit(self):
        root = ROOT / 'build/pynq_z2/uart_monitor/behavior_tests' / uuid.uuid4().hex
        root.mkdir(parents=True)
        path = root / 'raw.bin'
        path.write_bytes(b''.join(encode_frame(frame(i)['raw_fields']) for i in range(20)))
        with self.assertRaises(ValueError):list(read_frames(path, self.profile))
        frames = list(read_frames(path, self.profile, device_time_ms=True))
        self.assertEqual(frames[-1]['end_ticks'], 19 * HZ // 50)
        selected = list(select_frames(iter(frames), .1, .2))
        self.assertEqual([f['sequence'] for f in selected], list(range(5, 10)))

    def test_cli_roundtrip_provenance_and_existing_model_preservation(self):
        root = ROOT / 'build/pynq_z2/uart_monitor/behavior_tests' / uuid.uuid4().hex
        root.mkdir(parents=True)
        raw = root / 'nominal.bin'; model = root / 'trained.json'
        raw.write_bytes(b''.join(encode_frame(frame(i)['raw_fields']) for i in range(400)))
        args = ['train', '--profile', str(ROOT / 'profiles/car_tlm1.json'), '--analysis',
                str(ROOT / 'profiles/analysis/car_behavior_v1.json'), '--raw', str(raw),
                '--device-time-ms', '--confirm-normal', '--output-profile', str(model)]
        with redirect_stdout(io.StringIO()):self.assertEqual(behavior_cli(args), 0)
        frozen = model.read_bytes(); profile = load_profile(model)
        self.assertEqual(profile['analysis']['model']['training']['time_source'], 'device_ms_reconstructed_not_PL')
        self.assertIn('behavior.py', profile['analysis']['model']['training']['software_files'])
        with self.assertRaises(FileExistsError):behavior_cli(args)
        self.assertEqual(model.read_bytes(), frozen)
        output = io.StringIO()
        with redirect_stdout(output):
            code = behavior_cli(['check', '--profile', str(model), '--raw', str(raw), '--device-time-ms', '--require-normal'])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())['same_source_as_training'])


if __name__ == '__main__':
    unittest.main()
