"""Offline error-injection checks for the reusable skill helpers, not FPGA tests."""
import json
from pathlib import Path
import struct
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_snapshot import snapshot, verify, relative_file, outside, write_new, digest
from audit_record import check_time_index, compare_subset


def main():
    checks = []

    def reject(label, action):
        try:
            action()
        except (ValueError, OSError):
            checks.append(label)
            return
        raise AssertionError('Unsafe/invalid operation was accepted: ' + label)

    with tempfile.TemporaryDirectory(prefix='urx_skill_') as temporary:
        base = Path(temporary).resolve()
        # Keep all generated files inside this known temporary root.
        base.relative_to(Path(tempfile.gettempdir()).resolve())
        root = base / 'source'
        root.mkdir()
        data = root / 'data.bin'
        data.write_bytes(b'actual bytes\x00\xff')
        manifest = snapshot(root)
        assert verify(root, manifest)['files'] == 1
        checks.append('unchanged_file_passes')
        data.write_bytes(b'changed bytes')
        reject('changed_file_rejected', lambda: verify(root, manifest))
        data.write_bytes(b'actual bytes\x00\xff')
        extra = root / 'extra.txt'
        extra.write_text('unexpected', encoding='utf-8')
        reject('extra_file_rejected', lambda: verify(root, manifest))
        extra.unlink()
        data.unlink()
        reject('missing_file_rejected', lambda: verify(root, manifest))
        data.write_bytes(b'actual bytes\x00\xff')
        reject('parent_path_rejected', lambda: relative_file(root, '../source/data.bin'))
        reject('absolute_path_rejected', lambda: relative_file(root, data.as_posix()))
        reject('output_inside_source_rejected', lambda: outside(root, root / 'receipt.json'))
        receipt = base / 'receipt.json'
        write_new(receipt, dict(status='test'))
        reject('existing_output_rejected', lambda: write_new(receipt, dict(status='overwrite')))
        assert json.loads(receipt.read_text())['status'] == 'test'
        raw, times = base / 'raw.bin', base / 'timestamps.bin'
        raw.write_bytes(b'ABC')
        times.write_bytes(struct.pack('<3Q', 10, 20, 30))
        assert check_time_index(raw, times) == 3
        checks.append('valid_time_index_passes')
        times.write_bytes(struct.pack('<2Q', 10, 20))
        reject('short_time_index_rejected', lambda: check_time_index(raw, times))
        times.write_bytes(struct.pack('<3Q', 10, 9, 30))
        reject('backwards_time_rejected', lambda: check_time_index(raw, times))
        degraded = dict(assessment=dict(capture_integrity='FAIL', protocol_integrity='FAIL', device_health='UNKNOWN'))
        compare_subset(degraded, degraded)
        checks.append('expected_failed_capture_preserved')
        reject('capture_failure_cannot_claim_device_pass', lambda: compare_subset(
            dict(assessment=dict(device_health='PASS')), degraded))
        compare_subset(dict(checksum_available=False, sequence_available=False),
                       dict(checksum_available=False, sequence_available=False))
        checks.append('unavailable_checks_preserved')
        reject('unavailable_checksum_cannot_claim_available', lambda: compare_subset(
            dict(checksum_available=True), dict(checksum_available=False)))
        assert digest(data) == manifest['files']['data.bin']['sha256']
    print(json.dumps(dict(status='PASS_SKILL_HELPERS', checks=len(checks), results=checks,
                          hardware_accessed=False, network_accessed=False,
                          note='Generated temporary inputs; not a new physical acquisition')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
