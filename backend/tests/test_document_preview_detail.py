import json

from PIL import Image
from PIL.PngImagePlugin import PngInfo
import pytest

from agent.v2.tools.view_image import view_image


@pytest.mark.asyncio
@pytest.mark.parametrize('marked,detail,width', [(True, None, 1024), (False, None, 512), (True, 'low', 512)])
async def test_document_preview_detail_is_automatic_but_overridable(tmp_path, marked, detail, width):
    info = PngInfo()
    if marked:
        info.add_text('document-preview', '1')
    Image.new('RGB', (1200, 675), 'white').save(tmp_path / 'renamed.png', pnginfo=info)
    result = json.loads(await view_image(path='renamed.png', detail=detail, workspace_dir=str(tmp_path)))
    assert result['size'][0] == width
    assert result['detail'] == ('high' if width == 1024 else 'low')
