"""Durable raw/index archive and bounded single-event evidence state machine."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import struct
from .transport import digest, HZ


def atomic_json(path, value):
    path=Path(path);temp=path.with_name(path.name+'.tmp')
    with temp.open('w',encoding='utf-8') as stream:
        json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False)
        stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.replace(str(temp),str(path))


def _copy_range(source, target, start, end):
    with Path(source).open('rb') as inp,Path(target).open('wb') as out:
        inp.seek(start);left=end-start
        while left:
            data=inp.read(min(65536,left))
            if not data:raise IOError('Evidence source truncated')
            out.write(data);left-=len(data)
        out.flush();os.fsync(out.fileno())


class Archive:
    def __init__(self, output, profile, start_ticks, provenance):
        self.root=Path(output)
        self.root.mkdir(parents=True,exist_ok=False)
        self.profile=profile;self.start_ticks=start_ticks;self.last_ticks=start_ticks
        self.total=0;self.frame_end=0;self.frame_count=0
        self.pending=None;self.saved=None;self.error=None;self.attempt=0
        self.retry_request=None
        self.continuous=profile['evidence'].get('mode','continuous')=='continuous'
        self.windows=[];self.exporting=None;self.saved_count=0;self.accepted_count=0;self.dropped_count=0
        self.recent_saved=[]
        self.state='ARMED';self.future=None
        self.pool=ThreadPoolExecutor(max_workers=1)
        self.files={n:(self.root/n).open('wb') for n in ('raw.bin','timestamps.bin','frames.jsonl','frame_index.bin','issues.jsonl','events.jsonl')}
        if self.continuous:self.files['window_index.jsonl']=(self.root/'window_index.jsonl').open('wb')
        if provenance.get('transport',{}).get('detection_source')=='fpga':
            self.files['hardware_events.jsonl']=(self.root/'hardware_events.jsonl').open('wb')
        atomic_json(self.root/'profile.json',profile)
        atomic_json(self.root/'provenance.json',provenance)

    def _line(self,name,value):
        data=(json.dumps(value,sort_keys=True,allow_nan=False)+'\n').encode('utf-8')
        self.files[name].write(data)
        return len(data)

    def append(self,chunk,frames,issues):
        if chunk.raw_offset!=self.total:raise ValueError('Archive raw discontinuity')
        self.files['raw.bin'].write(chunk.data)
        if chunk.ticks:self.files['timestamps.bin'].write(struct.pack('<'+'Q'*len(chunk.ticks),*chunk.ticks))
        self.total+=len(chunk.data)
        if chunk.ticks:self.last_ticks=chunk.ticks[-1]
        for frame in frames:
            first=self.frame_end
            self.frame_end+=self._line('frames.jsonl',frame)
            self.files['frame_index.bin'].write(struct.pack('<QQQQ',frame['start_ticks'],frame['end_ticks'],first,self.frame_end))
            self.frame_count+=1
        for issue in issues:self._line('issues.jsonl',issue)

    def trigger(self,event):
        self._line('events.jsonl',event)
        if self.continuous:
            if (len(self.windows)>=self.profile['evidence'].get('max_pending',8) or
                    self.accepted_count>=self.profile['evidence'].get('max_windows',100)):
                self.dropped_count+=1
                self._line('window_index.jsonl',dict(event_id=event['event_id'],state='LIMIT_REACHED',
                           reason='Window capacity reached; raw stream and event retained'))
                return
            self.accepted_count+=1
            self.windows.append(dict(state='POST_CAPTURE',attempt=0,error=None,
                pending=dict(trigger=event,desired_start_ticks=event['trigger_ticks']-int(self.profile['evidence']['pre_seconds']*HZ),
                             desired_end_ticks=event['trigger_ticks']+int(self.profile['evidence']['post_seconds']*HZ),pre_cache_clipped=False)))
            self._continuous_state()
            return
        if self.state!='ARMED':return
        self.pending=dict(trigger=event,desired_start_ticks=event['trigger_ticks']-int(self.profile['evidence']['pre_seconds']*HZ),
                          desired_end_ticks=event['trigger_ticks']+int(self.profile['evidence']['post_seconds']*HZ),
                          pre_cache_clipped=False)
        self.state='POST_CAPTURE';self.saved=None;self.error=None

    def flush(self, durable=False):
        for stream in self.files.values():
            stream.flush()
            if durable:os.fsync(stream.fileno())

    def poll(self,now_ticks,ending=False):
        if self.continuous:
            self._poll_continuous(now_ticks,ending)
            return
        if self.future and self.future.done():
            try:
                self.saved=self.future.result();self.state='SAVED_LOCKED';self.error=None
            except Exception as exc:
                self.error=type(exc).__name__+': '+str(exc);self.state='SAVE_FAILED'
            self.future=None
        if self.state=='POST_CAPTURE' and (now_ticks>=self.pending['desired_end_ticks'] or ending):
            self.flush(True)
            self.attempt+=1
            request=dict(self.pending,available_end_ticks=now_ticks,raw_entries=self.total,frames_end=self.frame_end,frame_count=self.frame_count,
                         attempt=self.attempt,capture_start_ticks=self.start_ticks)
            self.retry_request=request
            self.future=self.pool.submit(self._export,request)
            self.state='SAVING'

    def _continuous_state(self):
        failed=[w for w in self.windows if w['state']=='SAVE_FAILED']
        self.error=failed[0]['error'] if failed else None
        self.state=('SAVE_FAILED' if failed else 'SAVING' if self.future else
                    'POST_CAPTURE' if self.windows else 'MONITORING')

    def _poll_continuous(self,now_ticks,ending=False):
        if self.future and self.future.done():
            item=self.exporting
            try:
                result=self.future.result()
                self._line('window_index.jsonl',dict(event_id=item['pending']['trigger']['event_id'],
                           state='SAVED',path=str(Path(result['path']).relative_to(self.root)),readback_verified=True))
                self.saved=result;self.saved_count+=1
                self.recent_saved.append(dict(event_id=item['pending']['trigger']['event_id'],
                                               path=result['path'],readback_verified=True))
                self.recent_saved=self.recent_saved[-20:]
                self.windows.remove(item)
            except Exception as exc:
                item.update(state='SAVE_FAILED',error=type(exc).__name__+': '+str(exc))
                self._line('window_index.jsonl',dict(event_id=item['pending']['trigger']['event_id'],
                           state='SAVE_FAILED',error=item['error']))
            self.future=None;self.exporting=None
        if not self.future:
            ready=next((w for w in self.windows if w['state']=='POST_CAPTURE' and
                        (ending or now_ticks>=w['pending']['desired_end_ticks'])),None)
            if ready:
                self.flush(True)
                ready['attempt']+=1
                request=dict(ready['pending'],available_end_ticks=now_ticks,raw_entries=self.total,
                             frames_end=self.frame_end,frame_count=self.frame_count,attempt=ready['attempt'],
                             capture_start_ticks=self.start_ticks)
                # A retry preserves the original available window, including an early-stop boundary.
                if ready.get('request'):
                    request=dict(ready['request'],attempt=ready['attempt'])
                ready.update(state='SAVING',request=request,error=None)
                self.exporting=ready;self.future=self.pool.submit(self._export,request)
        self._continuous_state()

    def _export(self,request):
        directory=self.root/'events'/('event_%04d_attempt_%02d'%(request['trigger']['event_id'],request['attempt']))
        directory.mkdir(parents=True,exist_ok=False)
        begin=max(request['capture_start_ticks'],request['desired_start_ticks'])
        end=min(request['available_end_ticks'],request['desired_end_ticks'])
        total=request['raw_entries']
        with (self.root/'timestamps.bin').open('rb') as stream:
            def bound(tick,right=False):
                lo,hi=0,total
                while lo<hi:
                    mid=(lo+hi)//2;stream.seek(mid*8)
                    current=struct.unpack('<Q',stream.read(8))[0]
                    if current<tick or right and current==tick:lo=mid+1
                    else:hi=mid
                return lo
            first,last=bound(begin),bound(end,True)
        _copy_range(self.root/'raw.bin',directory/'raw.bin',first,last)
        _copy_range(self.root/'timestamps.bin',directory/'timestamps.bin',first*8,last*8)
        # Binary-search the disk index; no unbounded frame history or long-session scan.
        with (self.root/'frame_index.bin').open('rb') as stream:
            def frame_bound(tick,column,right=False):
                lo,hi=0,request['frame_count']
                while lo<hi:
                    mid=(lo+hi)//2;stream.seek(mid*32)
                    record=struct.unpack('<QQQQ',stream.read(32));current=record[column]
                    if current<tick or right and current==tick:lo=mid+1
                    else:hi=mid
                return lo
            a,b=frame_bound(begin,1),frame_bound(end,0,True)
            if a<b:
                stream.seek(a*32);frame_start=struct.unpack('<QQQQ',stream.read(32))[2]
                stream.seek((b-1)*32);frame_end=struct.unpack('<QQQQ',stream.read(32))[3]
            else:frame_start=frame_end=request['frames_end']
        _copy_range(self.root/'frames.jsonl',directory/'frames.jsonl',frame_start,frame_end)
        manifest=dict(request,raw_start=first,raw_end=last,covered_start_ticks=begin,covered_end_ticks=end,
                      pre_clipped=request['desired_start_ticks']<request['capture_start_ticks'] or request['pre_cache_clipped'],
                      post_clipped=request['available_end_ticks']<request['desired_end_ticks'],
                      note='Raw bytes follow hardware time; whole decoded frames can overlap window edges.',
                      files={name:digest(directory/name) for name in ('raw.bin','timestamps.bin','frames.jsonl')})
        atomic_json(directory/'event.json',manifest)
        readback=json.loads((directory/'event.json').read_text())
        if any(digest(directory/name)!=value for name,value in readback['files'].items()):
            raise IOError('Evidence readback mismatch')
        return dict(path=str(directory),manifest=manifest,readback_verified=True)

    def rearm(self,recovered):
        if self.continuous:raise RuntimeError('Continuous evidence remains armed; use retry for failed saves')
        if self.state!='SAVED_LOCKED' or not recovered:
            raise RuntimeError('Save/readback and recovery are required before rearming')
        self.state='ARMED';self.pending=None;self.saved=None;self.error=None

    def retry(self):
        if self.continuous:
            failed=[w for w in self.windows if w['state']=='SAVE_FAILED']
            if not failed:raise RuntimeError('No failed event save to retry')
            for item in failed:item.update(state='POST_CAPTURE',error=None)
            self._continuous_state()
            return
        if self.state!='SAVE_FAILED':raise RuntimeError('No failed event save to retry')
        self.state='POST_CAPTURE'

    def finish(self,now_ticks):
        if self.continuous:
            while True:
                self.poll(now_ticks,ending=True)
                if not self.future:break
                try:self.future.result()
                except Exception:pass
            self.pool.shutdown(wait=True)
            if not self.error:self.state='COMPLETED'
            self.flush(True)
            for stream in self.files.values():stream.close()
            return {name:digest(self.root/name) for name in list(self.files)+['profile.json','provenance.json']}
        self.poll(now_ticks,ending=True)
        self.pool.shutdown(wait=True)
        self.poll(now_ticks,ending=True)
        self.flush(True)
        for stream in self.files.values():stream.close()
        return {name:digest(self.root/name) for name in list(self.files)+['profile.json','provenance.json']}

    def status(self):
        if self.continuous:
            return dict(mode='continuous',state=self.state,error=self.error,saved=self.saved,
                        saved_count=self.saved_count,accepted_count=self.accepted_count,dropped_count=self.dropped_count,
                        pending_count=len(self.windows),failed_count=sum(w['state']=='SAVE_FAILED' for w in self.windows),
                        max_windows=self.profile['evidence'].get('max_windows',100),
                        max_pending=self.profile['evidence'].get('max_pending',8),
                        windows_integrity='FAIL' if self.error or self.dropped_count else 'PASS',
                        recent_saved=list(self.recent_saved),pending_requests=list(self.windows))
        return dict(state=self.state,error=self.error,saved=self.saved,pending=self.pending,retry_request=self.retry_request)


def retry_saved_session(root):
    """Retry a failed export from durable files after the capture process has ended."""
    root=Path(root);report=json.loads((root/'report.json').read_text())
    if report['evidence']['state']!='SAVE_FAILED':raise RuntimeError('Session has no failed save')
    for name,value in report['files'].items():
        if digest(root/name)!=value:raise IOError('Source archive changed: '+name)
    if report['evidence'].get('mode')=='continuous':
        return _retry_continuous_session(root,report)
    request=dict(report['evidence']['retry_request']);request['attempt']+=1
    report['evidence']['retry_request']=request
    atomic_json(root/'report.json',report)
    archive=Archive.__new__(Archive);archive.root=root
    try:
        result=archive._export(request)
    except Exception as exc:
        report['evidence']['error']=type(exc).__name__+': '+str(exc)
        atomic_json(root/'report.json',report)
        raise
    report['evidence'].update(state='SAVED_LOCKED',saved=result,error=None,retry_request=request)
    # Preserve capture errors; fixing an export cannot repair lost input bytes.
    report['status']='FAILED' if report['error'] else 'COMPLETED'
    atomic_json(root/'report.json',report)
    atomic_json(root/'status.json',dict(state=report['status'],report=report,output=str(root)))
    return result


def _retry_continuous_session(root,report):
    evidence=report['evidence'];archive=Archive.__new__(Archive);archive.root=root
    completed=[]
    for item in list(evidence['pending_requests']):
        if item['state']!='SAVE_FAILED':continue
        item['attempt']+=1;item['request']['attempt']=item['attempt']
        # Persist the attempt before exporting so interrupted retries never overwrite a directory.
        atomic_json(root/'report.json',report)
        try:
            result=archive._export(item['request'])
            with (root/'window_index.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(dict(event_id=item['pending']['trigger']['event_id'],state='SAVED',
                             path=str(Path(result['path']).relative_to(root)),readback_verified=True))+'\n')
                stream.flush();os.fsync(stream.fileno())
            completed.append(result);evidence['saved']=result;evidence['saved_count']+=1
            evidence['recent_saved']=(evidence['recent_saved']+[dict(event_id=item['pending']['trigger']['event_id'],
                                       path=result['path'],readback_verified=True)])[-20:]
            evidence['pending_requests'].remove(item)
        except Exception as exc:item['error']=type(exc).__name__+': '+str(exc)
    evidence['failed_count']=len(evidence['pending_requests']);evidence['pending_count']=evidence['failed_count']
    evidence['state']='SAVE_FAILED' if evidence['failed_count'] else 'COMPLETED'
    evidence['error']=evidence['pending_requests'][0]['error'] if evidence['failed_count'] else None
    evidence['windows_integrity']='FAIL' if evidence['failed_count'] or evidence['dropped_count'] else 'PASS'
    report['files']['window_index.jsonl']=digest(root/'window_index.jsonl')
    report['status']='FAILED' if report['error'] or evidence['error'] else 'COMPLETED'
    atomic_json(root/'report.json',report)
    atomic_json(root/'status.json',dict(state=report['status'],report=report,output=str(root)))
    if evidence['error']:raise IOError(evidence['error'])
    return dict(saved=completed,evidence=evidence)
