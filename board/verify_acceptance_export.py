"""Verify an exported UART session offline without accessing a board."""
import argparse
from datetime import datetime
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def contained(base, name):
    name = str(name).replace('\\', '/')
    parts = PurePosixPath(name)
    if not name or parts.is_absolute() or '..' in parts.parts or ':' in name:
        raise ValueError('Unsafe archive path: ' + name)
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {
        prefix + str(n) for prefix in ('COM', 'LPT') for n in range(1, 10)}
    if any(part.endswith(('.', ' ')) or part.split('.')[0].upper() in reserved
           or any(ord(c) < 32 for c in part) for part in parts.parts):
        raise ValueError('Unsupported Windows path: ' + name)
    target = (base / name).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        raise ValueError('Path escapes the record: ' + name)
    return target


def extract(source, destination):
    with zipfile.ZipFile(str(source)) as bundle:
        entries = bundle.infolist()
        if len(entries) > 50000 or sum(e.file_size for e in entries) > 1024 ** 3:
            raise ValueError('Archive exceeds the 1 GiB / 50000-entry inspection limit')
        seen = set()
        for entry in entries:
            target = contained(destination, entry.filename)
            key = str(target).casefold()
            if key in seen:
                raise ValueError('Duplicate archive path: ' + entry.filename)
            seen.add(key)
            mode = (entry.external_attr >> 16) & 0xffff
            if stat.S_ISLNK(mode) or entry.flag_bits & 1:
                raise ValueError('Symlink/encrypted entry is unsupported')
        destination.mkdir()
        for entry in entries:
            target = contained(destination, entry.filename)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as src, target.open('xb') as dst:
                    while True:
                        block = src.read(1024 * 1024)
                        if not block:
                            break
                        dst.write(block)


def locate_record(base):
    candidates = [base] + [p.parent for p in base.rglob('report.json')]
    result = []
    for candidate in candidates:
        if (all((candidate / name).is_file() for name in
                ('report.json', 'raw.bin', 'timestamps.bin', 'frames.jsonl', 'profile.json'))
                and candidate not in result):
            result.append(candidate)
    if len(result) != 1:
        raise ValueError('Select one exported session; detected %d records' % len(result))
    return result[0]


def check_file_references(record):
    for path in record.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlinks are unsupported: ' + str(path))
    metadata = [record / 'report.json'] + list((record / 'events').glob('*/event.json'))
    for path in metadata:
        value = json.loads(path.read_text(encoding='utf-8'))
        for name in value.get('files', {}):
            contained(path.parent, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    source = args.input.expanduser().resolve()
    if not source.exists():
        raise ValueError('Input does not exist: ' + str(source))
    output = args.output or ROOT / 'out/acceptance_checks' / (
        datetime.now().strftime('run_%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:6])
    output = output.resolve()
    if source.is_dir():
        try:
            output.relative_to(source)
        except ValueError:
            pass
        else:
            raise ValueError('Output must be outside the original record')
    output.mkdir(parents=True, exist_ok=False)
    try:
        if source.is_dir():
            record = locate_record(source)
        elif source.suffix.lower() == '.zip':
            extract(source, output / 'extracted')
            record = locate_record(output / 'extracted')
        else:
            raise ValueError('Select an exported ZIP or an extracted session directory')
        check_file_references(record)
        sys.path.insert(0, str(ROOT / 'src/pynq/scripts'))
        from uart_monitor_cli import verify_result
        result = verify_result(record)
        report = json.loads((record / 'report.json').read_text(encoding='utf-8'))
        receipt = dict(status='OFFLINE_VERIFICATION_PASSED', verification=result,
                       record=str(record), original_input=str(source),
                       capture_integrity=report.get('capture_integrity'),
                       protocol_integrity=report.get('protocol_integrity'),
                       hardware_accessed=False)
        (output / 'verification.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Offline verification passed. Frames: %s' % result['frames'])
        print('Capture integrity: %s; protocol integrity: %s' % (
            receipt['capture_integrity'], receipt['protocol_integrity']))
        print('Logical events match: %s' % result.get('logical_events_match'))
        print('Result: ' + str(output / 'verification.json'))
        return 0
    except Exception as error:
        (output / 'verification.json').write_text(json.dumps(dict(
            status='OFFLINE_VERIFICATION_FAILED', error=str(error), hardware_accessed=False),
            ensure_ascii=False, indent=2), encoding='utf-8')
        raise


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print('Verification failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
