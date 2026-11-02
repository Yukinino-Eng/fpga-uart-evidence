"""PYNQ power-cycle acceptance. Observe network before any repair; Python 3.6."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid


def require(condition,message):
    if not condition:raise RuntimeError(message)


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(65536),b''):result.update(block)
    return result.hexdigest()


def command(*args):
    return subprocess.check_output(list(args),stderr=subprocess.STDOUT).decode()


def boot_id():return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def network(address,prefix,port=9090):
    addresses=command('ip','-o','-4','addr','show','dev','eth0')
    require(bool(re.search(r'\binet '+re.escape(address)+'/'+str(prefix)+r'\b',addresses)),
            'Persistent IP absent or wrong prefix. Preserve failure; do not add it manually before saving this result. Observed: '+addresses.strip())
    from pynq_fixed_ip import CONFIG,configuration
    require(CONFIG.is_file() and CONFIG.read_text()==configuration(address,prefix),'Persistent IP configuration differs')
    require(command('systemctl','is-enabled','networking').strip()=='enabled','networking is not enabled at boot')
    require('eth0:2' in command('ifquery','--list','--allow=auto').splitlines(),'Alias missing from boot configuration')
    listeners=command('ss','-ltn')
    require(bool(re.search(':'+str(port)+r'\s',listeners)),'Notebook port is not listening: '+str(port))
    return dict(addresses=addresses,config_sha256=digest(CONFIG),
                listener_ports=listeners,network_repaired_by_script=False)


def notebook_source(path):
    notebook=json.loads(path.read_text())
    source=[dict(cell_type=c['cell_type'],source=''.join(c['source'])) for c in notebook['cells']]
    return hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest()


def snapshot(root):
    files={}
    for folder in ('scripts','firmware','profiles','results'):
        for path in sorted((root/folder).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc','.zip'):
                files[path.relative_to(root).as_posix()]=dict(size=path.stat().st_size,sha256=digest(path))
    notebooks={path.relative_to(root).as_posix():notebook_source(path)
               for path in (root/'notebooks').glob('*.ipynb')}
    return dict(files=files,notebook_sources=notebooks)


def check_snapshot(root,before):
    bad=[]
    for name,expected in before['snapshot']['files'].items():
        path=root/name
        if not path.is_file() or path.stat().st_size!=expected['size'] or digest(path)!=expected['sha256']:bad.append(name)
    for name,expected in before['snapshot']['notebook_sources'].items():
        path=root/name
        if not path.is_file() or notebook_source(path)!=expected:bad.append(name)
    require(not bad,'Pre-power-cycle files changed/missing: '+', '.join(bad[:20]))
    return len(before['snapshot']['files'])


def read_receipt(directory,phase):
    return json.loads((directory/(phase+'.json')).read_text())


def save_receipt(directory,phase,result):
    target=directory/(phase+'.json')
    if target.exists():
        target=directory/(phase+'_attempt_'+uuid.uuid4().hex[:8]+'.json')
    with target.open('x') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,sort_keys=True)
        stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.sync()
    summary={k:v for k,v in result.items() if k!='snapshot'}
    if 'snapshot' in result:summary['snapshot_files']=len(result['snapshot']['files'])
    print(json.dumps(dict(receipt=str(target),**summary),ensure_ascii=False,sort_keys=True))


def idle_receiver(root,program=False,allow_boot_recovery=False):
    from uart_monitor.urx2 import URX2Transport
    receiver=URX2Transport(root/'firmware/uart_detector2.bit',root/'profiles/car_tlm1.json',
                           program=program,allow_boot_recovery=allow_boot_recovery)
    state=receiver.registers()
    require(all(state[k]==0 for k in ('control','level','event_level','hardware_active')),
            'Receiver active or buffered: stop/save in Notebook before continuing; nothing was cleared')
    result=dict(registers=state,provenance=receiver.provenance)
    receiver.close()
    return result


def execute(args,directory):
    from pynq import PL
    from pynq_hardware_lease import HardwareLease
    from uart_monitor.urx2 import BOOT_BASE_SHA,STARTUP2_PAIR
    root=args.root
    current_boot=boot_id()
    result=dict(phase=args.phase,boot_id=current_boot,root=str(root),status='PASS',
                physical_capture_validated=False,network_repaired_by_script=False)
    require((digest(root/'firmware/uart_detector2.bit'),digest(root/'firmware/uart_detector2.hwh'))==STARTUP2_PAIR,
            'Unverified firmware pair')
    if args.phase=='before':
        require(not (directory/'before.json').exists(),'This run already has a before receipt; choose a new run ID')
        with HardwareLease():
            result.update(network(args.address,args.prefix,args.port))
            result.update(idle_receiver(root))
            result['snapshot']=snapshot(root)
            result['loaded_bit']=PL.bitfile_name
        result['status']='READY_FOR_ORDERLY_SHUTDOWN'
        result['automatic_shutdown_performed']=False
        return result
    before=read_receipt(directory,'before') if (directory/'before.json').is_file() else None
    if args.phase=='observe':
        require(not before,'A before receipt exists; use after instead')
        require(args.previous_boot_id and args.previous_boot_id!=current_boot,
                'A different previously recorded boot ID is required for limited-baseline observation')
        result.update(previous_boot_id=args.previous_boot_id,baseline_limited=True,original_files_verified=None)
    else:
        if before:
            require(before['status']=='READY_FOR_ORDERLY_SHUTDOWN','Before stage did not pass')
            require(before['root']==str(root),'Run directory differs from the before-stage root')
            require(current_boot!=before['boot_id'],'No reboot observed: boot ID unchanged')
        else:
            require(args.phase in ('load','verify') and (directory/'observe.json').is_file(),
                    'Before receipt missing; use observe with the previously recorded boot ID and report the limited baseline')
    if args.phase in ('after','observe'):
        result.update(network(args.address,args.prefix,args.port))
        if before:
            require(result['config_sha256']==before['config_sha256'],'Persistent IP configuration changed')
            result['original_files_verified']=check_snapshot(root,before)
        with HardwareLease():
            loaded=Path(PL.bitfile_name) if PL.bitfile_name else None
            require(loaded and loaded.is_file(),'No loaded overlay metadata')
            result['loaded_bit']=str(loaded);result['loaded_bit_sha256']=digest(loaded)
            require(loaded.as_posix().endswith('/pynq/overlays/base/base.bit') and digest(loaded)==BOOT_BASE_SHA,
                    'Expected default boot image not observed; save this result before any recovery')
        result['status']='PASS_AUTOMATIC_IP_AND_BOOT_IMAGE'
        result['firmware_loaded_by_script']=False
        return result
    after=read_receipt(directory,'after' if before else 'observe')
    require(after['status']=='PASS_AUTOMATIC_IP_AND_BOOT_IMAGE' and after['boot_id']==current_boot,
            'Successful after-stage receipt for this boot is required; do not skip network observation')
    require(after['root']==str(root),'Run directory changed after boot observation')
    result.update(network(args.address,args.prefix,args.port))
    require(result['config_sha256']==after['config_sha256'],'Persistent IP configuration changed')
    result['original_files_verified']=check_snapshot(root,before) if before else None
    result['baseline_limited']=not bool(before)
    with HardwareLease():
        if args.phase=='load':
            require(PL.bitfile_name==after['loaded_bit'] and digest(PL.bitfile_name)==BOOT_BASE_SHA,
                    'Boot application changed since after-stage; preserve it')
            result.update(idle_receiver(root,program=True,allow_boot_recovery=True))
            require(result['provenance']['verified_boot_recovery'],'Verified boot recovery branch was not used')
            result['status']='PASS_EXPLICIT_BOOT_RECOVERY'
        else:
            result.update(idle_receiver(root))
            result['status']='PASS_POWER_RECOVERY_READINESS' if before else 'PASS_POWER_RECOVERY_READINESS_LIMITED_BASELINE'
            result['load_receipt_present']=(directory/'load.json').is_file()
            result['browser_click_tested_by_script']=False
        result['loaded_bit']=PL.bitfile_name
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=['before','after','observe','load','verify'],required=True)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--run',required=True,help='New ASCII run ID; retain the same ID across reboot')
    parser.add_argument('--address',default='169.254.135.99')
    parser.add_argument('--prefix',type=int,default=16)
    parser.add_argument('--port',type=int,default=9090)
    parser.add_argument('--previous-boot-id',help='Only for observe: use a boot ID already recorded before power-off')
    args=parser.parse_args();args.root=args.root.resolve()
    require(bool(re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',args.run)),'Invalid run ID')
    sys.path.insert(0,str(args.root/'scripts'))
    directory=args.root/'validation'/args.run
    directory.mkdir(parents=True,exist_ok=True)
    require(not (directory/(args.phase+'.json')).exists(),'Phase already recorded; retain the prior result')
    try:
        result=execute(args,directory)
    except Exception as error:
        result=dict(status='FAIL',phase=args.phase,error=str(error),boot_id=boot_id(),
                    network_repaired_by_script=False)
        # Failed attempts never occupy the canonical successful stage filename.
        save_receipt(directory,args.phase+'_failed_'+uuid.uuid4().hex[:8],result)
        return 1
    save_receipt(directory,args.phase,result)
    return 0


if __name__=='__main__':sys.exit(main())
