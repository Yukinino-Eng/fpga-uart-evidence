"""Prepare or explicitly run a receive-only, repeated car tilt demonstration."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from uart_monitor.profile import load_profile
from uart_monitor.hardware import compile_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['validate', 'preflight', 'capture'])
    parser.add_argument('--profile', type=Path, default=ROOT/'profiles/car_tlm1_tilt_demo.json')
    parser.add_argument('--bit', type=Path, default=ROOT/'firmware/uart_detector2.bit')
    parser.add_argument('--seconds', type=float, default=90)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 0 < args.seconds <= 3600:
        parser.error('--seconds must be in (0,3600]')
    profile = load_profile(args.profile)
    compiled = compile_profile(profile)
    if args.action == 'validate':
        print(json.dumps(dict(status='VALID', profile_id=profile['id'],
                              rules=compiled['rule_ids'], receive_only=True,
                              hardware_accessed=False), ensure_ascii=False, indent=2))
        return 0
    if args.action == 'capture' and not args.output:
        parser.error('capture requires a new --output directory')
    if args.action == 'capture' and args.output.exists():
        parser.error('Preserve existing results; choose a new --output directory')
    # Nothing above imports PYNQ or accesses a board.
    import pynq
    from pynq_hardware_lease import HardwareLease
    from uart_monitor.urx2 import URX2Transport
    from uart_monitor.session import MonitorSession
    from uart_monitor_cli import verify_result

    class Ready(URX2Transport):
        def start(self):
            tick = super().start()
            print('CAR_TILT_RX_READY: keep still for 10 seconds before the first tilt', flush=True)
            return tick

    with HardwareLease():
        transport = Ready(args.bit, profile)
        state = transport.registers()
        if state['control'] or state['level'] or state['event_level'] or state['hardware_active'] & 256:
            raise RuntimeError('Preserve the active receiver or buffered evidence before continuing')
        if args.action == 'preflight':
            print(json.dumps(dict(status='READY', receive_only=True, capture_started=False,
                                  provenance=transport.provenance), sort_keys=True))
            return 0
        report = MonitorSession(profile, args.output, seconds=args.seconds).run(transport)
    verification = verify_result(args.output)
    result = dict(status=report['status'], capture_integrity=report['capture_integrity'],
                  protocol_integrity=report['protocol_integrity'], events=report['event_counts'],
                  evidence=report['evidence'], verification=verification,
                  motor_commands_sent=False, car_firmware_modified=False)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if report['status']=='COMPLETED' and report['capture_integrity']=='PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
