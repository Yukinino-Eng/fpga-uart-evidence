"""Portable EGo1 sender contract: reference bytes, schedule, and PC-side checks.

This tool never opens a serial port or accesses FPGA hardware. Python 3.6+.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
if not (HERE / 'uart_monitor').is_dir():
    sys.path.insert(0, str(ROOT / 'oracle'))
from uart_monitor.decoder import ByteChunk, Decoder
from uart_monitor.hardware import compile_profile
from uart_monitor.rules import RuleEngine

HZ = 100000000
NAMES = ('normal', 'bad_crc', 'skip', 'duplicate', 'gap', 'persistent', 'glitch', 'parallel8',
         'status', 'invalid', 'restart')
BODY = struct.Struct('<2sBBIIIiiiiHHHHHH')
FIELDS = ('sequence', 'uptime_ms', 'imu_sample_count', 'pitch_mdeg', 'rate_mdps',
          'encoder_e1', 'encoder_e2', 'pwm_a_counts', 'pwm_b_counts', 'flags',
          'fault_code', 'tx_skipped', 'imu_age_ms')


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def values_for(case, slot, fps):
    row = dict(zip(FIELDS, (slot, slot * 1000 // fps, slot * 2, -1234, 5678,
                           -42, 42, 8, 12, 35, 0, 0, 4)))
    first = 6 * fps
    if case == 'skip' and slot >= first:
        row['sequence'] += 1
    if case == 'duplicate' and slot >= first:
        row['sequence'] -= 1
    if case == 'persistent' and first <= slot < first + fps // 2:
        row['pitch_mdeg'] = 20000
    if case == 'glitch' and slot == first:
        row['pitch_mdeg'] = 20000
    if case == 'parallel8' and (first <= slot < first + fps // 5 or
                               14 * fps <= slot < 14 * fps + fps // 5):
        row['fault_code'] = 20
    if case == 'status' and first <= slot < first + fps // 2:
        row['fault_code'] = 1
    if case == 'invalid' and first <= slot < first + fps // 2:
        row['flags'] = 0
    if case == 'restart' and slot >= first:
        row['sequence'] -= first
        row['uptime_ms'] -= 6000
    return row


def encode(row):
    body = BODY.pack(b'\xa5\x5a', 1, 48, *(row[n] for n in FIELDS))
    return body + struct.pack('<I', zlib.crc32(body) & 0xffffffff)


def expected_device_counts(case):
    if case == 'persistent':
        return {'pitch_limit': 1}
    if case == 'parallel8':
        return {'parallel_%d' % i: 2 for i in range(8)}
    if case == 'status':
        return {'device_fault': 1}
    if case == 'invalid':
        return {'imu_invalid': 1}
    return {}


def generate(args):
    if args.fps not in (10, 50) or args.baud not in (9600, 115200):
        raise ValueError('Supported rates: 10/50 fps, 9600/115200 baud')
    if args.baud == 9600 and args.fps != 10:
        raise ValueError('9600 baud cannot carry 48-byte frames at 50 fps')
    if args.seconds not in (20, 60, 180):
        raise ValueError('Use 20/60/180 seconds')
    if args.output.exists():
        raise ValueError('Choose a new output directory; existing results are preserved')
    profile_path = ROOT / 'profiles' / ('ego1_parallel8.json' if args.case == 'parallel8' else 'ego1_faults.json')
    profile = json.loads(profile_path.read_text(encoding='utf-8'))
    profile['transport']['baud'] = args.baud
    compiled = compile_profile(profile)
    profile = compiled['profile']
    decoder = Decoder(profile)
    engine = RuleEngine(profile, 0)
    cpb = (HZ + args.baud // 2) // args.baud
    period = HZ // args.fps
    char_cycles = 10 * cpb
    interbyte_cycles = 2
    assert 48 * (char_cycles + interbyte_cycles) < period
    raw, times, events, schedule = bytearray(), [], [], []
    for slot in range(args.seconds * args.fps):
        if args.case == 'gap' and 6 * args.fps <= slot < 6 * args.fps + 3 * args.fps // 5:
            continue
        row = values_for(args.case, slot, args.fps)
        packet = bytearray(encode(row))
        if args.case == 'bad_crc' and slot == 6 * args.fps:
            packet[44] ^= 1
        offset = len(raw)
        start = slot * period
        # Modeled byte receive time at the center of the stop bit, not a board measurement.
        byte_ticks = [start + i * (char_cycles + interbyte_cycles) + (19 * cpb) // 2
                      for i in range(48)]
        accepted, issues = decoder.feed(ByteChunk(packet, byte_ticks, offset))
        # Updating at each packet also accounts for any intentional valid-frame silence.
        events.extend(engine.update(accepted, issues, byte_ticks[-1]))
        schedule.append(dict(slot=slot, start_cycle=start, raw_offset=offset, length=48,
                             sequence=row['sequence'], uptime_ms=row['uptime_ms']))
        raw.extend(packet)
        times.extend(byte_ticks)
    end = args.seconds * HZ
    events.extend(engine.update([], decoder.finish(), end))
    device = Counter(e['rule_id'] for e in events if e['category'] == 'device')
    assert dict(device) == expected_device_counts(args.case), (args.case, device)
    stats = decoder.summary()
    assert stats['crc_errors'] == int(args.case == 'bad_crc')
    assert stats['duplicates'] == int(args.case == 'duplicate')
    assert stats['restart_or_out_of_order'] == int(args.case == 'restart')
    missing = 3 * args.fps // 5 if args.case == 'gap' else int(args.case in ('bad_crc', 'skip'))
    assert stats['sequence_missing'] == missing
    assert sum(e['rule_id'] == 'valid_frame_timeout' for e in events) == int(args.case == 'gap')
    args.output.mkdir(parents=True)
    (args.output / 'stream.bin').write_bytes(raw)
    (args.output / 'bytes.mem').write_text(''.join('%02x\n' % b for b in raw), encoding='ascii')
    (args.output / 'timestamps_model.bin').write_bytes(struct.pack('<' + 'Q' * len(times), *times))
    with (args.output / 'schedule.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(schedule[0]))
        writer.writeheader()
        writer.writerows(schedule)
    # 128-bit descriptor: start cycles[127:64], offset[63:32], length[31:16], reserved[15:0].
    (args.output / 'schedule.mem').write_text(''.join('%016x%08x%04x0000\n' %
        (r['start_cycle'], r['raw_offset'], r['length']) for r in schedule), encoding='ascii')
    dump(args.output / 'profile.json', profile)
    dump(args.output / 'expected.json', dict(
        case=args.case, baud=args.baud, fps=args.fps, seconds=args.seconds,
        clock_hz=HZ, clocks_per_bit=cpb, schedule_count=len(schedule),
        raw_bytes=len(raw), stream_sha256=hashlib.sha256(raw).hexdigest(),
        parser=stats, device_event_counts=dict(device),
        hardware_covered_event_counts=dict(Counter(e['rule_id'] for e in events
            if e['rule_id'] != 'protocol:interframe_noise')),
        events=events, phase='First test frame through declared source duration; excludes startup/stop silence',
        time_origin='Synthetic reference timeline; not UTC or captured FPGA timestamps',
        interbyte_cycles_model=interbyte_cycles, hardware_accessed=False))
    print('GENERATED %s bytes=%d frames=%d' % (args.output.name, len(raw), len(schedule)))


def check(args):
    fixture = args.fixture
    expected = (fixture / 'stream.bin').read_bytes()
    received = args.received.read_bytes()
    if received != expected:
        common = min(len(received), len(expected))
        first = next((i for i in range(common) if received[i] != expected[i]), common)
        raise ValueError('Byte mismatch at offset %d; expected %d bytes, received %d' %
                         (first, len(expected), len(received)))
    status = dict(status='PASS_EXACT_BYTES', received_bytes=len(received),
                  timing='NOT_CHECKED', hardware_accessed_by_this_tool=False)
    if args.starts:
        with (fixture / 'schedule.csv').open(newline='', encoding='utf-8-sig') as handle:
            planned = list(csv.DictReader(handle))
        with args.starts.open(newline='', encoding='utf-8-sig') as handle:
            observed = list(csv.DictReader(handle))
        if len(observed) != len(planned):
            raise ValueError('Frame start log count mismatch')
        origin = int(observed[0]['start_cycle']) - int(planned[0]['start_cycle'])
        errors = []
        for target, actual in zip(planned, observed):
            if int(actual['slot']) != int(target['slot']):
                raise ValueError('Frame slot mismatch; check skipped slots')
            errors.append(abs(int(actual['start_cycle']) - origin - int(target['start_cycle'])))
        maximum = max(errors)
        if maximum > args.tolerance_us * HZ / 1000000:
            raise ValueError('Frame timing mismatch: maximum %d cycles' % maximum)
        status.update(timing='PASS_FRAME_START_SCHEDULE', max_deviation_cycles=maximum,
                      aligned_initial_latency_cycles=origin)
    if args.output:
        if args.output.exists():
            raise ValueError('Do not overwrite a previous check result')
        dump(args.output, status)
    print(json.dumps(status, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action')
    gen = sub.add_parser('generate')
    gen.add_argument('--case', choices=NAMES, required=True)
    gen.add_argument('--baud', type=int, default=115200)
    gen.add_argument('--fps', type=int, default=10)
    gen.add_argument('--seconds', type=int, default=20)
    gen.add_argument('--output', type=Path, required=True)
    verify = sub.add_parser('check')
    verify.add_argument('--fixture', type=Path, required=True)
    verify.add_argument('--received', type=Path, required=True)
    verify.add_argument('--starts', type=Path)
    verify.add_argument('--tolerance-us', type=float, default=1000)
    verify.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action == 'generate':
        generate(args)
    elif args.action == 'check':
        if args.tolerance_us <= 0:
            raise ValueError('Timing tolerance must be positive')
        check(args)
    else:
        parser.error('Choose generate or check')


if __name__ == '__main__':
    main()
