"""Resource discovery works across mounted packs, without following arbitrary links."""
import pytest
from agent.v2.tools.glob_files import glob_files


@pytest.mark.asyncio
@pytest.mark.parametrize('pattern,path', [
    ('.stimma/skills/**/label-cover.html', None),
    ('.stimma/skills/stimma-*/**/label-cover.html', None),
    ('**/label-cover.html', '.stimma/skills'),
    ('.stimma/skills/stimma-labels/**/label-cover.html', None),
])
async def test_glob_across_skill_resources_without_symlinks(tmp_path, monkeypatch, pattern, path):
    workspace = tmp_path / 'workspace'
    (workspace / '.stimma/skills').mkdir(parents=True)
    pack = tmp_path / 'pack'
    reference = pack / 'skills/label-design/references/label-cover.html'
    reference.parent.mkdir(parents=True)
    reference.write_text('<h1>Label guide</h1>')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.html').write_text('private')
    (pack / 'escape').symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr('agent.v2.tools._workspace_files.skill_resource_roots',
                        lambda: {'stimma-labels': pack})
    result = await glob_files(pattern=pattern, path=path, workspace_dir=str(workspace))
    assert result == '.stimma/skills/stimma-labels/skills/label-design/references/label-cover.html'
    escaped = await glob_files(pattern='.stimma/skills/**/secret.html', workspace_dir=str(workspace))
    assert 'No files or directories' in escaped
