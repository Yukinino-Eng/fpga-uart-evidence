"""URX2 transport and event bridge. Hardware access is explicit; RTL replay is labelled offline."""
import hashlib
import json
from pathlib import Path
import time
from .hardware import compile_profile,adapt_event,ID
from .transport import Transport,ReplayTransport,BASE,REGISTERS,digest,validate_hwh,CAR1_SHA,SBB_SHAS
from .rules import RuleEngine
from .profile import load_profile

EXTRA=dict(event_level=0x100,event_overflows=0x104,event_received=0x10c,event_consumed=0x170,
           hardware_frames=0x174,hardware_crc_errors=0x178,hardware_semantic_errors=0x17c,
           parser_overflows=0x188,parser_buffered=0x18c,hardware_active=0x190,
           hardware_missing=0x194,hardware_duplicates=0x198,hardware_restarts=0x19c,
           hardware_discarded=0x1a0,event_entries=0x1a4,configuration=0x1f0,detector_enabled=0x1f4)
URX1_SHA='9b218d76465c90d5c09f5a3d162d840da904f68e1caa100c93da1f4697efe2d6'
KNOWN_URX2_SHAS={'5bd7937d8965397b87de2bcffde3d72adae594b6272cee7bb7a6862510189a70',
                 '24870758d42c9abcbf5bf7ffc631dfbfb8de886d512fd5d10e403cfdfae4106f'}


def unpack_event(w):
    if len(w)!=24:raise ValueError('URX2 event record needs 24 words')
    return dict(mask=w[0],batch_id=w[1],ticks=w[2]|w[3]<<32,raw_start=w[4],raw_end=w[5],
                start_ticks=w[6]|w[7]<<32,last_valid_ticks=w[8]|w[9]<<32,missing=w[10],sequence=w[11],
                values=w[12:20],semantic_mask=w[20],frame_end_ticks=w[21]|w[22]<<32)


class URX2Transport(Transport):
    detection_source='fpga'
    def __init__(self,bit,profile,program=False):
        self.compiled=compile_profile(profile) if self.detection_source=='fpga' else None
        self.profile=self.compiled['profile'] if self.compiled else load_profile(profile)
        from pynq import Bitstream,MMIO,Clocks,PL
        self.bit=Path(bit).resolve();validate_hwh(self.bit.with_suffix('.hwh'))
        loaded=Path(PL.bitfile_name) if PL.bitfile_name else None
        old=digest(loaded) if loaded and loaded.is_file() else None
        matching=old==digest(self.bit)
        matching=matching and loaded.with_suffix('.hwh').is_file() and digest(loaded.with_suffix('.hwh'))==digest(self.bit.with_suffix('.hwh'))
        if program:
            if matching or old in (URX1_SHA,CAR1_SHA) or old in KNOWN_URX2_SHAS:
                previous=MMIO(BASE,65536)
                expected_id=ID if matching or old in KNOWN_URX2_SHAS else 0x31585255 if old==URX1_SHA else 0x31524143
                if previous.read(0xfc)!=expected_id:raise RuntimeError('Loaded-overlay metadata and actual hardware ID disagree')
                if previous.read(0)&1 or previous.read(12):raise RuntimeError('Save and drain active/buffered receiver first')
                if (matching or old in KNOWN_URX2_SHAS) and (previous.read(0x100) or previous.read(0x190)&256):
                    raise RuntimeError('Save/drain hardware events and wait for detector before programming')
            elif old in SBB_SHAS:
                previous=MMIO(0x43c00000,16384);dma=MMIO(0x40400000,65536)
                if previous.read(4)&4 or not(dma.read(4)&1 and dma.read(0x34)&1):raise RuntimeError('Save SBB event and halt DMA first')
                if previous.read(0xfc)==0x35424253 and previous.read(4)&1 and not previous.read(4)&256:
                    raise RuntimeError('Stop SBB5 before replacing PL')
            else:raise RuntimeError('Unknown loaded overlay; cannot prove it idle')
            Clocks.fclk0_mhz=100;Bitstream(str(self.bit)).download()
        elif not matching:raise RuntimeError('URX2 is not loaded; explicit program is required after preserving previous application')
        if abs(float(Clocks.fclk0_mhz)-100.0)>.001:raise RuntimeError('URX2 requires nominal 100MHz FCLK0')
        self.mmio=MMIO(BASE,65536)
        if self.mmio.read(0xfc)!=ID or self.mmio.read(0x30)!=0x20000 or self.mmio.read(0x34)&0x1ff!=0x1ff:
            raise RuntimeError('URX2 ID/ABI/capability mismatch')
        if self.mmio.read(0x20)!=100000000 or self.mmio.read(0x28)!=4096 or self.mmio.read(0x1a4)!=64:
            raise RuntimeError('URX2 clock or FIFO contract mismatch')
        self.baud=self.profile['transport']['baud'];self.offset=0;self.last_tick=None;self.pending=[]
        self.background_sync=bool(self.mmio.read(0x34)&0x200)
        self.provenance=dict(bit_sha256=digest(self.bit),hwh_sha256=digest(self.bit.with_suffix('.hwh')),
             overlay_id=ID,abi=0x20000,capabilities=self.mmio.read(0x34),detection_source=self.detection_source,
             timestamp_source='URX2_100MHz_relative_hardware_counter',receive_only=True,clock_hz=100000000,
             pin='PMODA1/Y18',reprogrammed=bool(program),
             uart_sync_policy='free_running_capture_gate' if self.background_sync else 'legacy_reset_on_capture',
             config_sha256=hashlib.sha256(json.dumps(self.compiled['words']).encode('ascii')).hexdigest() if self.compiled else None)

    def registers(self):
        result={name:int(self.mmio.read(offset)) for name,offset in dict(REGISTERS,**EXTRA).items()}
        result['host_pending_events']=len(getattr(self,'pending',[]))
        return result

    def start(self):
        state=self.registers()
        if state['control']&1 or state['level'] or state['event_level'] or state['hardware_active']&256:
            raise RuntimeError('Preserve active receiver, raw FIFO and event FIFO before starting')
        self.mmio.write(0,2)
        self.mmio.write(0x1f4,1 if self.compiled else 0)
        if self.mmio.read(0x1f4)!=(1 if self.compiled else 0):raise RuntimeError('URX2 execution mode readback mismatch')
        if self.compiled:self._configure()
        self.mmio.write(0x24,self.baud)
        if self.mmio.read(0x24)!=self.baud:raise RuntimeError('Baud readback mismatch')
        if self.background_sync and state['baud']!=self.baud:
            # Allow the background decoder to settle after changing its bit
            # period, before the capture gate opens. This is bounded by two
            # configured maximum frames and does not claim pre-arm coverage.
            length=self.profile['framing'].get('length',512)
            time.sleep(max(.005,2.0*(length+2)*10/self.baud))
        self.pending=[];self.offset=0;self.last_tick=None
        began=self.now_ticks();self.mmio.write(0,1)
        self.stopped_ticks=None
        return (int(self.mmio.read(0x180))|int(self.mmio.read(0x184))<<32) if self.compiled else began

    def _configure(self):
        for index,word in enumerate(self.compiled['words']):self.mmio.write(0x1000+4*index,word&0xffffffff)
        for index,word in enumerate(self.compiled['words']):
            if self.mmio.read(0x1000+4*index)!=word&0xffffffff:raise RuntimeError('URX2 configuration readback mismatch')
        self.mmio.write(0x1f0,0x43464732)
        if self.mmio.read(0x1f0)!=3:raise RuntimeError('URX2 hardware rejected configuration')

    def _read_events(self,maximum=16):
        for _ in range(min(maximum,self.mmio.read(0x100))):
            if not self.mmio.read(0x108)&0x80000000:raise RuntimeError('Concurrent hardware event reader')
            self.pending.append(unpack_event([int(self.mmio.read(0x110+4*i)) for i in range(24)]))
        if len(self.pending)>256:raise RuntimeError('Local hardware event staging capacity exceeded')

    def read(self,maximum=256):
        chunk=super().read(maximum)
        self._read_events()
        ready=[r for r in self.pending if r['raw_end']<=self.offset]
        self.pending=[r for r in self.pending if r['raw_end']>self.offset]
        chunk.hardware_events=ready
        return chunk

    def stop(self):
        self.mmio.write(0,0)
        self.stopped_ticks=self.now_ticks()
        deadline=time.monotonic()+1
        while self.mmio.read(0x190)&256:
            self._read_events()
            if time.monotonic()>deadline:raise RuntimeError('URX2 detector did not drain after stopping')
            time.sleep(.001)


