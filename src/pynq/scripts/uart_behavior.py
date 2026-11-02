"""Train a frozen behavior profile or check separate data, without board access.

train: --profile profiles/car_tlm1.json --analysis profiles/analysis/car_behavior_v1.json
       --raw <nominal raw.bin> --timestamps <timestamps.bin> --confirm-normal
       --output-profile <new profile.json>
check: --profile <trained profile.json> --raw <held-out raw.bin> --timestamps <index>

Legacy CAR1 data has no per-byte time index: use --device-time-ms explicitly.
This reconstructs frame timing from the device counter, not from a hardware clock.
Put a trained JSON in profiles/ to select it after reopening the existing Notebook.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from uart_monitor.behavior import fit_baseline
from uart_monitor.decoder import make_decoder
from uart_monitor.profile import load_profile
from uart_monitor.rules import HZ, RuleEngine
from uart_monitor.transport import ReplayTransport, digest


def read_frames(raw, profile, timestamps=None, device_time_ms=False):
    if bool(timestamps) == bool(device_time_ms):
        raise ValueError('Choose exactly one: --timestamps or --device-time-ms')
    if device_time_ms and not profile.get('sequence', {}).get('time_field'):
        raise ValueError('Device time reconstruction needs a configured device time field')
    decoder = make_decoder(profile)
    source = ReplayTransport(raw, profile, timestamps)
    previous = None; elapsed = 0
    bits = profile.get('sequence', {}).get('time_bits', 32)
    try:
        source.start()
        while True:
            chunk = source.read()
            frames, issues = decoder.feed(chunk)
            if issues:
                raise ValueError('Source protocol continuity is broken: ' + issues[0]['kind'])
            for frame in frames:
                if device_time_ms:
                    current = frame['device_time']
                    if previous is not None:
                        delta = (current - previous) % (1 << bits)
                        if delta >= 1 << (bits - 1):
                            raise ValueError('Device time restarted or went backwards')
                        elapsed += delta
                    previous = current
                    frame['start_ticks'] = frame['end_ticks'] = elapsed * HZ // 1000
                yield frame
            if source.eof:
                break
        if decoder.finish() or decoder.buffer:
            raise ValueError('Source contains trailing noise or an incomplete frame')
    finally:
        source.close()


def select_frames(frames, start_seconds=0, end_seconds=None):
    first = None
    try:
        for frame in frames:
            if first is None:
                first = frame['end_ticks']
            elapsed = (frame['end_ticks'] - first) / HZ
            if end_seconds is not None and elapsed >= end_seconds:
                break
            if elapsed >= start_seconds:
                yield frame
    finally:
        if hasattr(frames, 'close'):
            frames.close()


def nominal_frames(profile, frames):
    # Existing fault/validity rules also screen the declared nominal training set.
    plain = copy.deepcopy(profile); plain.pop('analysis', None)
    engine = None
    for frame in frames:
        if engine is None:
            engine = RuleEngine(plain, frame['end_ticks'])
        events = engine.update([frame], [], frame['end_ticks'])
        if events:
            raise ValueError('Declared nominal data violates ' + events[0]['rule_id'])
        yield frame


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('train', 'check'))
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--analysis', type=Path, help='Optional analysis config when training a protocol profile')
    parser.add_argument('--raw', required=True, type=Path)
    timing = parser.add_mutually_exclusive_group(required=True)
    timing.add_argument('--timestamps', type=Path)
    timing.add_argument('--device-time-ms', action='store_true', help='Explicitly reconstructed device time; not PL timestamps')
    parser.add_argument('--start-seconds', type=float, default=0)
    parser.add_argument('--end-seconds', type=float)
    parser.add_argument('--output-profile', type=Path)
    parser.add_argument('--confirm-normal', action='store_true', help='Declare selected training data nominal; not a diagnostic certification')
    parser.add_argument('--require-normal', action='store_true', help='Check exits nonzero on any anomaly or insufficient baseline coverage')
    args = parser.parse_args(argv)
    if not math.isfinite(args.start_seconds) or args.start_seconds < 0 or (args.end_seconds is not None and
            (not math.isfinite(args.end_seconds) or args.end_seconds <= args.start_seconds)):
        parser.error('Invalid time selection')
    if args.action == 'check' and args.analysis:
        parser.error('check uses the frozen analysis embedded in --profile')
    profile = load_profile(args.profile)
    if args.analysis:
        profile['analysis'] = json.loads(args.analysis.read_text(encoding='utf-8'))
        profile = load_profile(profile)
    if not profile.get('analysis'):
        parser.error('Behavior config is required')
    frames = select_frames(read_frames(args.raw, profile, args.timestamps, args.device_time_ms),
                           args.start_seconds, args.end_seconds)
    try:
        if args.action == 'train':
            if not args.confirm_normal or not args.output_profile:
                parser.error('train requires --confirm-normal and --output-profile')
            if args.output_profile.exists():
                raise FileExistsError('Preserve existing trained profiles: ' + str(args.output_profile))
            provenance = dict(raw_sha256=digest(args.raw),
                              timestamps_sha256=digest(args.timestamps) if args.timestamps else None,
                              time_source='device_ms_reconstructed_not_PL' if args.device_time_ms else 'supplied_capture_index',
                              selected_start_seconds=args.start_seconds, selected_end_seconds=args.end_seconds,
                              nominal_declared=True, hardware_accessed=False,
                              software_files={p.name: digest(p) for p in Path(__file__).with_name('uart_monitor').glob('*.py')})
            provenance['software_files']['uart_behavior.py'] = digest(__file__)
            result = fit_baseline(profile, nominal_frames(profile, frames), provenance)
            args.output_profile.parent.mkdir(parents=True, exist_ok=True)
            with args.output_profile.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
            print(json.dumps(dict(status='FROZEN_PROFILE_CREATED', model_id=result['analysis']['model']['model_id'],
                                  modes=sorted(result['analysis']['model']['modes']), hardware_accessed=False), indent=2))
            return 0
        engine = None; count = 0; examples = []
        for frame in frames:
            if engine is None:
                engine = RuleEngine(profile, frame['end_ticks'])
            events = engine.update([frame], [], frame['end_ticks'])
            if len(examples) < 20:
                examples.extend(events[:20-len(examples)])
            count += 1
        if engine is None:
            raise ValueError('No frames in selected interval')
        status = engine.behavior_status()
        source_digest = digest(args.raw)
        print(json.dumps(dict(status='CHECKED', frames=count, event_counts=engine.history_counts,
                              behavior=status, sample_events=examples, hardware_accessed=False,
                              raw_sha256=source_digest,
                              same_source_as_training=source_digest==profile['analysis'].get('model', {}).get('training', {}).get('raw_sha256'),
                              selected_start_seconds=args.start_seconds, selected_end_seconds=args.end_seconds,
                              time_source='device_ms_reconstructed_not_PL' if args.device_time_ms else 'supplied_capture_index',
                              note='Offline observations, not physical fault or independent generalization validation'), indent=2))
        return 1 if args.require_normal and (engine.events_total or status['baseline_assessment']=='UNKNOWN') else 0
    finally:
        frames.close()


if __name__ == '__main__':
    raise SystemExit(main())
