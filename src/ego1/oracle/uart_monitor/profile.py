"""Validated declarative protocol profiles; no hardware access or expression eval."""
import copy
import json
import math
from pathlib import Path
import struct
import zlib

TYPES = {'u8': 'B', 'i8': 'b', 'u16': 'H', 'i16': 'h', 'u32': 'I', 'i32': 'i',
         'u64': 'Q', 'i64': 'q', 'float32': 'f'}
BAUDS = (9600, 19200, 38400, 57600, 115200)
CHECKSUMS = ('none', 'xor8', 'sum8', 'crc16_modbus', 'crc32_iso_hdlc')


def checksum(data, kind):
    if kind == 'none':
        return None
    if kind == 'crc32_iso_hdlc':
        return zlib.crc32(data) & 0xffffffff
    if kind == 'sum8':
        return sum(data) & 255
    if kind == 'xor8':
        value = 0
        for byte in data:
            value ^= byte
        return value
    if kind == 'crc16_modbus':
        value = 0xffff
        for byte in data:
            value ^= byte
            for _ in range(8):
                value = (value >> 1) ^ (0xa001 if value & 1 else 0)
        return value
    raise ValueError('Unknown checksum: ' + str(kind))


def load_profile(source):
    if isinstance(source, dict):
        profile = copy.deepcopy(source)
    else:
        profile = json.loads(Path(source).read_text(encoding='utf-8'),
                             parse_constant=lambda v: (_ for _ in ()).throw(ValueError('Nonfinite JSON: '+v)))
    if profile.get('profile_version') != 1 or not isinstance(profile.get('id'), str) or not profile['id']:
        raise ValueError('Expected profile_version=1 and nonempty id')
    transport = profile.setdefault('transport', {})
    if transport.setdefault('baud', 115200) not in BAUDS or transport.setdefault('format', '8N1') != '8N1':
        raise ValueError('Unsupported UART settings')
    framing = profile['framing']
    kind = framing['kind']
    if kind not in ('binary', 'text'):
        from .decoder import DECODERS
        if kind not in DECODERS:raise ValueError('Use a registered decoder for other framing kinds')
        return DECODERS[kind][1](profile)
    if kind == 'binary':
        length = framing['length']
        sync = bytes.fromhex(framing['sync'])
        if not isinstance(length, int) or not 1 <= length <= 512 or not 1 <= len(sync) <= length:
            raise ValueError('Invalid fixed binary length/sync')
        for constant in framing.get('constants', []):
            data = bytes.fromhex(constant['hex'])
            if not 0 <= constant['offset'] <= length-len(data):
                raise ValueError('Constant outside frame')
    else:
        if not 1 <= framing.setdefault('max_length', 512) <= 512:
            raise ValueError('Text line maximum is 512 bytes')
        for key in ('prefix', 'separator'):
            framing[key].encode('ascii')
        if len(framing['separator']) != 1:
            raise ValueError('Text separator must be one ASCII character')
    check = profile.setdefault('checksum', {'kind': 'none'})
    if check['kind'] not in CHECKSUMS:
        raise ValueError('Unsupported checksum')
    if check['kind'] != 'none':
        if kind == 'binary':
            width = {'xor8': 1, 'sum8': 1, 'crc16_modbus': 2, 'crc32_iso_hdlc': 4}[check['kind']]
            if not 0 <= check['start'] < check['end'] <= length or not 0 <= check['offset'] <= length-width:
                raise ValueError('Checksum range/offset outside frame')
            if check.setdefault('byte_order', 'little') not in ('little', 'big'):
                raise ValueError('Checksum byte order')
        else:
            if check.setdefault('delimiter', '*') != '*':
                raise ValueError('v1 text checksum delimiter is *')
            if check.setdefault('start', 1) < 0:
                raise ValueError('Text checksum start')
    fields = profile['fields']
    names = [f['name'] for f in fields]
    if not fields or len(set(names)) != len(names) or not all(isinstance(n, str) and n for n in names):
        raise ValueError('Fields need unique nonempty names')
    for field in fields:
        if field['type'] not in TYPES or field.setdefault('byte_order', 'little') not in ('little', 'big'):
            raise ValueError('Field type/byte order')
        if not math.isfinite(float(field.setdefault('scale', 1))) or not math.isfinite(float(field.setdefault('bias', 0))):
            raise ValueError('Field scale/bias must be finite')
        if kind == 'binary' and not 0 <= field['offset'] <= length-struct.calcsize(TYPES[field['type']]):
            raise ValueError('Field outside frame: ' + field['name'])
        if kind == 'text' and (not isinstance(field['column'], int) or not 0 <= field['column'] < 64):
            raise ValueError('Text column outside supported bounds')
        validity = field.get('valid_when')
        if validity and (validity['field'] not in names or validity['mask'] < 0):
            raise ValueError('Invalid validity reference')
        if 'min' in field and 'max' in field and field['min'] > field['max']:
            raise ValueError('Reversed field bounds')
    by_name={f['name']:f for f in fields}
    for field in fields:
        condition=field.get('valid_when')
        if condition and (by_name[condition['field']]['type']=='float32' or not isinstance(condition.get('equals'),int)):
            raise ValueError('Validity flag must reference an integer field and equality')
    sequence = profile.get('sequence')
    if sequence:
        if sequence['field'] not in names or not 1 <= sequence.setdefault('bits', 32) <= 64:
            raise ValueError('Invalid sequence definition')
        if sequence.get('time_field') and sequence['time_field'] not in names:
            raise ValueError('Invalid device time reference')
        if not 1 <= sequence.setdefault('time_bits', 32) <= 64:
            raise ValueError('Invalid device time width')
        if not by_name[sequence['field']]['type'].startswith('u'):
            raise ValueError('Sequence field must be unsigned integer')
        if sequence.get('time_field') and not by_name[sequence['time_field']]['type'].startswith('u'):
            raise ValueError('Device time field must be unsigned integer')
    for key, name in profile.get('health', {}).items():
        if key.endswith('_field') and name not in names:
            raise ValueError('Invalid health field: ' + name)
    ids = set()
    for rule in profile.setdefault('rules', []):
        if rule['id'] in ids or rule['field'] not in names or rule['kind'] not in ('range', 'compare', 'bits', 'invalid'):
            raise ValueError('Invalid rule/id/field')
        ids.add(rule['id'])
        if rule['kind'] == 'compare' and rule.get('op') not in ('lt', 'le', 'gt', 'ge', 'eq', 'ne'):
            raise ValueError('Unsupported comparison')
        if not 0 <= rule.setdefault('duration_ms', 100 if rule['kind']=='range' else 0) <= 3600000:
            raise ValueError('Rule duration out of range')
        required = {'range': ('min', 'max'), 'compare': ('value',), 'bits': ('mask','equals'), 'invalid': ()}[rule['kind']]
        if any(k not in rule for k in required):
            raise ValueError('Missing rule operand')
        if any(not isinstance(rule[k],(int,float)) or not math.isfinite(rule[k]) for k in required):
            raise ValueError('Rule operands must be finite numbers')
        if rule['kind']=='bits' and (by_name[rule['field']]['type']=='float32' or not isinstance(rule['mask'],int) or not isinstance(rule['equals'],int)):
            raise ValueError('Bit rules require integer operands and fields')
        if rule['kind']=='range' and rule['min']>rule['max']:
            raise ValueError('Reversed rule range')
    timing = profile.setdefault('timing', {})
    if not 1 <= timing.setdefault('valid_frame_timeout_ms', 250) <= 3600000:
        raise ValueError('Frame timeout out of range')
    evidence = profile.setdefault('evidence', {})
    if evidence.setdefault('mode','single') not in ('single','continuous'):
        raise ValueError('Unsupported evidence mode')
    for key,default,maximum in (('max_pending',8,32),('max_windows',100,1000)):
        if type(evidence.setdefault(key,default)) is not int or not 1<=evidence[key]<=maximum:
            raise ValueError('Invalid evidence capacity: '+key)
    for key in ('pre_seconds', 'post_seconds'):
        if not 0 <= evidence.setdefault(key, 5) <= 60:
            raise ValueError('Evidence window must be 0..60 seconds')
    # Ensure arbitrary dictionaries cannot smuggle nonfinite constants into archived JSON.
    if 'analysis' in profile:
        from .behavior import validate_analysis
        validate_analysis(profile)
    json.dumps(profile, allow_nan=False)
    return profile
