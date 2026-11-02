"""Notebook controls use the same engine; only the worker owns the hardware lease."""
import json
import os
from pathlib import Path
import threading
import uuid
import zipfile
import time
import html
from .profile import load_profile
from .session import MonitorSession
from .transport import Transport


def launch(root='.'):
    import ipywidgets as widgets
    from IPython.display import display,FileLink
    from tornado.ioloop import PeriodicCallback
    from pynq_hardware_lease import HardwareLease
    root=Path(root).resolve()
    available=sorted((root/'profiles').glob('*.json'))
    def protocol_label(path):
        try:return load_profile(path).get('display',{}).get('name',path.stem)
        except Exception:return path.stem+'（配置待检查）'
    choose=widgets.Dropdown(options=[(protocol_label(p),str(p)) for p in available],description='设备协议',layout=widgets.Layout(width='330px'))
    baud=widgets.Dropdown(options=[9600,19200,38400,57600,115200],value=115200,description='波特率')
    seconds=widgets.BoundedIntText(value=180,min=1,max=3600,description='记录秒数')
    detector=widgets.Dropdown(options=[('软件规则 / URX1基线','software'),('FPGA并行规则 / URX2','fpga'),('软件规则 / URX2通用','software-urx2')],
                              value='fpga' if (root/'firmware/uart_detector2.bit').is_file() else 'software',
                              description='检测执行',layout=widgets.Layout(width='330px'))
    evidence_mode=widgets.Dropdown(options=[('自动连续记录','continuous')],
                                  value='continuous',layout=widgets.Layout(display='none'))
    window_limit=widgets.BoundedIntText(value=100,min=1,max=1000,description='记录上限')
    summary=widgets.HTML()
    check=widgets.Button(description='检查配置')
    program=widgets.Button(description='加载通用接收固件',button_style='warning')
    start=widgets.Button(description='开始监测',button_style='success')
    stop=widgets.Button(description='停止接收',button_style='danger',disabled=True)
    rearm=widgets.Button(description='重新布防',disabled=True,layout=widgets.Layout(display='none'))
    retry=widgets.Button(description='重试事件保存',disabled=True)
    download=widgets.Button(description='导出记录',disabled=True)
    status=widgets.Textarea(value='就绪。只接收数据；不会启动或停止小车。',disabled=True,layout=widgets.Layout(width='100%',height='260px'))
    output=widgets.Output()
    from .viewer import launch_view
    visual_output=widgets.VBox()
    records=widgets.Dropdown(options=[],description='历史记录',layout=widgets.Layout(width='65%'))
    scan=widgets.Button(description='刷新记录列表')
    inspect=widgets.Button(description='查看取证记录')
    notice=widgets.HTML('可查看实时字段曲线，或打开已保存的记录选择事件窗口。')
    state=dict(session=None,loader=None,load_message='',viewer=None,view_root=None,view_updated=0,preview_dirty=True)
    def scan_records(_=None):
        candidates=sorted((root/'results').glob('*/frames.jsonl'),key=lambda p:p.stat().st_mtime,reverse=True)[:100]
        previous=records.value
        records.options=[(p.parent.name,str(p.parent)) for p in candidates]
        values=[value for label,value in records.options]
        records.value=previous if previous in values else (values[0] if values else None)
        inspect.disabled=not candidates
    def show_record(path):
        dispose_view()
        state['viewer']=launch_view(path,display_view=False)
        visual_output.children=(state['viewer']['container'],)
        state['view_root']=str(path)
        state['preview_dirty']=False
    def dispose_view():
        if state['viewer']:
            state['viewer']['holder'].close();state['viewer']['panel'].close();state['viewer']['container'].close()
            visual_output.children=()
            state['viewer']=None
    def show_profile():
        dispose_view()
        state['viewer']=launch_view(None,profile(),display_view=False)
        visual_output.children=(state['viewer']['container'],)
        state['view_root']='profile:'+profile()['id'];state['preview_dirty']=False
    def inspect_record(_):
        if active() or not records.value:return
        try:show_record(records.value)
        except Exception as exc:notice.value=html.escape('无法打开记录：'+str(exc))
    def profile():
        p=load_profile(choose.value);p['transport']['baud']=baud.value
        p['evidence'].update(mode=evidence_mode.value,max_windows=window_limit.value,max_pending=32 if detector.value=='fpga' else 8)
        return load_profile(p)
    def selected(change=None):
        if choose.value:baud.value=load_profile(choose.value)['transport']['baud']
        state['preview_dirty']=True
        summary.value='<div style="padding:12px 16px;background:#eef5f0;border:1px solid #d9e5dc;border-radius:9px">'+html.escape(protocol_label(Path(choose.value)))+' · 字段和默认曲线随协议切换。监测只接收，不控制被测设备。</div>' if choose.value else ''
    selected();choose.observe(selected,names='value')
    def changed_setting(change):state['preview_dirty']=True
    for item in (baud,evidence_mode,window_limit,detector):item.observe(changed_setting,names='value')
    def active():
        s=state['session'];return bool(s and s.thread and s.thread.is_alive())
    def validated(_):
        try:
            p=profile()
            if detector.value=='fpga':
                from .hardware import compile_profile
                compile_profile(p)
            status.value='配置有效：'+p['id']+'，'+str(p['transport']['baud'])+' baud / 8N1，'+detector.label
        except Exception as exc:status.value='配置错误：'+str(exc)
        notice.value=html.escape(status.value)
    def selected_transport(p):
        if detector.value=='software-urx2':
            from .urx2 import URX2RawTransport
            return URX2RawTransport,root/'firmware/uart_detector2.bit'
        if detector.value=='fpga':
            from .hardware import compile_profile
            compile_profile(p)
            from .urx2 import URX2Transport
            return URX2Transport,root/'firmware/uart_detector2.bit'
        return Transport,root/'firmware/uart_monitor_rx.bit'
    def load(_):
        if active():return
        state['load_message']=''
        # The legacy SDK installs signal handlers during its first import.
        # Initialize it in the Notebook callback thread before the worker starts.
        try:
            p=profile();transport_class,bit=selected_transport(p)
            __import__('pynq')
        except Exception as exc:
            state['load_message']='硬件环境未就绪：'+str(exc);return
        state['load_message']='正在加载固件…'
        def worker():
            try:
                with HardwareLease():
                    kwargs=dict(program=True)
                    if detector.value in ('fpga','software-urx2'):kwargs['allow_boot_recovery']=True
                    t=transport_class(bit,p,**kwargs)
                    state['load_message']='通用接收固件已加载；接收器保持停止。';t.close()
            except Exception as exc:state['load_message']='加载失败：'+str(exc)
        state['loader']=threading.Thread(target=worker,daemon=True);state['loader'].start()
    def begin(_):
        if active():return
        state['load_message']=''
        try:
            __import__('pynq')
            previous=state['session']
            if previous and previous.report and previous.report['evidence']['state']=='SAVE_FAILED':
                raise RuntimeError('先保留并处理上一会话保存失败的证据；不能覆盖')
            p=profile();destination=root/'results'/(p['id']+'_'+uuid.uuid4().hex[:12])
            transport_class,bit=selected_transport(p)
            s=MonitorSession(p,destination,seconds.value);state['session']=s
            state['view_root']=None;state['preview_dirty']=False
            s.start_background(lambda:transport_class(bit,p,program=False),HardwareLease)
        except Exception as exc:status.value='无法开始：'+str(exc)
    def export(_):
        s=state['session']
        if not s or active() or not s.report:return
        path=s.output.with_suffix('.zip')
        if not path.exists():
            with zipfile.ZipFile(str(path),'w',zipfile.ZIP_DEFLATED) as bundle:
                for f in sorted(s.output.rglob('*')):
                    if f.is_file():bundle.write(str(f),str(f.relative_to(s.output)))
        with output:display(FileLink(os.path.relpath(str(path),str(Path.cwd())),result_html_prefix='下载本次记录：'))
    def refresh():
        running=active();loading=bool(state['loader'] and state['loader'].is_alive())
        for item in (choose,baud,seconds,evidence_mode,window_limit,detector,check,program,start):item.disabled=running or loading
        window_limit.disabled=running or loading or evidence_mode.value=='single'
        stop.disabled=not running
        s=state['session']
        if s:
            snap=s.snapshot()
            evidence=snap.get('evidence',snap.get('report',{}).get('evidence',{}))
            rearm.disabled=not running or not snap.get('rearm_allowed',False)
            retry.disabled=evidence.get('state')!='SAVE_FAILED'
            download.disabled=running or not bool(s.report)
            brief=dict(状态=snap.get('state'),已记录秒数=round(snap.get('elapsed_seconds',0),1),
                       有效帧=snap.get('parser',snap.get('report',{}).get('parser',{})).get('frames',0),
                       取证状态=evidence.get('state'),提示=snap.get('message',snap.get('error','')),
                       最新字段=snap.get('last_frame',snap.get('report',{}).get('last_frame')),
                       报告=snap.get('report'))
            if snap.get('behavior'):brief['行为检测']=snap['behavior']
            latest=brief['最新字段']
            if latest:
                brief['最新字段']={name:dict(value=value,unit=latest.get('units',{}).get(name,''),valid=latest['validity'][name])
                                 for name,value in latest['fields'].items()}
            status.value=json.dumps(brief,ensure_ascii=False,indent=2)
        if state['load_message']:status.value=state['load_message']
        error=s.snapshot().get('error','') if s else ''
        if error or state['load_message']:notice.value=html.escape(state['load_message'] or error)
        if running:notice.value='正在采集；页面约每500ms刷新，采集线程独立运行。连续模式为多个事件分别保存前后窗。'
        scan.disabled=running or loading;records.disabled=running or loading
        inspect.disabled=running or loading or not records.options
        try:
            if state['preview_dirty'] and not running and not loading:show_profile()
            if s and (running or state['view_root'] is None) and (s.output/'profile.json').is_file() and state['view_root']!=str(s.output):
                show_record(s.output)
            if state['viewer'] and time.monotonic()-state['view_updated']>=.5:
                state['viewer']['refresh'](live=running)
                state['view_updated']=time.monotonic()
        except Exception as exc:notice.value=html.escape('可视化读取提示：'+str(exc))
    check.on_click(validated);program.on_click(load);start.on_click(begin)
    stop.on_click(lambda _:state['session'].request_stop() if state['session'] else None)
    rearm.on_click(lambda _:state['session'].request_rearm() if state['session'] else None)
    def retry_event(_):
        s=state['session']
        if not s:return
        if active():s.request_retry();return
        try:
            from .archive import retry_saved_session
            retry_saved_session(s.output)
            s.report=json.loads((s.output/'report.json').read_text())
            with s.lock:s.live=dict(state=s.report['status'],report=s.report,output=str(s.output))
            notice.value='失败窗口已重试保存并回读校验。'
        except Exception as exc:notice.value=html.escape('重试保存失败：'+str(exc))
    retry.on_click(retry_event)
    download.on_click(export)
    scan.on_click(scan_records);inspect.on_click(inspect_record);scan_records()
    advanced=widgets.Accordion(children=[widgets.VBox([window_limit,status])]);advanced.set_title(0,'记录容量与详细信息');advanced.selected_index=None
    display(widgets.VBox([widgets.HTML('<h2>通用UART监测与取证</h2><p>选择设备协议 → 检查配置 → 加载固件 → 开始监测。单通道3.3V，只接收。</p>'),
                          widgets.HBox([choose,baud,seconds],layout=widgets.Layout(flex_flow='row wrap')),summary,
                          widgets.HBox([detector],layout=widgets.Layout(flex_flow='row wrap')),
                          widgets.HTML('<p>自动连续记录：故障恢复后再次触发会自动保存新记录，无需人工重新布防。持续未恢复的同一告警保留为一条。</p>'),
                          widgets.HBox([check,program,start,stop]),widgets.HBox([retry,download]),notice,
                          widgets.HBox([records,scan,inspect]),visual_output,advanced,output]))
    refresh()
    timer=PeriodicCallback(refresh,500);timer.start()
    return dict(state=state,timer=timer,widgets=dict(start=start,stop=stop,status=status,download=download,
                profile=choose,baud=baud,seconds=seconds,check=check,program=program,rearm=rearm,retry=retry,
                records=records,scan=scan,inspect=inspect,notice=notice,evidence_mode=evidence_mode,window_limit=window_limit,detector=detector),refresh=refresh)
