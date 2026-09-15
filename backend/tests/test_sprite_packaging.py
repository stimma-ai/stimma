"""Portable sprite handoff: actual pixels, paths, timing and deterministic bytes."""
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from sprite_export import ExportAnimation, SpriteExportError, SpriteExportOptions, SpriteSource, run_sprite_export
from sprite_source import read_source, write_source


def source(loop="loop"):
    frames = [Image.new("RGBA", (16, 24), (i * 60, 10, 30, 100 + i * 40)) for i in range(3)]
    return SpriteSource("Courier", "courier", (0.5, 0.9), [ExportAnimation(
        "run", "east", 12, loop, 0, 2, frames, [83, 127, 211])], pixelated=True)


def test_source_roundtrip_and_determinism(tmp_path):
    original = source()
    a = write_source(original, tmp_path / "a.zip", usage={"mirror_safe": True})
    b = write_source(original, tmp_path / "b.zip", usage={"mirror_safe": True})
    assert a.read_bytes() == b.read_bytes()
    loaded, usage = read_source(a)
    assert usage == {"mirror_safe": True}
    assert loaded.anchor == original.anchor
    assert loaded.animations[0].durations_ms == [83, 127, 211]
    assert [f.tobytes() for f in loaded.animations[0].frames] == [f.tobytes() for f in original.animations[0].frames]
    options = SpriteExportOptions(format="atlas-hash", padding=2)
    assert run_sprite_export(loaded, options).payload == run_sprite_export(loaded, options).payload


def test_rejects_registration_mismatch_and_invalid_timing(tmp_path):
    s = source()
    s.animations[0].frames[1] = Image.new("RGBA", (17, 24))
    with pytest.raises(SpriteExportError, match="share a canvas") as error:
        write_source(s, tmp_path / "bad.zip")
    assert "courier" in str(error.value) and "run_east: 16x24, 17x24" in str(error.value)
    assert "separate source archives/recipe runs" in str(error.value)
    s = source()
    s.animations[0].durations_ms[0] = 0
    with pytest.raises(SpriteExportError, match="positive integer"):
        write_source(s, tmp_path / "bad.zip")


def test_rejects_unsafe_archive(tmp_path):
    p = tmp_path / "bad.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("../escape.png", b"bad")
    with pytest.raises(SpriteExportError, match="unsafe"):
        read_source(p)


def test_godot_pingpong_and_exact_duration():
    s = source("pingpong")
    result = run_sprite_export(s, SpriteExportOptions(format="godot"))
    with zipfile.ZipFile(io.BytesIO(result.payload)) as z:
        text = z.read("courier.tres").decode()
    assert text.count('[sub_resource type="AtlasTexture"') == 4
    assert '"loop": true' in text
    durations = [float(line.split(':')[1].rstrip(',')) for line in text.splitlines() if line.startswith('"duration":')]
    assert durations == pytest.approx([d * 12 / 1000 for d in (83, 127, 211, 127)], abs=0.0001)
    s.animations[0].loop_start = 1
    with pytest.raises(SpriteExportError, match="partial loop"):
        run_sprite_export(s, SpriteExportOptions(format="godot"))


def test_installed_sprite_recipe_pixels_and_handoff(tmp_path):
    path = Path(__file__).resolve().parents[3] / "stimma-skills/stimma-sprites/recipes/sprite_assets.py"
    if not path.exists():
        pytest.skip("Sibling sprite stimpack not available")
    spec = importlib.util.spec_from_file_location("sprite_recipe_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from packages.recipes import Build, ResolvedInput, validate_params
    p = write_source(source(), tmp_path / "source.zip")
    recipe = module.build._stimma_recipe
    trees = []
    for n in range(2):
        out = tmp_path / str(n)
        out.mkdir()
        build = Build(recipe, {"source": ResolvedInput("source", p, "hash", "file")},
                      validate_params(recipe, {"godot": True}), out)
        module.build(build)
        trees.append({str(f.relative_to(out)): f.read_bytes() for f in out.rglob('*') if f.is_file()})
    assert trees[0] == trees[1]
    manifest = json.loads(trees[0]['asset.json'])
    atlas = json.loads(trees[0][manifest['atlas']])
    sheet = Image.open(io.BytesIO(trees[0]['atlas/courier.png']))
    for i, path in enumerate(manifest['animations'][0]['frames']):
        frame = Image.open(io.BytesIO(trees[0][path]))
        r = atlas['frames'][f'run_east/{i}']['frame']
        assert sheet.crop((r['x'], r['y'], r['x'] + r['w'], r['y'] + r['h'])).tobytes() == frame.tobytes()
    assert manifest['animations'][0]['content_bounds'] == [[0, 0, 16, 24]] * 3
    assert 'source' not in manifest
    assert 'index.html' not in trees[0]
