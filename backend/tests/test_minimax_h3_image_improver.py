"""H3 Image enhancement uses its own captions and ordered image references."""
from unittest.mock import AsyncMock

import pytest

from prompt_formats import prompt_format_requirements
from routes import prompt_enhancement as pe
from routes import generation as gen


@pytest.mark.parametrize('edit,mode,key', [
    (False, 'minimax-h3-image', 'improve_minimax_h3_image_system_prompt'),
    (True, 'minimax-h3-image-edit', 'improve_minimax_h3_image_edit_system_prompt'),
])
async def test_image_guide_and_off_level(edit, mode, key):
    request = pe.ImprovePromptRequest(prompt='a dog', model='minimax-h3-image', input_image_count=int(edit))
    guide, images, actual_mode = await pe.style_guide(request, None)
    assert actual_mode == mode
    assert 'MiniMax H3 Image' in guide
    assert 'Context-IR' not in guide
    assert 'overall_soundscape' not in guide
    assert '{protected_text_guidance}' not in guide
    assert not pe.improve_needed(request.prompt, mode, 'off')
    assert prompt_format_requirements('MiniMax H3 Image') == {'required': False}
    if edit:
        assert '<Picture 1>' in guide and '<Subject N>' in guide
        assert 'fully preserved' in guide
    else:
        assert 'rather than filling a word quota' in guide
        assert 'The people are fixed' in guide


async def test_edit_improver_sees_images_without_renumbering_missing_slots(monkeypatch):
    monkeypatch.setattr('llm_resolver.get_effective_llm_config', AsyncMock(return_value={}))
    complete = AsyncMock(return_value='The target image contains a blue cup.')
    monkeypatch.setattr(pe, 'llm_complete_text', complete)
    load = AsyncMock(side_effect=lambda _session, media_id: f'image-{media_id}')
    monkeypatch.setattr(pe, '_load_source_image_b64', load)
    await pe.improve_prompt(pe.ImprovePromptRequest(
        prompt='Make [the cup] blue', model='minimax-h3-image', input_image_count=3,
        input_media_ids=[11, None, 33], width=4096, height=4096), None)
    messages = complete.await_args.kwargs['messages']
    assert '<Subject N>' in messages[0]['content']
    assert 'keep the brackets and their contents exactly as written' in messages[0]['content']
    content = messages[1]['content']
    assert content[0]['text'].startswith('Rewrite this MiniMax H3 Image reference-image edit request.')
    assert '[the cup]' in content[0]['text']
    assert [p['text'] for p in content[1::2]] == ['<Picture 1>:', '<Picture 3>:']
    assert [p['image_url']['url'] for p in content[2::2]] == [
        'data:image/jpeg;base64,image-11', 'data:image/jpeg;base64,image-33']


def test_generation_context_passes_reference_ids_and_disables_edit_programs(monkeypatch):
    monkeypatch.setattr(gen, '_prompt_pipeline_context', lambda *args:
                        ('minimax-h3-image', 'minimax', 'image-to-image', {}))
    ctx = gen.prompt_enhance_context({'input_images': ['a.png', 'b.png'],
                                    'input_media_ids': [None, 33]}, 'p:h3', 'image-to-image', None)
    assert ctx['mode'] == 'minimax-h3-image-edit'
    assert ctx['enhance']['input_media_ids'] == [None, 33]
    assert ctx['enhance']['h3_task'] is None
    assert ctx['program_supported'] is False
    assert gen.native_prompt_format('p:h3', 'image-to-image') == 'MiniMax H3 Image'
