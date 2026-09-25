import json

from exif_extractor import parse_external_metadata
from generation_metadata import validate_generation_metadata


def test_comfyui_power_lora_graph():
    graph = {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'fabricated-base.safetensors'}},
        '2': {'class_type': 'Power Lora Loader (rgthree)', 'inputs': {
            'model': ['1', 0],
            'lora_1': {'on': True, 'lora': 'fabricated-turbo.safetensors', 'strength': 0.8},
            'lora_2': {'on': False, 'lora': 'bypassed.safetensors', 'strength': 1.0},
            'lora_3': {'on': True, 'lora': 'None', 'strength': 1.0},
        }},
        '3': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'a paper kite over a field'}},
        '4': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'blurred edges'}},
        '5': {'class_type': 'KSampler', 'inputs': {
            'model': ['2', 0], 'positive': ['3', 0], 'negative': ['4', 0],
            'seed': 48321, 'steps': 12, 'cfg': 1.0,
            'sampler_name': 'euler', 'scheduler': 'beta',
        }},
        '6': {'class_type': 'VAEDecode', 'inputs': {'samples': ['5', 0]}},
        '7': {'class_type': 'SaveImage', 'inputs': {'images': ['6', 0]}},
    }

    metadata = parse_external_metadata(json.dumps(graph))

    validate_generation_metadata(metadata)
    assert metadata['source'] == 'external'
    assert metadata['generator'] == 'comfyui'
    assert metadata['format'] == 'comfyui'
    assert metadata['model'] == 'fabricated-base.safetensors'
    assert metadata['prompt'] == 'a paper kite over a field'
    assert metadata['negative_prompt'] == 'blurred edges'
    assert metadata['parameters'] == {
        'seed': 48321, 'steps': 12, 'cfg': 1.0,
        'sampler': 'euler', 'scheduler': 'beta',
    }
    assert metadata['loras'] == [{'name': 'fabricated-turbo.safetensors', 'weight': 0.8}]


def test_comfyui_checkpoint_and_plain_lora_advanced_sampler():
    graph = {
        '1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': 'sample-checkpoint.safetensors'}},
        '2': {'class_type': 'LoraLoader', 'inputs': {
            'model': ['1', 0], 'lora_name': 'sample-style.safetensors', 'strength_model': 0.6,
        }},
        '3': {'class_type': 'KSamplerAdvanced', 'inputs': {
            'model': ['2', 0], 'noise_seed': 92, 'steps': 18, 'cfg': 2.5,
            'sampler_name': 'dpmpp_2m', 'scheduler': 'normal',
        }},
    }

    metadata = parse_external_metadata(json.dumps(graph))

    assert metadata['model'] == 'sample-checkpoint.safetensors'
    assert metadata['loras'] == [{'name': 'sample-style.safetensors', 'weight': 0.6}]
    assert metadata['parameters'] == {
        'seed': 92, 'steps': 18, 'cfg': 2.5,
        'sampler': 'dpmpp_2m', 'scheduler': 'normal',
    }


def test_a1111_and_unknown_metadata_still_behave():
    metadata = parse_external_metadata(
        'a pencil sketch\nNegative prompt: noisy\n'
        'Steps: 20, Sampler: Euler, CFG scale: 7, Seed: 123, Model: example'
    )
    assert metadata['format'] == 'a1111'
    assert metadata['prompt'] == 'a pencil sketch'
    assert metadata['negative_prompt'] == 'noisy'
    assert metadata['parameters']['steps'] == 20
    assert parse_external_metadata('{"other": "data"}') is None
    assert parse_external_metadata('{invalid') is None
