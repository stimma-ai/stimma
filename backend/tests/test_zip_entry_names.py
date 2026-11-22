"""ZIP downloads and exports never write two entries under one name."""

from routes.media_files import _unique_zip_name


def test_suffix_skips_names_already_emitted():
    used: dict[str, int] = {}
    names = [
        _unique_zip_name(n, used)
        for n in ["photo.png", "photo_1.png", "photo.png", "photo.png", "photo_1.png"]
    ]
    assert len(set(names)) == len(names)
    assert names[:4] == ["photo.png", "photo_1.png", "photo_2.png", "photo_3.png"]
