"""Android implementation of the first-party mobile CLI."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
ANDROID = ROOT / 'mobile' / 'android'
GRADLE_VERSION = '9.1.0'
GRADLE_SHA256 = 'a17ddd85a26b6a7f5ddb71ff8b05fc5104c0202c6e64782429790c933686c806'


def environment():
    env = dict(os.environ)
    env.setdefault('ANDROID_HOME', str(Path.home() / 'Library/Android/sdk'))
    for candidate in [Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home'),
                      Path('/Applications/Android Studio.app/Contents/jbr/Contents/Home')]:
        if 'JAVA_HOME' not in env and candidate.exists():
            env['JAVA_HOME'] = str(candidate)
    return env


def run(command, **kwargs):
    return subprocess.run([str(part) for part in command], check=True, env=kwargs.pop('env', environment()), **kwargs)


def gradle():
    home = ANDROID / '.build' / f'gradle-{GRADLE_VERSION}'
    executable = home / 'bin/gradle'
    if not executable.exists():
        home.parent.mkdir(parents=True, exist_ok=True)
        archive = home.parent / 'gradle.zip'
        urllib.request.urlretrieve(f'https://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip', archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != GRADLE_SHA256:
            archive.unlink()
            raise SystemExit('Gradle distribution checksum mismatch')
        with zipfile.ZipFile(archive) as package:
            package.extractall(home.parent)
        executable.chmod(0o755)
        archive.unlink()
    return executable


def android_main(args):
    sdk = Path(environment()['ANDROID_HOME'])
    adb = sdk / 'platform-tools/adb'
    target = [adb, '-s', args.device] if args.device else [adb, '-e']
    if args.action == 'doctor':
        for name, path in [('JDK', Path(environment().get('JAVA_HOME', '/missing')) / 'bin/java'),
                           ('ADB', adb), ('Emulator', sdk / 'emulator/emulator'),
                           ('API 36', sdk / 'platforms/android-36/android.jar')]:
            print(f'{name}: {"installed" if path.exists() else "missing"}')
        if adb.exists():
            run([adb, 'devices'])
        return
    if args.action == 'lint':
        run([gradle(), '--console=plain', 'lintDebug'], cwd=ANDROID)
        return
    if args.action not in {'build', 'run', 'test', 'test-ui', 'screenshot'}:
        raise SystemExit('Android supports doctor, build, run, test, test-ui, and screenshot')
    if args.action == 'screenshot':
        destination = Path(args.output) if args.output else ANDROID / '.build/emulator.png'
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('wb') as output:
            run([*target, 'exec-out', 'screencap', '-p'], stdout=output)
        return
    if args.action != 'test' and not args.skip_frontend:
        frontend = ROOT / 'frontend'
        if not (frontend / 'node_modules').exists():
            run(['npm', 'ci'], cwd=frontend)
        subprocess.run(['npm', 'run', 'build'], cwd=frontend, check=True,
                       env=dict(environment(), STIMMA_MOBILE_SHELL='1'))
        assets = ANDROID / 'app/src/main/assets'
        shutil.rmtree(assets, ignore_errors=True)
        shutil.copytree(frontend / 'dist-mobile', assets)
    if args.action != 'test' and not (ANDROID / 'app/src/main/assets/mobile.html').exists():
        raise SystemExit('Bundled UI missing. Build without --skip-frontend first.')
    task = 'testDebugUnitTest' if args.action == 'test' else 'assembleDebug'
    run([gradle(), '--console=plain', task], cwd=ANDROID)
    if args.action == 'test':
        run(['npm', 'run', 'test:desktop-bridge'], cwd=ROOT / 'frontend')
        run(['node', '--test', '--experimental-strip-types',
             'tests/websocketResume.test.mjs', 'tests/connectionPresentation.test.mjs',
             'tests/viewportRotation.test.mjs', 'tests/mobileReadiness.test.mjs',
             'tests/mobileReadiness.browser.test.mjs'], cwd=ROOT / 'frontend',
            env=dict(environment(), STIMMA_TEST_MOBILE_PLATFORM='android'))
        return
    if args.action == 'build':
        return
    devices = run([adb, 'devices'], capture_output=True, text=True).stdout
    if not any(line.startswith(args.device + '\t' if args.device else 'emulator-') and '\tdevice' in line for line in devices.splitlines()):
        avds = run([sdk / 'emulator/emulator', '-list-avds'], capture_output=True, text=True).stdout.splitlines()
        name = args.simulator or next(iter(avds), None)
        if not name:
            raise SystemExit('No Android virtual device. Create an API 36 ARM64 AVD with avdmanager.')
        log = (ANDROID / '.build/emulator.log').open('w')
        emulator_command = [str(sdk / 'emulator/emulator'), '-avd', name, '-no-snapshot-load']
        if args.device:
            if not args.device.startswith('emulator-') or not args.device[9:].isdigit():
                raise SystemExit('Connect the requested device first, or use an emulator-NNNN serial.')
            emulator_command += ['-port', args.device[9:], '-read-only']
        subprocess.Popen(emulator_command,
                         env=environment(), stdout=log, stderr=log, start_new_session=True)
        log.close()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            boot = subprocess.run([str(part) for part in [*target, 'shell', 'getprop', 'sys.boot_completed']],
                                  capture_output=True, text=True)
            if boot.stdout.strip() == '1':
                break
            time.sleep(2)
        else:
            raise SystemExit('Android emulator did not boot within three minutes')
    if args.action == 'test-ui':
        command = [gradle(), '--console=plain', 'connectedDebugAndroidTest']
        if args.local_backend_port:
            if not 1024 <= args.local_backend_port <= 65535:
                raise SystemExit('Invalid isolated backend port')
            run([*target, 'reverse', f'tcp:{args.local_backend_port}', f'tcp:{args.local_backend_port}'])
            command += [f'-Pandroid.testInstrumentationRunnerArguments.localBackendPort={args.local_backend_port}']
        test_env = environment()
        if args.device:
            test_env['ANDROID_SERIAL'] = args.device
        run(command, cwd=ANDROID, env=test_env)
        return
    run([*target, 'install', '-r', ANDROID / 'app/build/outputs/apk/debug/app-debug.apk'])
    run([*target, 'shell', 'am', 'force-stop', 'ai.stimma.mobile.debug'])
    launch = [*target, 'shell', 'am', 'start', '-f', '0x14000000', '-n', 'ai.stimma.mobile.debug/ai.stimma.mobile.MainActivity']
    if args.local_backend_port:
        if not 1024 <= args.local_backend_port <= 65535:
            raise SystemExit('Invalid isolated backend port')
        run([*target, 'reverse', f'tcp:{args.local_backend_port}', f'tcp:{args.local_backend_port}'])
        launch += ['--ei', 'localBackendPort', str(args.local_backend_port)]
    run(launch)
