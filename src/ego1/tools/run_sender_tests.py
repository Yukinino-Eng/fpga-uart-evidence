"""UART-pin XSim regression. No serial, hardware manager or board access."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
CASES=['normal','bad_crc','skip','duplicate','gap','persistent','glitch','parallel8','status','invalid','restart']


def tool(bin_dir,name,args,cwd,log):
    exe=bin_dir/(name+('.bat' if os.name=='nt' else ''))
    if not exe.is_file():raise RuntimeError('Missing tool: '+str(exe))
    env=os.environ.copy()
    if os.name=='nt':
        env.setdefault('PROCESSOR_ARCHITECTURE','AMD64')
        command='call "'+str(exe)+'" '+' '.join('"'+str(a).replace(chr(92),'/')+'"' for a in args)
        invocation=cwd/('invoke_'+re.sub('[^A-Za-z0-9_]','_',log.parent.name+'_'+log.stem)+'.cmd')
        invocation.write_text('@echo off'+chr(13)+chr(10)+command+chr(13)+chr(10),encoding='utf-8')
        result=subprocess.run(['cmd.exe','/d','/c',invocation.name],cwd=str(cwd),env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    else:result=subprocess.run([str(exe)]+[str(a) for a in args],cwd=str(cwd),env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    text=result.stdout.decode('utf-8',errors='replace')
    log.write_text(text,encoding='utf-8')
    if result.returncode or re.search(r'(^|\n)(ERROR:|Fatal:)',text):
        raise RuntimeError('Tool failed: '+str(log)+' '+text[-1500:])
    return text


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vivado-bin',type=Path,required=True)
    p.add_argument('--label',default='simulation1')
    args=p.parse_args()
    if not re.fullmatch('[A-Za-z0-9_]+',args.label):raise ValueError('Invalid label')
    output=ROOT/'verification'/args.label
    work=ROOT/'build'/args.label
    if output.exists() or work.exists():raise ValueError('Preserve old results; choose a new label')
    output.mkdir(parents=True);work.mkdir(parents=True)
    tool(args.vivado_bin,'xvlog',['-sv',ROOT/'src/ego1_urx2_source_top.sv',ROOT/'reference/rtl/uart_tx.sv',
        ROOT/'reference/rtl/button_debounce.sv',ROOT/'tb/tb_ego1_urx2.sv'],work,output/'compile.log')
    snapshots={}
    results=[]
    tests=[]
    for baud in [9600,115200]:
        for case in range(8):tests.append((baud,case,10,20,250000,0))
        tests.append((baud,0,10,60,250000,0))
    for case in [8,9,10]:tests.append((115200,case,10,20,250000,0))
    tests.extend([(115200,0,50,60,250000,0),(9600,0,50,20,250000,0),
                  (9600,0,10,20,100000000,2),(115200,0,10,20,100000000,2)])
    for baud,case,fps,seconds,hz,short in tests:
        name='%d_%s_%ds_%dfps_%dHz%s'%(baud,CASES[case],seconds,fps,hz,'_short' if short else '')
        dest=output/name;dest.mkdir()
        key=(hz,fps,case if case>=8 else -1)
        if key not in snapshots:
            snapshot='sender_%d_%d_%d'%(hz,fps,key[2]+1)
            log=output/(snapshot+'_elab.log')
            tool(args.vivado_bin,'xelab',['work.tb_ego1_urx2','-s',snapshot,'-debug','typical','-timescale','1ns/1ps',
                '-generic_top','CLK_HZ='+str(hz),'-generic_top','FPS='+str(fps),'-generic_top','FIXED_CASE='+str(key[2])],work,log)
            snapshots[key]=snapshot
        text=tool(args.vivado_bin,'xsim',[snapshots[key],'-tclbatch',ROOT/'scripts/xsim_run.tcl',
            '-testplusarg','BAUD='+str(baud),'-testplusarg','CASE='+str(case),
            '-testplusarg','LONG='+str(int(seconds==60)),'-testplusarg','SHORT='+str(short),
            '-testplusarg','OUT='+str(dest),'-log',dest/'runtime.log','-wdb',dest/'wave.wdb'],work,dest/'console.log')
        if 'TEST_PASS' not in text or 'Fatal:' in text:raise RuntimeError('No clean terminal PASS: '+name)
        if fps==50 and baud==9600:
            status=dict(status='PASS_REJECTED_UNSUPPORTED_RATE')
        elif short:
            raw=(dest/'received.bin').read_bytes()
            expected=(ROOT/'fixtures'/('%d_normal_20s'%baud)/'stream.bin').read_bytes()[:short*48]
            if raw!=expected:raise RuntimeError('Full-rate short byte mismatch')
            with (dest/'frame_starts.csv').open() as f:starts=list(csv.DictReader(f))
            if len(starts)!=short or int(starts[1]['start_cycle'])-int(starts[0]['start_cycle'])!=10000000:
                raise RuntimeError('Full-rate schedule mismatch')
            status=dict(status='PASS_REAL_100MHZ_BIT_TIMING_AND_PREFIX',bytes=len(raw),clocks_per_bit=(hz+baud//2)//baud)
        else:
            fixture=ROOT/'fixtures'/('%d_%s_%ds'%(baud,CASES[case],seconds)+('_50fps' if fps==50 else ''))
            cmd=[sys.executable,'-B',str(ROOT/'tools/fixture.py'),'check','--fixture',str(fixture),
                '--received',str(dest/'received.bin'),'--starts',str(dest/'frame_starts.csv'),'--output',str(dest/'check.json')]
            checked=subprocess.run(cmd,cwd=str(ROOT),stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (dest/'compare.log').write_bytes(checked.stdout)
            if checked.returncode:raise RuntimeError(checked.stdout.decode('utf-8',errors='replace'))
            status=json.loads((dest/'check.json').read_text(encoding='utf-8'))
        if not (dest/'check.json').exists():(dest/'check.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
        status.update(name=name,source='XSim_UART_PIN',clock_hz=hz,hardware_accessed=False)
        results.append(status)
        (output/'summary.json').write_text(json.dumps(dict(results=results,complete=False),indent=2),encoding='utf-8')
        print('PASS '+name,flush=True)
    (output/'summary.json').write_text(json.dumps(dict(results=results,complete=True,tests=len(results),
        notes='Full-duration regressions scale CLK_HZ to 250kHz for runtime; starts normalized to 100MHz. Two 100MHz short tests independently check production bit timing. No hardware validation.'),indent=2),encoding='utf-8')
    print('REGRESSION_PASS tests='+str(len(results)),flush=True)

if __name__=='__main__':main()
