import json
from pathlib import Path
import sys
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from agent.v2 import service
from agent.v2.workspace_commands import can_run_in_workspace, parse_workspace_command, run_workspace_command

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX command adaptation; PowerShell keeps its native path')


@pytest.fixture(autouse=True)
def reset_chat_interrupt_state(monkeypatch):
    # Other service tests intentionally leave an interrupted chat id behind;
    # these tests create fresh chats and exercise command dispatch.
    monkeypatch.setattr(service, '_interrupt_flags', {})


@pytest.mark.parametrize('command', [
    'python script.py', 'python -c "print(1)" | cat',
    'cat input.txt > output.txt', 'cp $(whoami) out', 'echo `pwd`',
    'cat input.txt; touch another.txt', 'cp *.png out',
    'cd', 'cd -', 'cp -a source target', 'curl https://example.com',
])
def test_other_shell_commands_keep_the_permission_path(command):
    assert parse_workspace_command(command) is None


def test_validation_uses_actual_cwd_and_rejects_escape(tmp_path):
    (tmp_path / 'draft').mkdir()
    (tmp_path / 'master.png').write_bytes(b'asset')
    assert can_run_in_workspace('cd draft && cp ../master.png tile.png && ls', tmp_path)
    assert not can_run_in_workspace('cd draft && cp ../../private.png tile.png', tmp_path)
    assert not can_run_in_workspace('cd .. && cat private.txt', tmp_path)


@pytest.mark.asyncio
async def test_copy_then_python_inspection_never_needs_a_shell(session, test_chat, tmp_path):
    (tmp_path / 'draft').mkdir()
    Image.new('RGB', (8, 9), (255, 248, 240)).save(tmp_path / 'master.png')
    (tmp_path / 'draft/info.txt').write_text('Icon files')
    command = 'cd draft && cp ../master.png tile.png && cat info.txt; python -c "from PIL import Image; im=Image.open(\'tile.png\'); print(im.size, im.getpixel((0,0)))"'
    original = Path.cwd()
    result = await run_workspace_command(command, workspace_dir=tmp_path, session=session, chat_id=test_chat.id)
    assert 'Icon files' in result
    assert '(8, 9) (255, 248, 240)' in result
    assert (tmp_path / 'draft/tile.png').is_file()
    assert Path.cwd() == original


@pytest.mark.asyncio
async def test_changed_symlink_is_revalidated_without_shell_fallback(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'source').write_text('Inside')
    outside = tmp_path / 'private'
    outside.write_text('Outside')
    command = 'cp source copied'
    assert can_run_in_workspace(command, workspace)
    (workspace / 'source').unlink()
    (workspace / 'source').symlink_to(outside)
    result = await run_workspace_command(command, workspace_dir=workspace)
    assert result.startswith('Error:')
    assert not (workspace / 'copied').exists()
    assert outside.read_text() == 'Outside'


@pytest.mark.asyncio
async def test_python_uses_existing_restricted_runtime(session, test_chat, tmp_path):
    result = await run_workspace_command('python -c "import subprocess"', workspace_dir=tmp_path, session=session, chat_id=test_chat.id)
    assert "Import 'subprocess' is not allowed" in result


@pytest.mark.asyncio
async def test_service_adapts_before_prompt_and_records_the_actual_result(session, test_chat, mock_ws, tmp_path, monkeypatch):
    (tmp_path / 'info.txt').write_text('Package files')
    monkeypatch.setattr(service, 'get_workspace_dir', lambda _: tmp_path)
    monkeypatch.setattr(service, 'get_permission_decision', AsyncMock(return_value='ask'))
    shell = AsyncMock(side_effect=AssertionError('A real shell must not execute'))
    monkeypatch.setattr(service.get_tool('bash'), 'handler', shell)
    arguments = json.dumps({'command': 'cat info.txt; python -c "print(2 + 3)"'})
    assert not await service._needs_permission('bash', arguments, test_chat, session)
    result = await service._execute_tool_call('bash', arguments, 'test-workspace', test_chat.id, str(tmp_path), None, session, mock_ws, chat=test_chat)
    assert 'Package files' in result and '5' in result
    shell.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_shell_approval_keeps_native_execution(session, test_chat, mock_ws, tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'get_permission_decision', AsyncMock(return_value='ask'))
    shell = AsyncMock(return_value='Native shell output')
    monkeypatch.setattr(service.get_tool('bash'), 'handler', shell)
    result = await service._execute_tool_call('bash', json.dumps({'command': 'cat ../external.txt'}), 'approved-shell', test_chat.id, str(tmp_path), None, session, mock_ws, chat=test_chat, native_shell_approved=True)
    assert result == 'Native shell output'
    shell.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_denial_is_not_bypassed(session, test_chat, tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'get_workspace_dir', lambda _: tmp_path)
    monkeypatch.setattr(service, 'get_permission_decision', AsyncMock(return_value='deny'))
    monkeypatch.setattr(service, 'check_permission_for_call', AsyncMock(return_value=False))
    assert await service._needs_permission('bash', json.dumps({'command': 'python -c "print(1)"'}), test_chat, session)
