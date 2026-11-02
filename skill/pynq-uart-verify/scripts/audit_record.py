"""Audit a saved URX record; optionally replay through explicitly supplied project code."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_snapshot import digest, outside, relative_file, write_new


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def verify_file_map(root, files):
    if not isinstance(files, dict):
        raise ValueError('Missing file digest map')
    for name, expected in files.items():
        if digest(relative_file(root, name)) != expected:
            raise ValueError('Digest mismatch: ' + str(name))


def check_time_index(raw, timestamps):
    size = Path(raw).stat().st_size
    if Path(timestamps).stat().st_size != size * 8:
        raise ValueError('Timestamp index must contain one little-endian uint64 per byte')
    previous = None
    with Path(timestamps).open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            for tick, in struct.iter_unpack('<Q', block):
                if previous is not None and tick < previous:
                    raise ValueError('Hardware time moved backwards inside one record')
                previous = tick
    return size


def summarize(root):
    root = Path(root).resolve()
    report = read_json(relative_file(root, 'report.json'))
    verify_file_map(root, report.get('files'))
    for name in ['raw.bin', 'timestamps.bin', 'profile.json', 'events.jsonl', 'frames.jsonl']:
        if name not in report['files']:
            raise ValueError('Required file missing from digest map: ' + name)
    raw_bytes = check_time_index(root / 'raw.bin', root / 'timestamps.bin')
    events = []
    with (root / 'events.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                events.append(json.loads(line))
    if len({e['event_id'] for e in events}) != len(events):
        raise ValueError('Duplicate event IDs in the saved ledger')
    saved = {}
    for path in sorted((root / 'events').glob('*/event.json')):
        relative_file(root, path.relative_to(root).as_posix())
        window = read_json(path)
        verify_file_map(path.parent, window.get('files'))
        eid = window['trigger']['event_id']
        if eid not in {e['event_id'] for e in events}:
            raise ValueError('Window has no matching event')
        if window['trigger'] != next(e for e in events if e['event_id'] == eid):
            raise ValueError('Window trigger differs from event ledger')
        if eid not in saved or window.get('attempt', 0) > saved[eid].get('attempt', 0):
            saved[eid] = window
    parser = report.get('parser', {})
    evidence = report.get('evidence', {})
    if evidence.get('saved_count') != len(saved):
        raise ValueError('Saved-window count differs from existing verified window files')
    if report.get('events_total') != len(events):
        raise ValueError('Event count differs from saved ledger')
    complete = [w for w in saved.values() if w['trigger']['category'] == 'device'
                and w.get('pre_clipped') is False and w.get('post_clipped') is False
                and not w.get('pre_cache_clipped', False)]
    counts = Counter(e['trigger_ticks'] for e in events if e['category'] == 'device')
    return dict(assessment={key: report.get(key) for key in
                            ['capture_integrity', 'protocol_integrity', 'device_health']},
                raw_bytes=raw_bytes, frames=parser.get('frames'), events=len(events),
                device_events=sum(e['category'] == 'device' for e in events),
                same_tick_device_counts=[counts[t] for t in sorted(counts)],
                saved_windows=len(saved), complete_device_windows=len(complete),
                checksum_available=parser.get('checksum_available'),
                sequence_available=parser.get('sequence_available'),
                parser=parser, failed_windows=evidence.get('failed_count'),
                pending_windows=evidence.get('pending_count'), dropped_windows=evidence.get('dropped_count'))


def compare_subset(expected, actual, location='result'):
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise ValueError('Expected object at ' + location)
        for key, value in expected.items():
            if key not in actual:
                raise ValueError('Missing expectation field: ' + location + '.' + key)
            compare_subset(value, actual[key], location + '.' + key)
    elif type(expected) is not type(actual) or expected != actual:
        raise ValueError('Expectation mismatch at {}: expected {!r}, got {!r}'.format(location, expected, actual))


def replay(root, project):
    scripts = Path(project).resolve() / 'scripts'
    cli = scripts / 'uart_monitor_cli.py'
    if not cli.is_file():
        raise ValueError('Project must contain scripts/uart_monitor_cli.py')
    sys.path.insert(0, str(scripts))
    specification = importlib.util.spec_from_file_location('skill_uart_monitor_cli', str(cli))
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    result = module.verify_result(Path(root))
    result['implementation_files'] = {
        'uart_monitor_cli.py': digest(cli),
        'decoder.py': digest(scripts / 'uart_monitor/decoder.py'),
        'rules.py': digest(scripts / 'uart_monitor/rules.py'),
        'hardware.py': digest(scripts / 'uart_monitor/hardware.py')}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--project-root', type=Path)
    parser.add_argument('--expect', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        output = outside(args.record, args.output) if args.output else None
        if output and output.exists():
            raise ValueError('Output already exists; use a new receipt path')
        observed = summarize(args.record)
        result = dict(status='OFFLINE_FILES_VERIFIED', observed=observed,
                      hardware_accessed=False, network_accessed=False,
                      note='Saved artifacts only. Original capture/device assessments are preserved.')
        if args.project_root:
            result['replay'] = replay(args.record, args.project_root)
        if args.expect:
            compare_subset(read_json(args.expect), result)
            result['expectations_matched'] = True
        if output:
            write_new(output, result)
        print(json.dumps(result))
        return 0
    except (ValueError, OSError, TypeError, KeyError, ImportError, StopIteration) as error:
        print(json.dumps(dict(status='REJECTED', error=str(error))), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
