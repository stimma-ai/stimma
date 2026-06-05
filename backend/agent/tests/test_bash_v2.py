from types import SimpleNamespace

import pytest

from agent.v2.tools.bash import bash


class _FakeProc:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        return None


@pytest.mark.asyncio
async def test_bash_uses_powershell_on_windows(monkeypatch, tmp_path):
    calls = []

    async def _fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeProc(stdout=b"ok")

    monkeypatch.setattr("agent.v2.tools.bash.is_windows_host", lambda: True)
    monkeypatch.setattr("agent.v2.tools.bash.asyncio.create_subprocess_exec", _fake_exec)

    result = await bash("Get-ChildItem", workspace_dir=tmp_path)

    assert result == "ok"
    assert calls
    args, kwargs = calls[0]
    assert args == ("powershell", "-NoProfile", "-Command", "Get-ChildItem")
    assert kwargs["cwd"] == str(tmp_path)


@pytest.mark.asyncio
async def test_bash_uses_bash_when_available_on_non_windows(monkeypatch, tmp_path):
    calls = []

    async def _fake_shell(command, **kwargs):
        calls.append((command, kwargs))
        return _FakeProc(stdout=b"ok")

    monkeypatch.setattr("agent.v2.tools.bash.is_windows_host", lambda: False)
    monkeypatch.setattr("agent.v2.tools.bash.shutil.which", lambda name: "/bin/bash" if name == "bash" else None)
    monkeypatch.setattr("agent.v2.tools.bash.asyncio.create_subprocess_shell", _fake_shell)

    result = await bash("ls -la", workspace_dir=tmp_path)

    assert result == "ok"
    assert calls
    command, kwargs = calls[0]
    assert command == "ls -la"
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["executable"] == "/bin/bash"
