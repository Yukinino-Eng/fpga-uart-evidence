"""URX1 hardware driver and an explicitly labelled file-replay transport."""
import hashlib
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
from .decoder import ByteChunk

BASE=0x43c10000
IDENTITY=0x31585255
HZ=100000000
REGISTERS=dict(control=0,status=4,level=12,received=16,consumed=20,overflows=24,
               framing_errors=28,clock_hz=32,baud=36,fifo_entries=40,session=44,
               abi=48,capabilities=52,divisor=72)
CAR1_SHA='6ca2e46a2dd09da1ad7fd682d01472cd60b4c8bac12c716991fe88d01bc1cbce'
SBB_SHAS={'625806bf59309fb2b8e715efacd2cfceca0c987b28ff83f3f30bb065746ae0a8',
          '76de1af2670892cda7428dbb0268ea1de06fd43e08681e7a02232d9c0f57a1df'}


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(65536),b''):h.update(block)
    return h.hexdigest()


def validate_hwh(path):
    ranges=[x.attrib for x in ET.parse(str(path)).iter('MEMRANGE') if x.attrib.get('INSTANCE')=='uart_rx_0']
    if len(ranges)!=1 or int(ranges[0]['BASEVALUE'],0)!=BASE or int(ranges[0]['HIGHVALUE'],0)!=BASE+65535:
        raise ValueError('URX1 HWH address/range mismatch')


class Transport:
    hardware_accessed=True
    supports_buffered_capture=True
    def __init__(self, bit, profile, program=False):
        from pynq import Bitstream, MMIO, Clocks, PL
        self.bit=Path(bit).resolve()
        validate_hwh(self.bit.with_suffix('.hwh'))
        loaded=Path(PL.bitfile_name) if PL.bitfile_name else None
        loaded_hash=digest(loaded) if loaded and loaded.is_file() else None
        matching=loaded_hash==digest(self.bit)
        matching=matching and loaded.with_suffix('.hwh').is_file() and digest(loaded.with_suffix('.hwh'))==digest(self.bit.with_suffix('.hwh'))
        if program:
            if matching or loaded_hash==CAR1_SHA:
                old=MMIO(BASE,65536)
                if old.read(0)&1 or old.read(12):raise RuntimeError('Preserve active receiver/buffered data before programming')
            elif loaded_hash in SBB_SHAS:
                old=MMIO(0x43c00000,16384);dma=MMIO(0x40400000,65536)
                if old.read(4)&4 or not(dma.read(4)&1 and dma.read(0x34)&1):
                    raise RuntimeError('Save SBB event and halt both DMA channels first')
                if old.read(0xfc)==0x35424253 and old.read(4)&1 and not old.read(4)&256:
                    raise RuntimeError('Stop SBB5 source before replacing PL')
            else:
                raise RuntimeError('Unknown loaded overlay; cannot prove it is idle')
            Clocks.fclk0_mhz=100
            Bitstream(str(self.bit)).download()
        elif not matching:
            raise RuntimeError('URX1 is not loaded; use explicit program after saving/stopping previous application')
        if not 99<=float(Clocks.fclk0_mhz)<=101:raise RuntimeError('Expected 100MHz FCLK0')
        self.mmio=MMIO(BASE,65536)
        r=self.registers()
        if self.mmio.read(0xfc)!=IDENTITY or r['abi']>>16!=1 or r['capabilities']&7!=7:
            raise RuntimeError('Incompatible URX1 identity/ABI/capabilities')
        if r['clock_hz']!=HZ or r['fifo_entries']!=4096:raise RuntimeError('Unexpected URX1 clock/FIFO')
        self.baud=profile['transport']['baud']
        self.offset=0
        self.last_tick=None
        self.provenance=dict(bit_sha256=digest(self.bit),hwh_sha256=digest(self.bit.with_suffix('.hwh')),
                             overlay_id=IDENTITY,abi=r['abi'],capabilities=r['capabilities'],
                             timestamp_source='URX1_fifo_enqueue_100MHz_ticks',receive_only=True,
                             clock_hz=HZ,pin='PMODA1/Y18',reprogrammed=bool(program))

    def registers(self):return {k:int(self.mmio.read(v)) for k,v in REGISTERS.items()}

    def now_ticks(self):
        low=int(self.mmio.read(0x40));high=int(self.mmio.read(0x44))
        return (high<<32)|low

    def start(self):
        if self.mmio.read(0)&1 or self.mmio.read(12):raise RuntimeError('Receiver must be stopped and empty')
        self.mmio.write(0x24,self.baud)
        if self.mmio.read(0x24)!=self.baud:raise RuntimeError('Baud configuration readback failed')
        self.mmio.write(0,2)
        self.offset=0;self.last_tick=None
        began=self.now_ticks()
        self.mmio.write(0,1)
        self.stopped_ticks=None
        return began

    def read(self, maximum=256):
        count=min(int(self.mmio.read(12)),maximum)
        data=bytearray();ticks=[]
        read=self.mmio.read
        for _ in range(count):
            value=int(read(8))
            if not value&0x80000000:raise RuntimeError('Invalid FIFO pop; possible concurrent reader')
            low=int(read(0x38));high=int(read(0x3c));tick=(high<<32)|low
            if self.last_tick is not None and tick<self.last_tick:raise RuntimeError('Hardware timestamp regressed')
            self.last_tick=tick;data.append(value&255);ticks.append(tick)
        state=self.registers()
        result=ByteChunk(data,ticks,self.offset,state)
        self.offset+=len(data)
        return result

    def stop(self):
        self.mmio.write(0,0)
        self.stopped_ticks=self.now_ticks()
    def close(self):pass


class ReplayTransport:
    hardware_accessed=False
    def __init__(self, raw, profile, timestamps=None):
        self.raw=Path(raw).open('rb')
        self.index=Path(timestamps).open('rb') if timestamps else None
        self.profile=profile;self.offset=0;self.tick=0;self.eof=False
        if timestamps and Path(timestamps).stat().st_size!=Path(raw).stat().st_size*8:
            self.close();raise ValueError('Timestamp index length must be 8 bytes per raw byte')
        self.provenance=dict(timestamp_source='recorded_hardware_index' if timestamps else 'synthetic_wire_time_for_replay_only',
                             raw_source_sha256=digest(raw),hardware_accessed=False)
    def start(self):
        if self.index:
            first=self.index.read(8);self.index.seek(0)
            if first:self.tick=struct.unpack('<Q',first)[0]
        return self.tick
    def read(self, maximum=256):
        data=self.raw.read(maximum)
        self.eof=not data
        ticks=list(struct.unpack('<'+'Q'*len(data),self.index.read(len(data)*8))) if self.index and data else [int((self.offset+n+1)*10*HZ/self.profile['transport']['baud']) for n in range(len(data))]
        if ticks:
            if ticks[0]<self.tick:raise ValueError('Replay timestamp index regressed')
            self.tick=ticks[-1]
        chunk=ByteChunk(data,ticks,self.offset,dict(level=0,overflows=0,framing_errors=0))
        self.offset+=len(data)
        return chunk
    def now_ticks(self):return self.tick
    def stop(self):pass
    def registers(self):return dict(control=0,level=0,overflows=0,framing_errors=0,received=self.offset,consumed=self.offset)
    def close(self):
        self.raw.close()
        if self.index:self.index.close()
