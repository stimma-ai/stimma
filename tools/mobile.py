#!/usr/bin/env python3
"""Native mobile build/run entry point, invoked by tools/stimma mobile."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
IOS = ROOT / 'mobile' / 'ios'
BUILD = IOS / '.build'


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def capture(args):
    return subprocess.check_output([str(a) for a in args], text=True)


def build(args, device=False):
    if not args.skip_frontend:
        frontend = ROOT / 'frontend'
        if not (frontend / 'node_modules').exists():
            run(['npm', 'ci'], cwd=frontend)
        run(['npm', 'run', 'build'], cwd=frontend, env=dict(os.environ, STIMMA_MOBILE_SHELL='1'))
        if (IOS / 'Frontend').exists():
            shutil.rmtree(IOS / 'Frontend')
        shutil.copytree(frontend / 'dist-mobile', IOS / 'Frontend')
    if not (IOS / 'Frontend' / 'mobile.html').exists():
        raise SystemExit('Frontend missing. Build without --skip-frontend first.')
    run(['xcodegen', 'generate', '--spec', IOS / 'project.yml'], cwd=IOS)
    cmd = ['xcodebuild', '-project', IOS / 'StimmaMobile.xcodeproj', '-scheme', 'StimmaMobile',
           '-configuration', 'Debug', '-sdk', 'iphoneos' if device else 'iphonesimulator',
           '-destination', 'generic/platform=iOS' if device else 'generic/platform=iOS Simulator',
           '-derivedDataPath', BUILD, 'build']
    if device:
        team = args.team or os.environ.get('STIMMA_APPLE_TEAM')
        if args.unsigned_device:
            cmd += ['CODE_SIGNING_ALLOWED=NO']
        elif not team:
            raise SystemExit('Use --team TEAM_ID or set STIMMA_APPLE_TEAM for device signing.')
        else:
            cmd += [f'DEVELOPMENT_TEAM={team}', '-allowProvisioningUpdates', '-allowProvisioningDeviceRegistration']
    else:
        cmd += ['CODE_SIGNING_ALLOWED=YES', 'CODE_SIGN_IDENTITY=-']
    BUILD.mkdir(parents=True, exist_ok=True)
    with (BUILD / 'build.log').open('w') as log:
        result = subprocess.run([str(a) for a in cmd], cwd=IOS, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print('\n'.join((BUILD / 'build.log').read_text().splitlines()[-70:]))
        raise SystemExit(result.returncode)
    print('iOS build succeeded.')
    return BUILD / 'Build' / 'Products' / ('Debug-iphoneos' if device else 'Debug-iphonesimulator') / 'StimmaMobile.app'


def simulator(requested):
    devices = json.loads(capture(['xcrun', 'simctl', 'list', 'devices', 'available', '-j']))['devices']
    phones = [d for group in devices.values() for d in group if d['name'].startswith('iPhone')]
    if requested:
        match = next((d for d in phones if d['udid'] == requested or d['name'] == requested), None)
    else:
        match = next((d for d in phones if d['state'] == 'Booted'), None) or phones[-1]
    if not match:
        raise SystemExit('No matching iPhone simulator. Install an iOS runtime in Xcode.')
    if match['state'] != 'Booted':
        run(['xcrun', 'simctl', 'boot', match['udid']])
    run(['open', '-a', 'Simulator'])
    run(['xcrun', 'simctl', 'bootstatus', match['udid'], '-b'])
    return match['udid']


def main():
    parser = argparse.ArgumentParser(description='Build and run the native Stimma iOS shell')
    parser.add_argument('platform', choices=['ios'])
    parser.add_argument('action', choices=['build', 'run', 'device', 'doctor', 'screenshot', 'test', 'test-ui', 'package'])
    parser.add_argument('--skip-frontend', action='store_true')
    parser.add_argument('--simulator', help='Simulator name or UDID')
    parser.add_argument('--device', help='Physical device identifier')
    parser.add_argument('--team', help='Apple Developer team ID (kept out of source)')
    parser.add_argument('--output', help='Screenshot path')
    parser.add_argument('--local-backend-port', type=int, help='Simulator Debug only: isolated loopback test backend')
    parser.add_argument('--unsigned-device', action='store_true', help='Build only: compile for physical iOS without signing')
    args = parser.parse_args()
    if args.unsigned_device and args.action != 'build':
        parser.error('--unsigned-device is only valid with build')
    if args.action == 'package':
        frontend = ROOT / 'frontend'
        if not args.skip_frontend:
            if not (frontend / 'node_modules').exists():
                run(['npm', 'ci'], cwd=frontend)
            run(['npm', 'run', 'build'], cwd=frontend, env=dict(os.environ, STIMMA_MOBILE_SHELL='0'))
        run(['python3', ROOT / 'tools' / 'build_ui_package.py', frontend / 'dist', ROOT / 'backend' / 'mobile-ui'])
        return
    if args.action == 'test':
        run(['bash', IOS / 'Tests' / 'run.sh'], cwd=ROOT)
        run(['npm', 'run', 'test:desktop-bridge'], cwd=ROOT / 'frontend')
        return
    if args.action == 'doctor':
        run(['xcodebuild', '-version'])
        run(['xcrun', 'simctl', 'list', 'devices', 'available'])
        print('xcodegen:', 'installed' if shutil.which('xcodegen') else 'missing')
        return
    if args.action == 'screenshot':
        run(['xcrun', 'simctl', 'io', args.simulator or 'booted', 'screenshot', args.output or BUILD / 'simulator.png'])
        return
    app = build(args, device=args.action == 'device' or args.unsigned_device)
    if args.action == 'test-ui':
        udid = simulator(args.simulator)
        run(['xcodebuild', '-project', IOS / 'StimmaMobile.xcodeproj', '-scheme', 'StimmaMobile',
             '-destination', f'platform=iOS Simulator,id={udid}', '-derivedDataPath', BUILD,
             'test', 'CODE_SIGNING_ALLOWED=YES', 'CODE_SIGN_IDENTITY=-'], cwd=IOS)
        return
    if args.action == 'run':
        udid = simulator(args.simulator)
        subprocess.run(['xcrun', 'simctl', 'terminate', udid, 'ai.stimma.mobile'], capture_output=True)
        run(['xcrun', 'simctl', 'install', udid, app])
        launch = ['xcrun', 'simctl', 'launch', udid, 'ai.stimma.mobile']
        if args.local_backend_port:
            if not 1024 <= args.local_backend_port <= 65535:
                raise SystemExit('Invalid local backend port')
            launch += ['--local-backend-port', str(args.local_backend_port)]
        run(launch)
    elif args.action == 'device':
        if not args.device:
            print('Device build ready. Supply --device to install and launch.')
            return
        run(['xcrun', 'devicectl', 'device', 'install', 'app', '--device', args.device, app])
        run(['xcrun', 'devicectl', 'device', 'process', 'launch', '--device', args.device, 'ai.stimma.mobile'])


if __name__ == '__main__':
    main()
