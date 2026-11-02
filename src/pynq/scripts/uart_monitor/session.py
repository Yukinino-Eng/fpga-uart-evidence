"""Shared capture/replay engine used by CLI and the nonblocking Notebook UI."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import queue
import threading
import time
from .archive import Archive, atomic_json
from .decoder import make_decoder
from .profile import load_profile
from .rules import RuleEngine
from .transport import HZ, digest


class MonitorSession:
    def __init__(self,profile,output,seconds=180):
        self.profile=load_profile(profile)
        if not 0<seconds<=3600:raise ValueError('Duration must be (0,3600] seconds')
        self.output=Path(output);self.seconds=seconds
        self.stop_requested=threading.Event();self.commands=queue.Queue()
        self.lock=threading.Lock();self.live=dict(state='IDLE');self.thread=None;self.report=None

    def request_stop(self):self.stop_requested.set()
    def request_rearm(self):self.commands.put('rearm')
    def request_retry(self):self.commands.put('retry')
    def snapshot(self):
        with self.lock:return json.loads(json.dumps(self.live))

    def start_background(self,factory,lease_factory=None):
        if self.thread and self.thread.is_alive():raise RuntimeError('Session is already running')
        def work():
            try:
                if lease_factory:
                    with lease_factory():self.run(factory())
                else:self.run(factory())
            except BaseException as exc:
                with self.lock:self.live.update(state='FAILED',error=type(exc).__name__+': '+str(exc))
        self.thread=threading.Thread(target=work,name='URX1-capture',daemon=True)
        self.thread.start()

    def run(self,transport):
        if transport.hardware_accessed and getattr(transport,'supports_buffered_capture',False):
            from .buffered import BufferedTransport
            transport=BufferedTransport(transport,self.seconds)
        decoder=make_decoder(self.profile)
        archive=None;started=False;error=None;last_frame=None;last_tick=0;message=''
        before=transport.registers()
        if before.get('control',0)&1 or before.get('level',0):
            transport.close();raise RuntimeError('Preserve previous active receiver/buffered data')
        # Construct the archive before enabling hardware; never start into an existing output path.
        start=transport.now_ticks()
        provenance=dict(transport=transport.provenance,hardware_accessed=transport.hardware_accessed,
                        created_utc=datetime.now(timezone.utc).isoformat(),utc_source='host_clock_not_independently_verified',
                        software_files={p.name:digest(p) for p in Path(__file__).parent.glob('*.py')})
        archive=Archive(self.output,self.profile,start,provenance)
        engine=RuleEngine(self.profile,start)
        hardware_rules=getattr(transport,'detection_source','software')=='fpga'
        if hardware_rules:
            from .urx2 import HardwareRuleEngine
            engine=HardwareRuleEngine(self.profile,start)
        began=time.monotonic();last_status=began;last_flush=began;previous_local=(0,0,0,0)
        capture_end_ticks=None
        def consume(chunk):
            nonlocal last_frame,last_tick,previous_local
            frames,issues=decoder.feed(chunk)
            archive.append(chunk,frames,issues)
            if frames:last_frame=frames[-1]
            now=transport.now_ticks()
            if capture_end_ticks is not None:now=min(now,capture_end_ticks)
            last_tick=now
            local=tuple(chunk.state.get(k,0) for k in ('overflows','framing_errors','event_overflows','parser_overflows'))
            for name,value,old in zip(('fifo_overflow','framing_error','event_fifo_overflow','parser_overflow'),local,previous_local):
                if value>old:
                    archive.trigger(engine._event('local:'+name,'capture',now,dict(count=value-old,observation='counter_delta_at_poll')))
            previous_local=local
            if hardware_rules:
                records=getattr(chunk,'hardware_events',[])
                for record in records:archive._line('hardware_events.jsonl',record)
                events=engine.update_hardware(frames,issues,records,now,chunk.state)
            else:
                events=engine.update(frames,issues,now,drained=chunk.state.get('level',0)==0,
                                     local_ok=not local[0] and not local[1])
            for event in events:archive.trigger(event)
            archive.poll(now)
        try:
            start=transport.start();started=True;engine.last_frame_ticks=start;archive.start_ticks=start
            began=time.monotonic()
            while not self.stop_requested.is_set() and time.monotonic()-began<self.seconds:
                chunk=transport.read();consume(chunk)
                if getattr(transport,'eof',False):break
                while not self.commands.empty():
                    command=self.commands.get_nowait()
                    try:
                        if command=='rearm':archive.rearm(engine.recovered())
                        elif command=='retry':archive.retry()
                        message=''
                    except RuntimeError as exc:message=str(exc)
                now=time.monotonic()
                if now-last_flush>=.25:
                    archive.flush();last_flush=now
                if now-last_status>=.25:
                    live=dict(state='RUNNING',elapsed_seconds=now-began,parser=decoder.summary(),
                              last_frame=last_frame,registers=chunk.state,evidence=archive.status(),
                              rearm_allowed=archive.state=='SAVED_LOCKED' and engine.recovered(),message=message,
                              output=str(self.output),events_total=engine.events_total)
                    live.update(now_ticks=transport.now_ticks(),start_ticks=start,event_counts=dict(engine.history_counts),
                                detection_source='fpga' if hardware_rules else 'software',
                                overlay_id=transport.provenance.get('overlay_id'),
                                last_valid_age_seconds=max(0,(transport.now_ticks()-engine.last_frame_ticks)/HZ),
                                active_rules=[k for k,v in engine.states.items() if v.get('triggered')])
                    if engine.behavior:live['behavior']=engine.behavior_status()
                    atomic_json(self.output/'status.json',live)
                    with self.lock:self.live=live
                    last_status=now
                if not chunk.data:time.sleep(.002)
        except BaseException as exc:
            error=type(exc).__name__+': '+str(exc)
        finally:
            if started:
                try:
                    transport.stop()
                    capture_end_ticks=getattr(transport,'stopped_ticks',None)
                    if capture_end_ticks is None:capture_end_ticks=transport.now_ticks()
                    for _ in range(getattr(transport,'drain_limit',32)):
                        chunk=transport.read();consume(chunk)
                        if not chunk.data and not getattr(chunk,'hardware_events',[]) and getattr(transport,'eof',True):break
                except BaseException as exc:
                    error=(error+'; ' if error else '')+'Cleanup: '+type(exc).__name__+': '+str(exc)
            registers=transport.registers()
            last_tick=capture_end_ticks if capture_end_ticks is not None else transport.now_ticks()
            capture_seconds=time.monotonic()-began
            transport.close()
        try:
            tail=decoder.finish()
            if tail:
                from .decoder import ByteChunk
                archive.append(ByteChunk(b'',[],decoder.stats['bytes_seen']),[],tail)
            for event in engine.update([],tail,last_tick,drained=registers.get('level',0)==0,
                                       local_ok=not registers.get('overflows',0) and not registers.get('framing_errors',0)):
                archive.trigger(event)
            hashes=archive.finish(last_tick)
        except BaseException as exc:
            hashes={};error=(error+'; ' if error else '')+'Archive: '+type(exc).__name__+': '+str(exc)
        stats=decoder.summary()
        capture_ok=not error and not registers.get('control',1) and registers.get('level',1)==0 and not registers.get('overflows',1) and not registers.get('framing_errors',1)
        capture_ok=capture_ok and registers.get('consumed',-1)==stats['bytes_seen'] and registers.get('received',-1)==registers.get('consumed',-2)+registers.get('overflows',0)
        capture_ok=capture_ok and not registers.get('event_overflows',0) and not registers.get('parser_overflows',0) and not registers.get('host_pending_events',0)
        quality='FAIL' if not stats['transport_integrity_observed'] else ('PASS' if stats['checksum_available'] and stats['sequence_available'] else 'UNKNOWN')
        device_events=sum(v for k,v in engine.history_counts.items() if not k.startswith(('local:','protocol:','behavior:baseline:')) and k!='valid_frame_timeout')
        device_observation_complete=not transport.hardware_accessed or capture_ok
        report=dict(format='URX1-session-v1',status='FAILED' if error or archive.error else 'COMPLETED',
                    hardware_accessed=transport.hardware_accessed,profile_id=self.profile['id'],parser=stats,
                    capture_integrity=('PASS' if capture_ok else 'FAIL') if transport.hardware_accessed else 'UNKNOWN',
                    protocol_integrity=quality,device_health='FAIL' if device_events else ('PASS' if self.profile['rules'] and stats['frames'] and device_observation_complete else 'UNKNOWN'),
                    assessment='Observed configured rules only; not complete application acceptance',
                    events_total=engine.events_total,event_counts=engine.history_counts,evidence=archive.status(),
                    error=error,hardware_registers=registers,capture_seconds=capture_seconds,elapsed_seconds=time.monotonic()-began,
                    start_ticks=start,end_ticks=last_tick,last_frame=last_frame,files=hashes,provenance=provenance,
                    car_application_acceptance=False)
        report['detection_source']='fpga' if hardware_rules else 'software'
        if engine.behavior:
            report['behavior']=engine.behavior_status()
            unknown=(report['behavior']['baseline_assessment'] in ('UNKNOWN','DEVIATION_OBSERVED') or
                     report['behavior']['current_baseline_state']=='WARMUP' or
                     report['behavior']['mode'] is None or
                     'UNKNOWN' in report['behavior']['freshness'].values() or not stats['frames'])
            if not device_events and unknown:
                report['device_health']='UNKNOWN'
        atomic_json(self.output/'report.json',report)
        atomic_json(self.output/'status.json',dict(state=report['status'],report=report,output=str(self.output)))
        self.report=report
        with self.lock:self.live=dict(state=report['status'],report=report,output=str(self.output))
        return report
