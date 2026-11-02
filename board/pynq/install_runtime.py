"""Copy the sealed PYNQ runtime to a new directory. No hardware access."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error('Output already exists; choose a new directory')
    source = ROOT / 'src/pynq'
    if output == ROOT or ROOT in output.parents:
        # Local smoke deployments are allowed only under the ignored out directory.
        if ROOT / 'out' not in output.parents:
            parser.error('For a local deployment use out/<new_directory>')
    manifest = json.loads((ROOT / 'manifest.sha256.json').read_text(encoding='utf-8'))['files']
    selected = []
    for folder in ['scripts/uart_monitor', 'profiles', 'notebooks']:
        selected.extend(p for p in (source / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    for name in ['car_telemetry.py', 'car_tilt_demo.py', 'car_uart_capture.py', 'pynq_hardware_lease.py',
                 'uart_monitor_cli.py', 'uart_behavior.py', 'uart_monitor_view.py']:
        selected.append(source / 'scripts' / name)
    selected.extend(p for p in (ROOT / 'board/pynq/firmware').iterdir() if p.is_file())
    for p in selected:
        key = p.relative_to(ROOT).as_posix()
        if hashlib.sha256(p.read_bytes()).hexdigest() != manifest[key]:
            raise ValueError('Source hash mismatch: ' + key)
    output.mkdir(parents=True)
    records = {}
    for p in selected:
        relative = p.relative_to(source) if source in p.parents else Path('firmware') / p.name
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(p), str(target))
        records[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
    (output / 'runtime_manifest.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
    print('RUNTIME_PREPARED files={} path={} hardware_accessed=false'.format(len(records), output))

if __name__ == '__main__':
    main()

