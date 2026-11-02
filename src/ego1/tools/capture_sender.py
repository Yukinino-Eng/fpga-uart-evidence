"""Receive-only board smoke capture; never writes UART bytes."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import time
import serial
from serial.tools import list_ports

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--port',required=True);p.add_argument('--baud',type=int,choices=[9600,115200],required=True)
p.add_argument('--output',type=Path,required=True);p.add_argument('--wait',type=int,default=180)
a=p.parse_args()
ports=[x for x in list_ports.comports() if x.device.upper()==a.port.upper()]
if len(ports)!=1 or ports[0].vid!=0x0403 or ports[0].pid!=0x6010 or ports[0].serial_number!='1234':
    raise SystemExit('Port identity mismatch; re-identify board before capture')
a.output.mkdir(parents=True)
meta=dict(source='PHYSICAL_EGo1_USB_RX',port=a.port,baud=a.baud,vid=ports[0].vid,pid=ports[0].pid,
    serial=ports[0].serial_number,jtag_identified_part='xc7a35t',hardware_accessed=True,uart_bytes_written=0,
    timestamp_basis='PC read completion; not PYNQ hardware time',status='WAITING_FOR_S0')
def save():
    (a.output/'capture.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
save()
s=serial.Serial(port=None,baudrate=a.baud,timeout=0.05)
s.dtr=False;s.rts=False;s.port=a.port
raw=bytearray();first=None;started=time.monotonic()
try:
    s.open()
    print('CAPTURE_READY '+a.port+' '+str(a.baud),flush=True)
    with (a.output/'received.bin').open('wb') as f,(a.output/'pc_reads.csv').open('w',newline='') as log:
        writer=csv.writer(log);writer.writerow(['seconds_since_open','offset','length'])
        while True:
            now=time.monotonic()
            if first is None and now-started>a.wait:break
            if first is not None and now-first>21:break
            block=s.read(s.in_waiting or 1)
            if block:
                now=time.monotonic()
                if first is None:first=now
                writer.writerow([now-started,len(raw),len(block)])
                raw.extend(block);f.write(block);f.flush()
finally:s.close()
expected=(ROOT/'fixtures'/('%d_normal_20s'%a.baud)/'stream.bin').read_bytes()
meta.update(status='PASS_EXACT_BOARD_BYTES' if bytes(raw)==expected else 'NO_DATA' if not raw else 'FAIL_EXACT_BYTES',
    received_bytes=len(raw),expected_bytes=len(expected),sha256=hashlib.sha256(raw).hexdigest(),
    matched=bytes(raw)==expected,first_byte_seconds=None if first is None else first-started,
    board_to_pynq_tested=False,frame_schedule='NOT_MEASURED_BY_PC_READ_TIMESTAMPS')
if raw!=expected:
    common=min(len(raw),len(expected))
    meta['first_mismatch']=next((i for i in range(common) if raw[i]!=expected[i]),common)
save();print(json.dumps(meta,indent=2),flush=True)
raise SystemExit(0 if meta['matched'] else 1)
