"""Auto-markers match a configured folder, not sibling folders sharing its prefix."""

import os

from ingestion import _path_in_folder


def test_sibling_with_shared_prefix_is_not_inside_folder():
    assert _path_in_folder("/photos/a.png", "/photos")
    assert _path_in_folder("/photos/a.png", "/photos/")
    assert not _path_in_folder("/photos-old/a.png", "/photos")
    assert not _path_in_folder("/photosbackup.png", "/photos")
    if os.sep == "\\":
        assert _path_in_folder("C:\\photos\\a.png", "C:\\photos")
    else:
        # A backslash is an ordinary filename character on POSIX.
        assert not _path_in_folder("/photos\\archive/a.png", "/photos")
