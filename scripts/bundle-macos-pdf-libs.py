"""Vendor WeasyPrint's native libraries and relocate their dependency closure.

Run on macOS after installing Homebrew pango. The result needs no Homebrew
installation on the recipient's machine. Signing happens after relocation.
"""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT_LIBS = (
    'libgobject-2.0.0.dylib', 'libpango-1.0.dylib',
    'libpangoft2-1.0.dylib', 'libharfbuzz.0.dylib',
    'libharfbuzz-subset.0.dylib',
)


def dependencies(path):
    output = subprocess.check_output(['otool', '-L', str(path)], text=True)
    # The first entry is the library's own install name.
    return [line.strip().split(' (', 1)[0] for line in output.splitlines()[2:]]


def bundle(output, prefix):
    # Hardened Python ignores DYLD_* overrides. Its native loader searches
    # the interpreter's lib directory even after distribution signing.
    destination = output / 'python' / 'lib'
    destination.mkdir(parents=True, exist_ok=True)
    pending = [prefix / 'lib' / name for name in ROOT_LIBS]
    copied = {}
    while pending:
        source = pending.pop()
        name = source.resolve().name
        # Several public sonames can refer to the same library. Preserve them
        # as symlinks: duplicate copies register Pango's GObject types twice.
        if source.name != name:
            alias = destination / source.name
            if not alias.exists():
                alias.symlink_to(name)
        if name in copied:
            if copied[name] != source.resolve():
                raise RuntimeError(f'Conflicting native PDF libraries: {name}')
            continue
        if not source.is_file():
            raise RuntimeError(f'Missing PDF library: {name}; install Homebrew pango')
        copied[name] = source.resolve()
        target = destination / name
        shutil.copy2(source, target)
        target.chmod(0o755)
        subprocess.run(['install_name_tool', '-id', f'@loader_path/{name}', str(target)], check=True)
        for dependency in dependencies(source):
            if dependency.startswith(('/usr/lib/', '/System/Library/')):
                continue
            if dependency.startswith('@loader_path/'):
                dep = source.resolve().parent / dependency.removeprefix('@loader_path/')
            elif dependency.startswith('@rpath/'):
                dep = prefix / 'lib' / dependency.removeprefix('@rpath/')
            elif dependency.startswith('/'):
                dep = Path(dependency)
            else:
                raise RuntimeError(f'Unresolved PDF dependency: {dependency}')
            pending.append(dep)
            subprocess.run(['install_name_tool', '-change', dependency,
                            f'@loader_path/{dep.resolve().name}', str(target)], check=True)
        # Homebrew retains upstream license notices at the keg root.
        for parent in source.resolve().parents:
            if parent.parent.name == 'Cellar' or parent.parent.parent.name == 'Cellar':
                license_dir = output / 'licenses' / 'pdf' / parent.parent.name
                for notice in parent.glob('*'):
                    if notice.is_file() and notice.name.upper().startswith(('COPYING', 'LICENSE', 'NOTICE')):
                        license_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(notice, license_dir / notice.name)
                break
    # Fontconfig's compiled default points into Homebrew. Ship its portable
    # macOS font discovery/alias rules, using the recipient's own font cache.
    fonts = destination / 'fonts'
    shutil.copytree(prefix / 'etc' / 'fonts', fonts, symlinks=False, dirs_exist_ok=True)
    config = fonts / 'fonts.conf'
    config.write_text(config.read_text().replace(
        f'<cachedir>{prefix}/var/cache/fontconfig</cachedir>', ''
    ))
    # No dependency may retain a build-machine path after relocation.
    for name in copied:
        library = destination / name
        if any(not dep.startswith(('@loader_path/', '/usr/lib/', '/System/Library/'))
               for dep in dependencies(library)):
            raise RuntimeError(f'Unrelocated PDF library: {library.name}')
    # Relocation invalidates bottle signatures. Ad-hoc sign even when the
    # enclosing build defers distribution signing to the desktop packager.
    for name in copied:
        library = destination / name
        if not library.is_symlink():
            subprocess.run(['codesign', '--force', '--sign', '-', str(library)], check=True)


if __name__ == '__main__':
    prefix = Path(subprocess.check_output(['brew', '--prefix'], text=True).strip())
    bundle(Path(sys.argv[1]), prefix)
