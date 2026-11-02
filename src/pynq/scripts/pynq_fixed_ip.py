"""Persist a PYNQ wired IP without restarting networking or touching PL (Python 3.6)."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess

CONFIG=Path('/etc/network/interfaces.d/urx2-static-ip')


def configuration(address,prefix):
    ip=ipaddress.IPv4Address(address)
    network=ipaddress.IPv4Network('{}/{}'.format(ip,prefix),strict=False)
    if ip.is_multicast or ip.is_loopback or ip.is_unspecified or ip in (network.network_address,network.broadcast_address):
        raise ValueError('Choose a usable unicast IPv4 host address')
    return ('# Persistent wired address for the existing PYNQ acceptance URL.\n'
            'auto eth0:2\niface eth0:2 inet static\n'
            '    address {}\n    netmask {}\n').format(ip,network.netmask)


def command(*args):
    return subprocess.check_output(list(args),stderr=subprocess.STDOUT).decode()


def apply(address,prefix,remove=False):
    content=configuration(address,prefix)
    if os.geteuid()!=0:raise RuntimeError('Run with sudo; no password is stored by this script')
    interfaces=Path('/etc/network/interfaces').read_text()
    if not re.search(r'^\s*source-directory\s+/etc/network/interfaces\.d\s*$',interfaces,re.M):
        raise RuntimeError('Unsupported network configuration; no files changed')
    if command('systemctl','is-enabled','networking').strip()!='enabled':
        raise RuntimeError('The networking boot service must already be enabled')
    before=command('ip','-o','-4','addr','show','dev','eth0')
    if CONFIG.exists() and CONFIG.read_text()!=content:
        raise RuntimeError('Existing IP configuration differs; preserve it and inspect it first')
    if remove:
        if CONFIG.exists():CONFIG.unlink()
        os.sync()
        return dict(status='REMOVED_PERSISTENCE',live_addresses_changed=False,config=str(CONFIG))
    for path in CONFIG.parent.iterdir():
        if path.is_file() and path!=CONFIG:
            text=path.read_text()
            if re.search(r'(^|\s)eth0:2(?=\s|$)',text) or re.search(r'^\s*address\s+'+re.escape(address)+r'\s*$',text,re.M):
                raise RuntimeError('Address or eth0:2 already configured in '+str(path))
    created=not CONFIG.exists()
    added=False
    if created:
        with CONFIG.open('x') as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())
        CONFIG.chmod(0o644)
    try:
        parsed=command('ifquery','eth0:2')
        if 'eth0:2' not in command('ifquery','--list','--allow=auto').splitlines():
            raise RuntimeError('Alias not included in automatic boot configuration')
        if address not in parsed:raise RuntimeError('Configured address did not parse correctly')
        dry_run=command('ifup','--no-act','eth0:2')
        if not re.search(r'\binet '+re.escape(address)+'/'+str(prefix)+r'\b',before):
            if re.search(r'\binet '+re.escape(address)+r'/',before):
                raise RuntimeError('Live address has a different prefix; not changing it')
            command('ip','addr','add','{}/{}'.format(address,prefix),'dev','eth0')
            added=True
        after=command('ip','-o','-4','addr','show','dev','eth0')
        if not re.search(r'\binet '+re.escape(address)+'/'+str(prefix)+r'\b',after):
            raise RuntimeError('Live IP verification failed')
        os.sync()
    except BaseException:
        if added:command('ip','addr','del','{}/{}'.format(address,prefix),'dev','eth0')
        if created:CONFIG.unlink()
        raise
    return dict(status='PERSISTENT_IP_CONFIGURED',address=address,prefix=prefix,config=str(CONFIG),
                addresses=after,parser=parsed,dry_run=dry_run,new_live_alias=added,
                reboot_tested=False,network_service_restarted=False,firmware_changed=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address',default='169.254.135.99')
    parser.add_argument('--prefix',type=int,default=16)
    parser.add_argument('--remove',action='store_true',help='Remove this exact persistent configuration; keep the live IP')
    args=parser.parse_args()
    print(json.dumps(apply(args.address,args.prefix,args.remove),sort_keys=True,indent=2))
