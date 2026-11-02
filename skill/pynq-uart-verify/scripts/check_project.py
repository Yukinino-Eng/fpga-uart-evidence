"""Run the shipped URX examples against a supplied full project, without a board."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_snapshot import contained, write_new


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    skill = Path(__file__).resolve().parents[1]
    root = args.project_root.resolve()
    cases = json.loads((skill / 'examples/record-cases.json').read_text(encoding='utf-8'))
    records = []
    for case in cases:
        if not re.match(r'^[a-z0-9_]+$', case['id']):
            raise ValueError('Invalid case ID')
        record = contained(root, root / case['record'])
        if not record.is_dir():
            raise ValueError('Missing historical record: ' + case['record'])
        try:
            args.output.resolve().relative_to(record)
        except ValueError:
            pass
        else:
            raise ValueError('Output must not be inside an input record')
        records.append(record)
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for case, record in zip(cases, records):
        output = args.output / (case['id'] + '.json')
        command = [sys.executable, '-B', str(skill / 'scripts/audit_record.py'),
                   '--project-root', str(root), '--record', str(record),
                   '--expect', str(skill / 'examples' / case['expect']), '--output', str(output)]
        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if process.returncode:
            (args.output / (case['id'] + '_error.txt')).write_bytes(process.stderr)
            write_new(args.output / 'completion.json', dict(status='REJECTED', completed=results,
                      failed_case=case['id'], hardware_accessed=False))
            print(process.stderr.decode('utf-8', errors='replace'), file=sys.stderr)
            return 1
        receipt = json.loads(output.read_text(encoding='utf-8'))
        results.append(dict(id=case['id'], expectations_matched=receipt['expectations_matched'],
                            frames=receipt['observed']['frames'],
                            device_health=receipt['observed']['assessment']['device_health']))
    receipt = dict(status='PASS_HISTORICAL_RECORD_AUDIT', cases=results,
                   hardware_accessed=False, network_accessed=False,
                   note='New offline validation of existing physical records; no new board test')
    write_new(args.output / 'completion.json', receipt)
    print(json.dumps(receipt))
    return 0


if __name__ == '__main__':
    sys.exit(main())
