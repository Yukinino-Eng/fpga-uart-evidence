"""Bounded, read-only visualization of URX1 records (Python 3.6 compatible)."""
from collections import deque
import base64
import html
import json
import math
import zlib
from pathlib import Path

HZ = 100000000


def profile_payload(profile, name='未开始的监测会话'):
    display=profile.get('display',{})
    labels=display.get('fields',{})
    return dict(version=2,name=name,live=False,origin=0,time_basis='unknown',frames=[],events=[],windows={},
                fields=[dict(name=f['name'],unit=f.get('unit',''),label=labels.get(f['name'],f['name']))
                        for f in profile.get('fields',[])],rules=profile.get('rules',[]),report={},
                status=dict(state='IDLE',evidence=dict(mode=profile.get('evidence',{}).get('mode','continuous'),
                    max_windows=profile.get('evidence',{}).get('max_windows',100),
                    max_pending=profile.get('evidence',{}).get('max_pending',8),saved_count=0,pending_count=0)),
                profile_id=profile.get('id',''),profile_label=display.get('name',profile.get('id','')),
                default_field=display.get('default_field'),transport=profile.get('transport',{}),
                evidence_config=profile.get('evidence',{}),view_frames_seen=0,view_limited=False,
                catching_up=False,errors=[],source_kind='empty',
                rule_labels=dict(display.get('rule_labels',{}),**display.get('rules',{})),
                gap_seconds=profile.get('timing',{}).get('valid_frame_timeout_ms',250)/1000.0)


def _json(text):
    def bad(value):
        raise ValueError('Nonfinite JSON: ' + value)
    return json.loads(text, parse_constant=bad)


class RecordView:
    def __init__(self, root, max_frames=2000, max_events=200):
        self.root = Path(root).resolve()
        self.frames = deque(maxlen=max_frames)
        self.events = deque(maxlen=max_events)
        self.cursors = {}
        self.origin = None
        self.errors = []
        self.seen = 0
        self.window_cache = {}

    def _read(self, name, target, budget=262144):
        path = self.root / name
        offset, pending = self.cursors.get(name, (0, b''))
        if not path.is_file():
            return False
        if path.stat().st_size < offset:
            raise ValueError('Record file truncated: ' + name)
        with path.open('rb') as stream:
            stream.seek(offset)
            data = stream.read(budget)
        offset += len(data)
        parts = (pending + data).split(b'\n')
        pending = parts.pop()
        if len(pending) > 1048576:
            raise ValueError('Oversized record line: ' + name)
        for line in parts:
            if not line.strip():
                continue
            try:
                item = _json(line.decode('utf-8'))
                if not isinstance(item, dict):
                    raise ValueError('Expected a record object')
                if name == 'frames.jsonl':
                    if (type(item.get('start_ticks')) is not int or type(item.get('end_ticks')) is not int
                            or not 0 <= item['start_ticks'] <= item['end_ticks'] < 1 << 64
                            or not isinstance(item.get('fields'), dict) or not isinstance(item.get('validity'), dict)):
                        raise ValueError('Invalid decoded-frame structure')
                elif (type(item.get('event_id')) is not int or type(item.get('trigger_ticks')) is not int
                      or not isinstance(item.get('rule_id'), str)):
                    raise ValueError('Invalid event structure')
                target.append(item)
                if name == 'frames.jsonl':
                    self.seen += 1
                    if self.origin is None:
                        self.origin = item['start_ticks']
            except (ValueError, KeyError, UnicodeError) as exc:
                self.errors.append(name + ': ' + str(exc))
                self.errors = self.errors[-10:]
        self.cursors[name] = offset, pending
        return offset < path.stat().st_size

    def _metadata(self, name):
        try:
            return _json((self.root / name).read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}

    def update(self, live=False):
        catching = self._read('frames.jsonl', self.frames)
        catching = self._read('events.jsonl', self.events) or catching
        profile = self._metadata('profile.json')
        report = self._metadata('report.json')
        status = self._metadata('status.json')
        windows = {}
        # Only the latest bounded event set is loaded. The complete log stays on disk.
        ids = {e['event_id'] for e in list(self.events)[-100:]}
        frame_budget=20000
        for path in sorted((self.root / 'events').glob('*/event.json'),reverse=True):
            path.resolve().relative_to(self.root)
            manifest = _json(path.read_text(encoding='utf-8'))
            identity = manifest['trigger']['event_id']
            if identity not in ids:
                continue
            limit=min(2000,frame_budget)
            signature = (path.stat().st_mtime, path.stat().st_size,limit)
            cached = self.window_cache.get(str(path))
            if cached and cached[0] == signature:
                windows[str(identity)] = cached[1]
                frame_budget-=len(cached[1]['frames'])
                continue
            frames = []
            view_clipped = False
            with (path.parent / 'frames.jsonl').open(encoding='utf-8') as stream:
                for n, line in enumerate(stream):
                    if n >= limit:
                        view_clipped = True
                        break
                    if line.strip():
                        frames.append(_json(line))
            windows[str(identity)] = dict(manifest=manifest, frames=frames, view_clipped=view_clipped)
            frame_budget-=len(frames)
            self.window_cache[str(path)] = (signature, windows[str(identity)])
        self.window_cache = {p: value for p, value in self.window_cache.items()
                             if value[1]['manifest']['trigger']['event_id'] in ids}
        frames = list(self.frames)
        fields = profile_payload(profile)['fields']
        if not fields and frames:
            fields = [dict(name=n, unit=frames[-1].get('units', {}).get(n, '')) for n in frames[-1]['fields']]
        origin = self.origin
        basis = 'first_frame'
        if origin is None:
            origin = report.get('start_ticks')
            if origin is None and self.events:
                origin = self.events[0].get('evidence', {}).get('last_valid_ticks')
            basis = 'capture_start' if origin is not None else 'unknown'
        return dict(version=2, name=self.root.name, live=bool(live), origin=origin or 0, time_basis=basis,
                    frames=frames, events=list(self.events)[-100:], windows=windows, fields=fields,
                    profile_id=profile.get('id',''),profile_label=profile.get('display',{}).get('name',profile.get('id','')),
                    default_field=profile.get('display',{}).get('default_field'),transport=profile.get('transport',{}),
                    evidence_config=profile.get('evidence',{}),source_kind=('rtl_record' if report.get('provenance',{}).get('transport',{}).get('event_origin')=='observed_XSim_RTL_output' else 'hardware_record' if report.get('hardware_accessed') else 'offline_record'),
                    detection_source=report.get('detection_source',status.get('detection_source','software')),
                    overlay_id=report.get('provenance',{}).get('transport',{}).get('overlay_id',status.get('overlay_id')),
                    rule_labels=dict(profile.get('display',{}).get('rule_labels',{}),**profile.get('display',{}).get('rules',{})),
                    source_note=('检测事件来自XSim观察到的RTL输出，当前为离板回放。' if report.get('provenance',{}).get('transport',{}).get('event_origin')=='observed_XSim_RTL_output' else ''),
                    rules=profile.get('rules', []), report=report, status=status,
                    view_frames_seen=self.seen, view_limited=self.seen > len(frames) or len(self.events) > 100,
                    catching_up=catching, errors=list(self.errors),
                    gap_seconds=profile.get('timing', {}).get('valid_frame_timeout_ms', 250) / 1000.0)


