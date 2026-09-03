from core.slowtrace import _skip_detailed_logging


def test_database_scoped_media_routes_skip_detailed_request_logging():
    assert _skip_detailed_logging("/api/db/guid/thumbnail/hash")
    assert _skip_detailed_logging("/api/db/guid/media/42/thumbnail")
    assert _skip_detailed_logging("/api/db/guid/media/by-hash/hash/file")
    assert _skip_detailed_logging("/api/db/guid/media/by-hash/hash/mse-loop/segment")


def test_ordinary_api_routes_keep_detailed_request_logging():
    assert not _skip_detailed_logging("/api/assets")
    assert not _skip_detailed_logging("/api/boards/42")
