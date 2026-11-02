"""180-second load replay plus focused production-clock UART wave captures."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from run_sender_tests import tool
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--vivado-bin',type=Path,required=True);args=p.parse_args()
    work=ROOT/'build/extended1';out=ROOT/'verification/extended1'
    work.mkdir();out.mkdir()
    tool(args.vivado_bin,'xvlog',['-sv',ROOT/'src/ego1_urx2_source_top.sv',ROOT/'reference/rtl/uart_tx.sv',ROOT/'reference/rtl/button_debounce.sv',ROOT/'tb/tb_ego1_urx2.sv'],work,out/'compile.log')
    fixture=out/'fixture_180s'
    subprocess.run([sys.executable,'-B',str(ROOT/'tools/fixture.py'),'generate','--case','normal','--baud','115200','--fps','50','--seconds','180','--output',str(fixture)],check=True)
    results=[]
    for hz,fps,seconds,baud,short in [(250000,50,180,115200,0),(100000000,10,20,9600,2),(100000000,10,20,115200,2)]:
        name='load_180s' if not short else 'wave_'+str(baud)
        dest=out/name;dest.mkdir();snapshot=name
        tool(args.vivado_bin,'xelab',['work.tb_ego1_urx2','-s',snapshot,'-debug','typical','-timescale','1ns/1ps','-generic_top','CLK_HZ='+str(hz),'-generic_top','FPS='+str(fps),'-generic_top','SECONDS='+str(seconds)],work,dest/'elab.log')
        text=tool(args.vivado_bin,'xsim',[snapshot,'-tclbatch',ROOT/'scripts/xsim_wave.tcl','-testplusarg','BAUD='+str(baud),'-testplusarg','CASE=0','-testplusarg','SHORT='+str(short),'-testplusarg','OUT='+str(dest),'-log',dest/'runtime.log','-wdb',dest/'wave.wdb'],work,dest/'console.log')
        if 'TEST_PASS' not in text or 'Fatal:' in text:raise RuntimeError('No terminal PASS')
        if short:
            expected=(ROOT/'fixtures'/('%d_normal_20s'%baud)/'stream.bin').read_bytes()[:short*48]
            assert (dest/'received.bin').read_bytes()==expected
            status=dict(status='PASS_FULL_CLOCK_WAVE_AND_BYTES',clocks_per_bit=(hz+baud//2)//baud)
            (dest/'check.json').write_text(json.dumps(status,indent=2))
        else:
            subprocess.run([sys.executable,'-B',str(ROOT/'tools/fixture.py'),'check','--fixture',str(fixture),'--received',str(dest/'received.bin'),'--starts',str(dest/'frame_starts.csv'),'--output',str(dest/'check.json')],check=True)
            status=json.loads((dest/'check.json').read_text())
        status.update(name=name,clock_hz=hz,source='XSim_UART_PIN',hardware_accessed=False)
        results.append(status);print('PASS '+name,flush=True)
    (out/'summary.json').write_text(json.dumps(dict(complete=True,results=results,tests=len(results)),indent=2))
    print('EXTENDED_PASS tests=3',flush=True)
if __name__=='__main__':main()
