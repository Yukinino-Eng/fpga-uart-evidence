"""Check the sealed repository paths and SHA256 manifest, without hardware access."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def files(root):
    for p in root.rglob('*'):
        relative = p.relative_to(root)
        if not p.is_file() or any(x in ('.git', '__pycache__', '.pytest_cache', '.venv', '.Xil') for x in relative.parts):
            continue
        if relative.parts[0] == 'out' or relative.parts[:3] in (('src', 'pynq', 'build'), ('src', 'ego1', 'build')):
            continue
        if relative.parts[:3] in (('src','car','build'),('src','car','Objects'),('src','car','Listings')):
            continue
        yield p

def main():
    expected = json.loads((ROOT / 'manifest.sha256.json').read_text(encoding='utf-8'))['files']
    actual = {p.relative_to(ROOT).as_posix(): p for p in files(ROOT) if p != ROOT / 'manifest.sha256.json'}
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    bad = [name for name in expected if name in actual and hashlib.sha256(actual[name].read_bytes()).hexdigest() != expected[name]]
    invalid_paths = []
    for name in actual:
        for part in Path(name).parts:
            if part in ('README.md', 'SKILL.md'):
                continue
            pattern=r'[A-Za-z0-9_.-]+' if Path(name).parts[:2]==('src','car') or Path(name).parts[:3]==('board','car','firmware') else r'[a-z0-9_.-]+'
            if not re.fullmatch(pattern, part):
                invalid_paths.append(name)
                break
    if missing or extra or bad or invalid_paths:
        raise SystemExit(json.dumps({'missing': missing, 'extra': extra, 'changed': bad,
                                     'invalid_paths': invalid_paths}, ensure_ascii=False, indent=2))
    version = json.loads((ROOT / 'report/provenance/pynq_version.json').read_text(encoding='utf-8'))
    for name, digest in version['firmware_sha256'].items():
        assert hashlib.sha256((ROOT / 'board/pynq/firmware' / name).read_bytes()).hexdigest() == digest, name
    print('REPOSITORY_PASS files={} paths=english firmware_pair=verified hardware_accessed=false'.format(len(expected)))

if __name__ == '__main__':
    main()

