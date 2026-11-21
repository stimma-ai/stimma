"""EXIF prompt extraction: camera boilerplate and Windows XPComment."""

from PIL import Image

from exif_extractor import extract_prompt_from_exif


def _jpeg_with(tmp_path, **tags):
    img = Image.new("RGB", (8, 8))
    exif = Image.Exif()
    for tag, value in tags.items():
        exif[{"ImageDescription": 0x010E, "XPComment": 0x9C9C}[tag]] = value
    path = tmp_path / "photo.jpg"
    img.save(path, exif=exif.tobytes())
    return path


def test_camera_boilerplate_is_not_a_prompt(tmp_path):
    path = _jpeg_with(tmp_path, ImageDescription="OLYMPUS DIGITAL CAMERA         ")
    assert extract_prompt_from_exif(path) == (None, None)


def test_xpcomment_decodes_utf16_and_beats_boilerplate(tmp_path):
    prompt = "a lighthouse at dusk, oil painting"
    path = _jpeg_with(
        tmp_path,
        ImageDescription="OLYMPUS DIGITAL CAMERA",
        XPComment=(prompt + "\x00").encode("utf-16-le"),
    )
    raw, parsed = extract_prompt_from_exif(path)
    assert raw == prompt
    assert parsed == prompt


def test_short_xpcomment_is_kept(tmp_path):
    path = _jpeg_with(tmp_path, XPComment="red fox\x00".encode("utf-16-le"))
    assert extract_prompt_from_exif(path)[0] == "red fox"
