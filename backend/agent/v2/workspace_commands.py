"""Run a small set of literal file/Python commands through workspace capabilities.

This never executes a shell. Anything outside this grammar keeps the ordinary
shell permission path. Approval and execution both validate file locations;
execution never falls back to a shell after a workspace operation fails.
"""
from __future__ import annotations

from pathlib import Path
import shlex
import sys


def parse_workspace_command(command: str) -> list[list[str]] | None:
    if sys.platform == "win32":
        return None  # PowerShell has different quoting and command semantics.
    if not command or any(char in command for char in ('$', '`')):
        return None
    lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|<>()')
    lexer.whitespace_split = True
    lexer.commenters = ''
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    steps, current = [], []
    for token in tokens:
        if token in (';', '&&'):
            if not current:
                return None
            steps.append(current)
            current = []
        elif token and all(c in ';&|<>()' for c in token):
            return None
        else:
            current.append(token)
    if current:
        steps.append(current)
    if not steps:
        return None
    for step in steps:
        name, *args = step
        if name in ('python', 'python3'):
            if len(args) != 2 or args[0] != '-c':
                return None
        elif name == 'cd':
            if len(args) != 1 or args[0].startswith(('-', '~')):
                return None
        elif name == 'cp':
            if len(args) != 2 or any(a.startswith(('-', '~')) for a in args):
                return None
        elif name == 'cat':
            if not args or any(a.startswith(('-', '~')) for a in args):
                return None
        elif name == 'ls':
            if any(a.startswith('-') and a not in ('-l', '-a', '-la', '-al') for a in args):
                return None
            if len([a for a in args if not a.startswith('-')]) > 1:
                return None
        elif name == 'pwd':
            if args:
                return None
        elif name == 'echo':
            if args and args[0] in ('-n', '-e', '-E'):
                return None
        else:
            return None
        if name not in ('python', 'python3', 'echo') and any(any(c in a for c in '*?[]~') for a in args):
            return None
    return steps


def validate_workspace_steps(steps: list[list[str]], workspace: Path) -> None:
    from .code_runtime import _make_workspace_resolver
    root = workspace.resolve()
    read = _make_workspace_resolver(root, read_only=True)
    write = _make_workspace_resolver(root)
    cwd = root
    for name, *args in steps:
        if name == 'cd':
            cwd = read(cwd / args[0])
            if not cwd.is_relative_to(root) or not cwd.is_dir():
                raise ValueError('cd must name a directory inside the chat workspace')
        elif name == 'cp':
            source = read(cwd / args[0])
            destination = write(cwd / args[1])
            if destination.is_dir():
                write(destination / source.name)
        elif name == 'cat':
            for path in args:
                read(cwd / path)
        elif name == 'ls':
            read(cwd / next((a for a in args if not a.startswith('-')), '.'))


def can_run_in_workspace(command: str, workspace: str | Path) -> bool:
    steps = parse_workspace_command(command)
    if steps is None:
        return False
    try:
        validate_workspace_steps(steps, Path(workspace))
    except (OSError, ValueError):
        return False
    return True


async def run_workspace_command(command: str, **kwargs) -> str:
    from .code_runtime import _SafeOS, _SafeShutil, _make_safe_open
    from .tools.run_code import run_code
    steps = parse_workspace_command(command)
    if steps is None:
        return 'Error: This command needs the shell permission path.'
    root = Path(kwargs['workspace_dir']).resolve()
    output = []
    try:
        validate_workspace_steps(steps, root)
        reader = _make_safe_open(root)
        files = _SafeShutil(root)
        scoped_os = _SafeOS(root)
        cwd = root
        for name, *args in steps:
            if name == 'cd':
                cwd = (cwd / args[0]).resolve()
                if not cwd.is_relative_to(root) or not cwd.is_dir():
                    raise ValueError('cd must stay inside the chat workspace')
            elif name == 'cp':
                files.copy(cwd / args[0], cwd / args[1])
            elif name == 'cat':
                for path in args:
                    with reader(cwd / path, errors='replace') as source:
                        output.append(source.read(10_000))
            elif name == 'ls':
                target = cwd / next((a for a in args if not a.startswith('-')), '.')
                scoped_os.stat(target)
                names = sorted(scoped_os.listdir(target)) if target.is_dir() else [target.name]
                if not any('a' in a for a in args if a.startswith('-')):
                    names = [n for n in names if not n.startswith('.')]
                output.append('\n'.join(names))
            elif name == 'pwd':
                output.append(str(cwd))
            elif name == 'echo':
                output.append(' '.join(args))
            else:
                context = dict(kwargs)
                context['workspace_dir'] = cwd
                # A prior cd changes relative paths, not the permitted root.
                context['project_workspace_dir'] = root
                result = await run_code(code=args[1], **context)
                if result.startswith(('Error', 'Code has issues')):
                    return result
                output.append(result)
    except (OSError, ValueError) as exc:
        return f'Error: {exc}'
    return ('Executed with workspace file/Python tools.\n' + '\n'.join(output))[:10_000]
