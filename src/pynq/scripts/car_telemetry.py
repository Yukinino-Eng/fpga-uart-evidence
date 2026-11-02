"""CAR-TLM1 fixed 48-byte telemetry codec/parser (Python 3.6+, no PYNQ import)."""
import struct
import zlib

SYNC = b'\xa5\x5a'
VERSION = 1
FRAME_BYTES = 48
BODY = struct.Struct('<2sBBIIIiiiiHHHHHH')
FIELDS = ('sequence', 'uptime_ms', 'imu_sample_count', 'pitch_mdeg', 'rate_mdps',
          'encoder_e1', 'encoder_e2', 'pwm_a_counts', 'pwm_b_counts', 'flags',
          'fault_code', 'tx_skipped', 'imu_age_ms')


def encode_frame(values):
    """Host fixture/reference encoder; this does not implement the car driver."""
    body = BODY.pack(SYNC, VERSION, FRAME_BYTES, *(values[k] for k in FIELDS))
    return body + struct.pack('<I', zlib.crc32(body) & 0xffffffff)


def decode_frame(data):
    if len(data) != FRAME_BYTES or data[:4] != SYNC + bytes((VERSION, FRAME_BYTES)):
        raise ValueError('CAR-TLM1 header/size mismatch')
    if zlib.crc32(data[:44]) & 0xffffffff != struct.unpack_from('<I', data, 44)[0]:
        raise ValueError('CAR-TLM1 CRC mismatch')
    row = dict(zip(FIELDS, BODY.unpack(data[:44])[3:]))
    if row['pwm_a_counts'] > 400 or row['pwm_b_counts'] > 400:
        raise ValueError('PWM counts exceed current TIM3 ARR+1=400')
    if row['flags'] & ~0xf1ff or ((row['flags'] >> 5) & 3) == 3:
        raise ValueError('Reserved CAR-TLM1 flag bits/mode')
    return row


class TelemetryParser:
    def __init__(self):
        self.buffer = bytearray()
        self.previous = None
        self.stats = dict(bytes_seen=0, frames=0, discarded_bytes=0, interframe_discarded_bytes=0, header_errors=0,
                          crc_errors=0, semantic_errors=0, sequence_missing=0,
                          duplicates=0, restart_or_out_of_order=0, imu_invalid_frames=0,
                          max_imu_age_ms=0, max_car_tx_skipped=0)

    def discard(self, count):
        self.stats['discarded_bytes'] += count
        if self.stats['frames']:
            self.stats['interframe_discarded_bytes'] += count
        del self.buffer[:count]

    def feed(self, chunk):
        self.stats['bytes_seen'] += len(chunk)
        self.buffer.extend(chunk)
        rows = []
        while True:
            index = self.buffer.find(SYNC)
            if index < 0:
                keep = 1 if self.buffer[-1:] == SYNC[:1] else 0
                remove = len(self.buffer) - keep
                self.discard(remove)
                break
            if index:
                self.discard(index)
            if len(self.buffer) < 4:
                break
            if self.buffer[2] != VERSION or self.buffer[3] != FRAME_BYTES:
                self.stats['header_errors'] += 1
                self.discard(1)
                continue
            if len(self.buffer) < FRAME_BYTES:
                break
            packet = bytes(self.buffer[:FRAME_BYTES])
            if zlib.crc32(packet[:44]) & 0xffffffff != struct.unpack_from('<I', packet, 44)[0]:
                self.stats['crc_errors'] += 1
                self.discard(1)
                continue
            del self.buffer[:FRAME_BYTES]
            try:
                row = decode_frame(packet)
            except ValueError:
                self.stats['semantic_errors'] += 1
                continue
            if self.previous is not None:
                delta = (row['sequence'] - self.previous['sequence']) & 0xffffffff
                elapsed = (row['uptime_ms'] - self.previous['uptime_ms']) & 0xffffffff
                if elapsed >= 0x80000000 or delta >= 0x80000000:
                    self.stats['restart_or_out_of_order'] += 1
                elif delta == 0:
                    self.stats['duplicates'] += 1
                elif delta > 1:
                    self.stats['sequence_missing'] += delta - 1
            self.previous = row
            self.stats['frames'] += 1
            if not (row['flags'] & 3) == 3:
                self.stats['imu_invalid_frames'] += 1
            self.stats['max_imu_age_ms'] = max(self.stats['max_imu_age_ms'], row['imu_age_ms'])
            self.stats['max_car_tx_skipped'] = max(self.stats['max_car_tx_skipped'], row['tx_skipped'])
            rows.append(row)
        return rows

    def summary(self):
        result = dict(self.stats)
        result['trailing_partial_bytes'] = len(self.buffer)
        faults = ('header_errors', 'crc_errors', 'semantic_errors', 'sequence_missing', 'interframe_discarded_bytes',
                  'duplicates', 'restart_or_out_of_order', 'max_car_tx_skipped')
        result['transport_integrity_observed'] = result['frames'] > 0 and not any(result[k] for k in faults)
        result['edge_trim_note'] = 'Capture can begin/end inside a frame; raw bytes are retained. No claims about frames outside this capture.'
        return result
