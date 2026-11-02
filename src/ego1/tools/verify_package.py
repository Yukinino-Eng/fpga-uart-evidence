"""Verify the normalized EGo1 snapshot; original package provenance is separate."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
expected = json.loads((ROOT / 'manifest.sha256.json').read_text(encoding='utf-8'))['files']
actual = {p.relative_to(ROOT).as_posix(): p for p in ROOT.rglob('*') if p.is_file()
          and p.name != 'manifest.sha256.json'
          and not any(x in ('__pycache__', 'build', '.git', '.Xil') for x in p.relative_to(ROOT).parts)}
missing = sorted(set(expected) - set(actual))
extra = sorted(set(actual) - set(expected))
bad = [name for name in expected if name in actual and hashlib.sha256(actual[name].read_bytes()).hexdigest() != expected[name]]
if missing or extra or bad:
    raise SystemExit('PACKAGE_FAIL missing=%s extra=%s changed=%s' % (missing, extra, bad))
print('PACKAGE_PASS files=%d hardware_accessed=false' % len(expected))
