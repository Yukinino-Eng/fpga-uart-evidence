"""Byte-level framing and protocol fields, independent of PYNQ and device control."""
import math
import struct
from .profile import TYPES, checksum, load_profile


class ByteChunk:
    def __init__(self, data, ticks, raw_offset=0, state=None):
        self.data = bytes(data)
        self.ticks = tuple(ticks)
        self.raw_offset = raw_offset
        self.state = state or {}
        if len(self.data) != len(self.ticks) or raw_offset < 0:
            raise ValueError('Each raw byte needs one timestamp and a nonnegative offset')
        if any(t < 0 or t >= 1 << 64 for t in self.ticks) or any(b<a for a,b in zip(self.ticks,self.ticks[1:])):
            raise ValueError('Invalid or decreasing hardware time')


DECODERS = {}


def register_decoder(name, factory, validator):
    """Explicit code registration; JSON profiles cannot import executable code."""
    if name in DECODERS or name in ('binary','text'):
        raise ValueError('Decoder already registered')
    if not callable(factory) or not callable(validator):raise ValueError('Factory and profile validator required')
    DECODERS[name] = (factory,validator)


class Decoder:
    def __init__(self, profile):
        self.profile = load_profile(profile)
        self.buffer = bytearray()
        self.times = []
        self.base = 0
        self.previous = None
        self.drop_line = False
        self.noise = None
        self.stats = dict(bytes_seen=0, frames=0, discarded_bytes=0, interframe_discarded_bytes=0,
                          header_errors=0, crc_errors=0, semantic_errors=0, sequence_missing=0,
                          duplicates=0, restart_or_out_of_order=0, imu_invalid_frames=0,
                          max_imu_age_ms=0, max_car_tx_skipped=0)

    def _discard(self, count):
        self.stats['discarded_bytes'] += count
        if self.stats['frames']:
            self.stats['interframe_discarded_bytes'] += count
            if count:
                if self.noise is None:self.noise=dict(kind='interframe_noise',raw_offset=self.base,count=0,ticks=0)
                self.noise['count']+=count;self.noise['ticks']=self.times[count-1]
        self._remove(count)

    def finish(self):
        issues=[]
        self._flush_noise(issues)
        return issues

    def _flush_noise(self,issues):
        if self.noise is not None:
            issues.append(self.noise);self.noise=None

    def _remove(self, count):
        del self.buffer[:count]
        del self.times[:count]
        self.base += count

    def _issue(self, issues, kind, tick, **extra):
        self.stats[kind] += extra.get('count', 1)
        issues.append(dict(kind=kind, ticks=tick, raw_offset=self.base, **extra))

    def _fields(self, packet):
        raw = {}
        binary = self.profile['framing']['kind'] == 'binary'
        columns = None if binary else packet.decode('ascii').split(self.profile['framing']['separator'])
        for f in self.profile['fields']:
            if binary:
                raw[f['name']] = struct.unpack_from(('<' if f['byte_order']=='little' else '>') + TYPES[f['type']], packet, f['offset'])[0]
            else:
                token = columns[f['column']]
                value = float(token) if f['type']=='float32' else int(token,10)
                if f['type'] != 'float32':
                    struct.pack('<'+TYPES[f['type']], value)  # enforce signedness/width
                raw[f['name']] = value
        values, valid = {}, {}
        for f in self.profile['fields']:
            value = raw[f['name']]
            if not math.isfinite(value):
                raise ValueError('Nonfinite field')
            if 'min' in f and value < f['min'] or 'max' in f and value > f['max']:
                raise ValueError('Field bounds')
            if 'allowed_mask' in f and value & ~f['allowed_mask']:
                raise ValueError('Reserved bits')
            if any(value & x['mask'] in x['values'] for x in f.get('forbidden_mask_values', [])):
                raise ValueError('Forbidden bit combination')
            condition = f.get('valid_when')
            valid[f['name']] = not condition or raw[condition['field']] & condition['mask'] == condition['equals']
            if value in f.get('invalid_values', []):
                valid[f['name']] = False
            values[f['name']] = value * f['scale'] + f['bias'] if valid[f['name']] else None
            if values[f['name']] is not None and not math.isfinite(values[f['name']]):
                raise ValueError('Nonfinite converted field')
        return raw, values, valid

    def _accepted(self, packet, count, frames, issues):
        self._flush_noise(issues)
        tick = self.times[count-1]
        try:
            raw, fields, validity = self._fields(packet)
        except (ValueError, IndexError, struct.error, UnicodeError, OverflowError):
            self._issue(issues, 'semantic_errors', tick)
            self._remove(count)
            return
        frame = dict(raw_fields=raw, fields=fields, validity=validity,
                     units={f['name']:f.get('unit','') for f in self.profile['fields']},
                     raw_start=self.base, raw_end=self.base+count,
                     start_ticks=self.times[0], end_ticks=tick, profile_id=self.profile['id'])
        seq = self.profile.get('sequence')
        frame['sequence'] = raw[seq['field']] if seq else None
        frame['device_time'] = raw.get(seq.get('time_field')) if seq else None
        if seq and self.previous is not None:
            modulus = 1 << seq['bits']
            delta = (frame['sequence']-self.previous['sequence']) % modulus
            back = delta >= modulus//2
            if seq.get('time_field'):
                span = (frame['device_time']-self.previous['device_time']) % (1 << seq['time_bits'])
                back = back or span >= (1 << (seq['time_bits']-1))
            if back:
                self._issue(issues, 'restart_or_out_of_order', tick)
            elif delta == 0:
                self._issue(issues, 'duplicates', tick)
            elif delta > 1:
                self._issue(issues, 'sequence_missing', tick, count=delta-1)
        self.previous = frame
        health = self.profile.get('health', {})
        if health.get('valid_field') and raw[health['valid_field']] & health['valid_mask'] != health['valid_mask']:
            self.stats['imu_invalid_frames'] += 1
        if health.get('age_field'):
            self.stats['max_imu_age_ms'] = max(self.stats['max_imu_age_ms'], raw[health['age_field']])
        if health.get('tx_skipped_field'):
            self.stats['max_car_tx_skipped'] = max(self.stats['max_car_tx_skipped'], raw[health['tx_skipped_field']])
        self.stats['frames'] += 1
        frames.append(frame)
        self._remove(count)

    def feed(self, chunk):
        if chunk.raw_offset != self.stats['bytes_seen']:
            raise ValueError('Raw offset discontinuity')
        self.stats['bytes_seen'] += len(chunk.data)
        frames, issues = [], []
        # Bound buffering even for large malformed input chunks.
        for offset in range(0, len(chunk.data), 512):
            self.buffer.extend(chunk.data[offset:offset+512])
            self.times.extend(chunk.ticks[offset:offset+512])
            if self.profile['framing']['kind']=='binary':
                self._binary(frames, issues)
            else:
                self._text(frames, issues)
        return frames, issues

    def _binary(self, frames, issues):
        p = self.profile
        sync, length = bytes.fromhex(p['framing']['sync']), p['framing']['length']
        while self.buffer:
            index = self.buffer.find(sync)
            if index < 0:
                keep = max((n for n in range(1,len(sync)) if self.buffer[-n:]==sync[:n]), default=0)
                self._discard(len(self.buffer)-keep)
                break
            if index:
                self._discard(index)
            if len(self.buffer) < len(sync):
                break
            bad_header = False
            for c in p['framing'].get('constants', []):
                expected = bytes.fromhex(c['hex'])
                end = c['offset']+len(expected)
                if len(self.buffer)>=end and self.buffer[c['offset']:end] != expected:
                    self._issue(issues,'header_errors',self.times[min(end-1,len(self.times)-1)])
                    self._discard(1)
                    bad_header = True
                    break
            if bad_header:
                continue
            if len(self.buffer) < length:
                break
            packet = bytes(self.buffer[:length])
            c = p['checksum']
            if c['kind']!='none':
                width = {'xor8':1,'sum8':1,'crc16_modbus':2,'crc32_iso_hdlc':4}[c['kind']]
                actual = int.from_bytes(packet[c['offset']:c['offset']+width],c['byte_order'])
                if checksum(packet[c['start']:c['end']],c['kind']) != actual:
                    self._issue(issues,'crc_errors',self.times[length-1])
                    self._discard(1)
                    continue
            self._accepted(packet,length,frames,issues)

    def _text(self, frames, issues):
        p = self.profile
        maximum = p['framing']['max_length']
        while self.buffer:
            index = self.buffer.find(b'\n')
            if self.drop_line:
                count = len(self.buffer) if index<0 else index+1
                self._discard(count)
                if index<0:
                    break
                self.drop_line=False
                continue
            if index<0:
                if len(self.buffer)>maximum:
                    self._issue(issues,'header_errors',self.times[maximum])
                    self.drop_line=True
                    self._discard(len(self.buffer))
                break
            count=index+1
            packet=bytes(self.buffer[:count]).rstrip(b'\r\n')
            if count>maximum or not packet.startswith(p['framing']['prefix'].encode('ascii')):
                self._issue(issues,'header_errors',self.times[count-1]);self._discard(count);continue
            c=p['checksum']
            if c['kind']!='none':
                try:
                    body, encoded=packet.rsplit(b'*',1)
                    digits={'xor8':2,'sum8':2,'crc16_modbus':4,'crc32_iso_hdlc':8}[c['kind']]
                    if len(encoded)!=digits or any(ch not in b'0123456789abcdefABCDEF' for ch in encoded):
                        raise ValueError('Checksum encoding')
                    if checksum(body[c['start']:],c['kind'])!=int(encoded,16):
                        raise ValueError('Checksum mismatch')
                    packet=body
                except ValueError:
                    self._issue(issues,'crc_errors',self.times[count-1]);self._discard(count);continue
            self._accepted(packet,count,frames,issues)

    def summary(self):
        result=dict(self.stats)
        result['trailing_partial_bytes']=len(self.buffer)
        failed=('header_errors','crc_errors','semantic_errors','sequence_missing','duplicates',
                'restart_or_out_of_order','interframe_discarded_bytes','max_car_tx_skipped')
        result['transport_integrity_observed']=bool(result['frames']) and not any(result[k] for k in failed)
        result['checksum_available']=self.profile['checksum']['kind']!='none'
        result['sequence_available']=bool(self.profile.get('sequence'))
        return result


def make_decoder(profile):
    kind = profile['framing']['kind']
    return DECODERS[kind][0](profile) if kind in DECODERS else Decoder(profile)