def document(payload, holder_id=None):
    """One renderer for standalone HTML and the Notebook iframe; no CDN or service."""
    template = Path(__file__).with_name('viewer.html').read_text(encoding='utf-8')
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return template.replace('/*URX_DATA*/null', encoded).replace('/*URX_HOLDER*/null', json.dumps(holder_id))


def export_record(root, output):
    reader = RecordView(root)
    payload = reader.update()
    while payload['catching_up']:
        payload = reader.update()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document(payload), encoding='utf-8')
    return payload


def notebook_payload(payload):
    """Lossless full snapshots avoid dropped-delta gaps and Notebook IOPub floods."""
    text=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    encoded=text.encode('utf-8')
    if len(encoded)<32768:return text
    return 'URX-ZLIB1:'+base64.b64encode(zlib.compress(encoded,1)).decode('ascii')


def launch_view(root, profile=None, display_view=True):
    """A standalone Notebook record viewer; never imports or accesses PYNQ."""
    import uuid
    import ipywidgets as widgets
    from IPython.display import display
    identity = 'urx_data_' + uuid.uuid4().hex
    reader = RecordView(root) if root is not None else None
    payload = reader.update() if reader else profile_payload(profile or {})
    holder = widgets.HTML('<pre id="{}" hidden>{}</pre>'.format(identity, html.escape(notebook_payload(payload))))
    panel = widgets.HTML('<iframe title="UART取证可视化" sandbox="allow-scripts allow-same-origin" style="border:0;width:100%;height:1250px" srcdoc="{}"></iframe>'.format(html.escape(document(payload, identity), quote=True)))
    container = widgets.VBox([holder, panel])
    if display_view:display(container)
    def refresh(live=False):
        data = reader.update(live) if reader else payload
        holder.value = '<pre id="{}" hidden>{}</pre>'.format(identity, html.escape(notebook_payload(data)))
        return data
    return dict(reader=reader, holder=holder, panel=panel, container=container, refresh=refresh)
