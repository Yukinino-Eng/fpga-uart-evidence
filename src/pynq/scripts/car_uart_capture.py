"""CAR1 PMODA UART capture/replay. Receive-only; never transmits car commands."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parent))
from car_telemetry import TelemetryParser

BASE = 0x43c10000
ID = 0x31524143
REGS = dict(control=0, status=4, level=12, received=16, consumed=20,
            overflows=24, framing_errors=28, clock_hz=32, baud=36, fifo_bytes=40, session=44)
KNOWN_SBB = {'625806bf59309fb2b8e715efacd2cfceca0c987b28ff83f3f30bb065746ae0a8',
             '76de1af2670892cda7428dbb0268ea1de06fd43e08681e7a02232d9c0f57a1df'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_hwh(path):
    ranges = [n.attrib for n in ET.parse(str(path)).iter('MEMRANGE')
              if n.attrib.get('INSTANCE') == 'car_rx_0']
    if len(ranges) != 1 or int(ranges[0]['BASEVALUE'], 0) != BASE or int(ranges[0]['HIGHVALUE'], 0) != BASE + 65535:
        raise RuntimeError('CAR1 HWH address/range mismatch')


class CarUART:
    def __init__(self, bit, program=False):
        from pynq import Bitstream, MMIO, Clocks, PL
        bit = Path(bit).resolve()
        validate_hwh(bit.with_suffix('.hwh'))
        loaded = Path(PL.bitfile_name) if PL.bitfile_name else None
        loaded_hash = digest(loaded) if loaded and loaded.is_file() else None
        matching = loaded_hash == digest(bit)
        if matching:
            matching = loaded.with_suffix('.hwh').is_file() and digest(loaded.with_suffix('.hwh')) == digest(bit.with_suffix('.hwh'))
        if not matching and not program:
            raise RuntimeError('Matching CAR1 overlay not loaded; use explicit --program after stopping other applications')
        if program:
            if loaded_hash in KNOWN_SBB:
                old = MMIO(0x43c00000, 16384)
                dma = MMIO(0x40400000, 65536)
                if old.read(4) & 4 or not (dma.read(4) & 1 and dma.read(0x34) & 1):
                    raise RuntimeError('Save/ACK SBB evidence and halt both DMA channels before replacing PL')
                if old.read(0xfc) == 0x35424253 and old.read(4) & 1 and not old.read(4) & 256:
                    raise RuntimeError('Stop the previous SBB5 source before replacing PL')
            elif matching:
                old = MMIO(BASE, 65536)
                if old.read(0) & 1 or old.read(12):
                    raise RuntimeError('Existing CAR1 receiver or buffered data must be handled before programming')
            Clocks.fclk0_mhz = 100
            Bitstream(str(bit)).download()
        if not 99 <= float(Clocks.fclk0_mhz) <= 101:
            raise RuntimeError('Expected 100MHz FCLK0')
        self.mmio = MMIO(BASE, 65536)
        if self.mmio.read(0xfc) != ID:
            raise RuntimeError('CAR1 ID mismatch')
        r = self.registers()
        if (r['clock_hz'], r['baud'], r['fifo_bytes']) != (100000000, 115200, 4096):
            raise RuntimeError('CAR1 clock/baud/FIFO mismatch')
        self.provenance = dict(bit_sha256=digest(bit), hwh_sha256=digest(bit.with_suffix('.hwh')),
                               overlay_id=ID, fclk0_mhz=float(Clocks.fclk0_mhz), pin='PMODA1/Y18', receive_only=True)

    def registers(self):
        return {name: int(self.mmio.read(offset)) for name, offset in REGS.items()}

    def start(self):
        if self.mmio.read(0) & 1 or self.mmio.read(12):
            raise RuntimeError('Receiver must be stopped and FIFO empty before starting a new capture')
        self.mmio.write(0, 2)  # Explicit empty/stopped new session; never clear an active receiver.
        self.mmio.write(0, 1)

    def read(self):
        count = min(int(self.mmio.read(12)), 4096)
        return bytes(int(self.mmio.read(8)) & 255 for _ in range(count))

    def stop(self):
        self.mmio.write(0, 0)


def capture(output, seconds=60, bit=None, program=False, replay=None, hardware_factory=CarUART):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    parser = TelemetryParser()
    board = None
    began = time.monotonic()
    report = dict(status='RUNNING', format='CAR-TLM1', hardware_accessed=replay is None,
                  created_utc=datetime.now(timezone.utc).isoformat(), utc_source='host_clock_not_independently_verified',
                  source='offline_raw_replay' if replay is not None else 'external_UART_not_independently_attributed',
                  car_application_acceptance=False)
    error = None
    raw_hash = hashlib.sha256()
    try:
        with (output / 'raw.bin').open('wb') as raw, (output / 'records.jsonl').open('w', encoding='utf-8') as records:
            def consume(data):
                raw.write(data)
                raw_hash.update(data)
                for row in parser.feed(data):
                    row['host_elapsed_seconds'] = time.monotonic() - began
                    records.write(json.dumps(row, sort_keys=True) + '\n')
            if replay is not None:
                with Path(replay).open('rb') as stream:
                    while True:
                        data = stream.read(4096)
                        if not data:
                            break
                        consume(data)
            else:
                board = hardware_factory(bit, program)
                report['provenance'] = board.provenance
                board.start()
                capture_began = time.monotonic()
                try:
                    while time.monotonic() - capture_began < seconds:
                        data = board.read()
                        if data:
                            consume(data)
                        else:
                            time.sleep(.002)
                finally:
                    board.stop()
                    for _ in range(16):
                        data = board.read()
                        if not data:
                            break
                        consume(data)
                    report['hardware_registers'] = board.registers()
                    report['capture_seconds'] = time.monotonic() - capture_began
            for stream in (raw, records):
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException as exc:
        error = exc
        report['error'] = type(exc).__name__ + ': ' + str(exc)
    report['elapsed_seconds'] = time.monotonic() - began
    report['parser'] = parser.summary()
    report['raw_sha256'] = raw_hash.hexdigest()
    good = report['parser']['transport_integrity_observed'] and error is None
    try:
        stored_hash = hashlib.sha256()
        with (output / 'raw.bin').open('rb') as stream:
            while True:
                data = stream.read(1024 * 1024)
                if not data:
                    break
                stored_hash.update(data)
        report['raw_readback_sha256'] = stored_hash.hexdigest()
        good = good and report['raw_readback_sha256'] == report['raw_sha256']
    except OSError as exc:
        good = False
        report['readback_error'] = str(exc)
    if board is not None:
        r = report.get('hardware_registers', {})
        good = good and bool(r) and not r.get('overflows', 1) and not r.get('framing_errors', 1)
        good = good and r.get('level', 1) == 0 and r.get('control', 1) == 0
        good = good and r.get('received', -1) == r.get('consumed', -2) + r.get('overflows', 0)
        good = good and r.get('consumed', -1) == parser.stats['bytes_seen']
    report['status'] = 'PASS' if good else 'FAIL'
    path = output / 'report.json'
    with path.open('w', encoding='utf-8') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    if error is not None:
        raise error
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bit', type=Path, default=Path('firmware/car_uart_rx.bit'))
    parser.add_argument('--program', action='store_true')
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--replay', type=Path)
    args = parser.parse_args()
    if not 0 < args.seconds <= 3600:
        parser.error('--seconds must be in (0, 3600]')
    if args.replay is not None:
        result = capture(args.output, replay=args.replay)
    else:
        from pynq_hardware_lease import HardwareLease
        with HardwareLease():
            result = capture(args.output, args.seconds, args.bit, args.program)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