class URX2RawTransport(URX2Transport):
    """Same URX2 bitstream, detector bypassed; generic software decoding/rules remain available."""
    detection_source='software'


class RTLReplayTransport(ReplayTransport):
    """Replay bytes and OBSERVED RTL event records, never regenerate hardware events in Python."""
    detection_source='fpga'
    def __init__(self,raw,profile,timestamps,records,end_ticks,start_ticks=0):
        super().__init__(raw,profile,timestamps)
        self.compiled=compile_profile(profile);self.records=list(records);self.final_tick=end_ticks;self.start_tick=start_ticks
        self.provenance.update(detection_source='fpga',event_origin='observed_XSim_RTL_output',
                               timestamp_source='RTL_stimulus_relative_time_not_new_hardware_capture',
                               hardware_accessed=False,physical_acceptance=False)
    def start(self):self.tick=self.start_tick;return self.tick
    def read(self,maximum=256):
        chunk=super().read(maximum)
        if self.eof:self.tick=self.final_tick
        ready=[r for r in self.records if r['raw_end']<=self.offset and r['ticks']<=self.tick]
        self.records=[r for r in self.records if r not in ready];chunk.hardware_events=ready
        return chunk


class HardwareRuleEngine(RuleEngine):
    def __init__(self,profile,start_ticks):
        super().__init__(profile,start_ticks);self.compiled=compile_profile(profile)
    def update_hardware(self,frames,issues,records,now_ticks,state):
        self.local_fault=any(state.get(k,0) for k in ('overflows','framing_errors','event_overflows','parser_overflows'))
        active=state.get('hardware_active',0)&255
        tracking=(state.get('hardware_active',0)>>16)&255
        self.states={r['id']:dict(triggered=bool(active&(1<<i))) for i,r in enumerate(self.profile['rules']) if tracking&(1<<i) or active&(1<<i)}
        if frames:self.last_frame_ticks=frames[-1]['end_ticks']
        events=[]
        for item in records:events.extend(adapt_event(item,self.compiled))
        # These parser diagnostics are not duplicated by the hardware event bitmap.
        for issue in issues:
            if issue['kind'] in ('interframe_noise','header_errors'):
                events.append(dict(rule_id='protocol:'+issue['kind'],category='protocol',trigger_ticks=issue['ticks'],
                                   evidence=issue,source='software'))
        result=[]
        for event in sorted(events,key=lambda e:(e['trigger_ticks'],e['rule_id'])):
            item=self._event(event['rule_id'],event['category'],event['trigger_ticks'],event['evidence'])
            item['source']=event['source']
            if 'hardware_batch_id' in event:item['hardware_batch_id']=event['hardware_batch_id']
            result.append(item)
        return result
    def update(self,frames,issues,now_ticks,drained=True,local_ok=True):
        return self.update_hardware(frames,issues,[],now_ticks,{})
