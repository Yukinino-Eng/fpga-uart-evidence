"""Strict, portable file snapshots. Python 3.6+; no hardware or network access."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

sys.dont_write_bytecode = True


def contained(root, candidate):
    root = Path(root).resolve()
    target = Path(candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError('Path escapes source directory: ' + str(candidate))
    return target


def relative_file(root, name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise ValueError('Manifest paths must be relative POSIX file paths')
    parsed = PurePosixPath(name)
    if parsed.is_absolute() or '..' in parsed.parts or parsed.as_posix() != name or name == '.':
        raise ValueError('Invalid relative path: ' + name)
    current = Path(root)
    for part in parsed.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Symbolic links are not accepted: ' + name)
    target = contained(root, current)
    if not target.is_file():
        raise ValueError('Missing file: ' + name)
    return target


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def snapshot(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('Source directory does not exist')
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symbolic links are not accepted: ' + str(path))
        if path.is_file():
            name = path.relative_to(root).as_posix()
            safe = relative_file(root, name)
            files[name] = dict(bytes=safe.stat().st_size, sha256=digest(safe))
    return dict(schema_version=1, files=files)


def verify(root, manifest):
    if manifest.get('schema_version') != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('Unsupported manifest schema')
    for name, item in manifest['files'].items():
        relative_file(root, name)
        if not isinstance(item, dict) or type(item.get('bytes')) is not int or item['bytes'] < 0:
            raise ValueError('Invalid byte count: ' + name)
        sha = item.get('sha256')
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('Invalid SHA256: ' + name)
    current = snapshot(root)
    if set(current['files']) != set(manifest['files']):
        raise ValueError('File inventory changed: ' + repr(sorted(set(current['files']) ^ set(manifest['files']))))
    changed = [name for name in current['files'] if current['files'][name] != manifest['files'][name]]
    if changed:
        raise ValueError('File contents changed: ' + repr(changed))
    return dict(status='FILE_SNAPSHOT_VERIFIED', files=len(current['files']),
                hardware_accessed=False, network_accessed=False,
                note='File integrity only; not a new hardware acceptance or proof of origin')


def outside(root, path):
    target = Path(path).resolve()
    try:
        target.relative_to(Path(root).resolve())
    except ValueError:
        return target
    raise ValueError('Outputs must be outside the source directory')


def write_new(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['create', 'verify'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        manifest_path = outside(args.root, args.manifest)
        output = outside(args.root, args.output) if args.output else None
        if output and (output == manifest_path or output.exists()):
            raise ValueError('Receipt must be a new file distinct from the manifest')
        if args.action == 'create':
            data = snapshot(args.root)
            write_new(manifest_path, data)
            result = dict(status='FILE_SNAPSHOT_CREATED', files=len(data['files']),
                          hardware_accessed=False, network_accessed=False)
        else:
            result = verify(args.root, json.loads(manifest_path.read_text(encoding='utf-8')))
        if output:
            write_new(output, result)
        print(json.dumps(result))
        return 0
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(json.dumps(dict(status='REJECTED', error=str(error))), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
