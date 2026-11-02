"""Independently replay every included PYNQ session. No board access."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/pynq/scripts'))
from uart_monitor_cli import verify_result

def main():
    records = []
    for report in sorted((ROOT / 'data/pynq').rglob('report.json')):
        folder = report.parent
        if not (folder / 'raw.bin').is_file():
            continue
        result = verify_result(folder)
        record = {'path': folder.relative_to(ROOT).as_posix(), 'verification': result}
        records.append(record)
        print('VERIFIED ' + record['path'] + ' frames=' + str(result['frames']))
    if not records:
        raise SystemExit('No complete raw records found')
    print(json.dumps({'status': 'PASS', 'records': len(records), 'hardware_accessed': False,
                      'frames': sum(x['verification']['frames'] for x in records)}, indent=2))
    return records

if __name__ == '__main__':
    main()

