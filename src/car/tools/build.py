"""Check or rebuild the STM32 car project without programming hardware."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]


def check():
    tree=ET.parse(ROOT/'Project.uvprojx')
    missing=[]
    references=[x.text for x in tree.iter('FilePath') if x.text]
    references += [x.text for x in tree.iter('ScatterFile') if x.text]
    for value in references:
        relative=value.replace('\\','/')
        path=(ROOT/relative).resolve()
        path.relative_to(ROOT)
        if not path.is_file():missing.append(relative)
    if missing:raise ValueError('Missing project sources: '+', '.join(missing))
    return dict(device='STM32F103C8',target='Lesson20 UART PYNQ',source_references=len(references),
                source_dependencies='PASS',hardware_programmed=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keil',default='C:/Keil_v5/UV4/UV4.exe')
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args();result=check()
    if not args.check_only:
        output=ROOT/'build';output.mkdir(exist_ok=True)
        log=output/'build.log'
        process=subprocess.run([args.keil,'-r',str(ROOT/'Project.uvprojx'),'-t',result['target'],'-o',str(log)],
                               cwd=str(ROOT),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        text=log.read_text(errors='replace')
        if process.returncode or '0 Error(s), 0 Warning(s).' not in text:raise RuntimeError(text)
        firmware=output/'firmware';firmware.mkdir(exist_ok=True)
        result['firmware_sha256']={}
        for suffix in ('hex','axf'):
            name='Lesson20Uart.'+suffix;target=firmware/name
            shutil.copyfile(str(ROOT/'Objects'/name),str(target))
            result['firmware_sha256'][name]=hashlib.sha256(target.read_bytes()).hexdigest()
        result.update(build='PASS_0_ERRORS_0_WARNINGS',output=str(firmware))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
