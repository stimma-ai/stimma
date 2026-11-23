"""Source tags travel with image data through Pillow and NumPy (agent/v2/source_tags)."""
import json

import numpy as real_np
import pytest
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from agent.v2.source_tags import sandbox_numpy, sources_of, tag, tracking

np = sandbox_numpy()


@pytest.fixture
def pair(tmp_path):
    Image.new("RGB", (16, 16), "red").save(tmp_path / "a.png")
    Image.new("RGB", (16, 16), "blue").save(tmp_path / "b.png")
    with tracking(tmp_path):
        yield tag(Image.open(tmp_path / "a.png"), ("A",)), tag(Image.open(tmp_path / "b.png"), ("B",))


def _in_place(image, change):
    change(image)
    return image


def test_one_image_operations_keep_the_tag(pair):
    a, _ = pair
    made = {
        "crop": a.crop((0, 0, 4, 4)), "convert": a.convert("RGBA"), "resize": a.resize((4, 4)), "copy": a.copy(),
        "rotate": a.rotate(30, expand=True), "transpose": a.transpose(Image.FLIP_LEFT_RIGHT),
        "transform": a.transform((8, 8), Image.AFFINE, (1, 0, 0, 0, 1, 0)),
        "filter": a.filter(ImageFilter.GaussianBlur(1)), "point": a.point(lambda v: v // 2), "band": a.split()[0],
        "expand": ImageOps.expand(a, 2), "pad": ImageOps.pad(a, (32, 20)), "fit": ImageOps.fit(a, (8, 8)),
        "grayscale": ImageOps.grayscale(a), "invert": ImageOps.invert(a), "autocontrast": ImageOps.autocontrast(a),
        "brightness": ImageEnhance.Brightness(a).enhance(1.2), "contrast": ImageEnhance.Contrast(a).enhance(1.2),
        "quantize": a.quantize(8), "thumbnail": _in_place(a.copy(), lambda im: im.thumbnail((8, 8))),
        "draw": _in_place(a.copy(), lambda im: ImageDraw.Draw(im).line((0, 0, 5, 5))),
    }
    assert {name: sources_of(image) for name, image in made.items()} == dict.fromkeys(made, ("A",))


def test_operations_over_several_images_carry_all_their_tags(pair):
    a, b = pair
    aa, bb = a.convert("RGBA"), b.convert("RGBA")
    made = {
        "paste": _in_place(a.copy(), lambda im: im.paste(b, (4, 4))),
        "paste on blank": _in_place(Image.new("RGB", (40, 16)), lambda im: (im.paste(a, (0, 0)), im.paste(b, (20, 0)))),
        "alpha_composite": Image.alpha_composite(aa, bb),
        "alpha_composite in place": _in_place(aa.copy(), lambda im: im.alpha_composite(bb)),
        "blend": Image.blend(a, b, 0.5), "composite": Image.composite(a, b, Image.new("L", (16, 16), 128)),
        "merge": Image.merge("RGB", (a.split()[0], b.split()[1], a.split()[2])),
        "chops": ImageChops.multiply(a, b), "putalpha": _in_place(aa.copy(), lambda im: im.putalpha(b.convert("L"))),
    }
    assert {name: sorted(sources_of(image)) for name, image in made.items()} == dict.fromkeys(made, ["A", "B"])
    # Order is the order the data arrived in: what was there, then what was added.
    assert sources_of(made["paste"]) == ("A", "B")


def test_arrays_made_from_images_carry_the_tag_through_numpy(pair):
    a, b = pair
    arr, brr = np.asarray(a), np.array(b)
    mask = arr[..., 0] > 128
    one = {
        "slice": arr[2:6], "flip": arr[:, ::-1].copy(), "scale": arr * 0.5, "astype": (arr * 0.5).astype(np.uint8),
        "asarray": np.asarray(arr, dtype=float), "pad": np.pad(arr, ((1, 1), (1, 1), (0, 0))), "rot90": np.rot90(arr),
        "dstack with own mask": np.dstack([arr, mask.astype(np.uint8) * 255]),
    }
    assert {name: sources_of(v) for name, v in one.items()} == dict.fromkeys(one, ("A",))
    both = {
        "add": arr + brr, "where": np.where(mask[..., None], arr, brr), "concatenate": np.concatenate([arr, brr], axis=1),
        "stack": np.stack([arr, brr]), "clip": np.clip(arr.astype(int) + brr, 0, 255),
        "in place": _in_place(arr.copy(), lambda x: x.__iadd__(brr)),
        "assigned into": _in_place(arr.copy(), lambda x: x.__setitem__(slice(0, 4), brr[0:4])),
    }
    assert {name: sorted(sources_of(v)) for name, v in both.items()} == dict.fromkeys(both, ["A", "B"])
    assert sources_of(Image.fromarray((arr * 0.5).astype(np.uint8))) == ("A",)
    # A mask cut from one image steering math on another counts as both.
    assert sorted(sources_of(np.add(arr, 1, where=brr > 0))) == ["A", "B"]
    # Writing through a view changes the array it was cut from.
    whole = arr.copy()
    tile = whole[:, :8]
    tile[:] = brr[:, :8]
    assert sorted(sources_of(whole)) == ["A", "B"]
    assert sources_of(np.array(object=a)) == sources_of(np.asarray(a=a)) == ("A",)


def test_what_is_not_pixels_carries_no_tag(pair):
    a, _ = pair
    arr = np.asarray(a)
    assert sources_of(np.zeros_like(arr)) == ()          # a blank canvas the same shape
    assert sources_of(arr.mean()) == ()                  # a measurement
    assert sources_of(Image.new("RGB", a.size)) == ()    # sized like it, made of nothing


def test_a_tagged_array_reads_and_saves_as_a_plain_array(pair, tmp_path):
    arr = np.asarray(pair[0])
    assert isinstance(arr, real_np.ndarray)
    assert repr(arr[0, :1]) == repr(real_np.asarray(pair[0])[0, :1])
    real_np.save(tmp_path / "a.npy", arr)
    assert type(real_np.load(tmp_path / "a.npy")) is real_np.ndarray


def test_saving_records_the_tag_for_the_written_file(tmp_path):
    from agent.v2.file_sources import file_digest

    Image.new("RGB", (16, 16), "red").save(tmp_path / "a.png")
    with tracking(tmp_path) as run:
        assert not run.opened
        Image.new("RGB", (4, 4)).save(tmp_path / "blank.png")
        Image.open(tmp_path / "a.png").crop((0, 0, 8, 8)).save(tmp_path / "out.png")
        assert run.opened
    ledger = json.loads((tmp_path / ".stimma-sources.json").read_text())["files"]
    # The opened file is known by its content, resolved to library media on save.
    assert ledger == {file_digest(tmp_path / "out.png"): {"sources": [file_digest(tmp_path / "a.png")]}}


def test_outside_agent_code_nothing_is_tagged_or_recorded(tmp_path):
    Image.new("RGB", (16, 16), "red").save(tmp_path / "a.png")
    image = Image.open(tmp_path / "a.png")
    assert sources_of(image) == ()
    image.crop((0, 0, 8, 8)).save(tmp_path / "out.png")
    assert not (tmp_path / ".stimma-sources.json").exists()
