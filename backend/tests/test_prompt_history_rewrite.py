import hashlib
import io
import json
import os
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path

import piexif
import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from rich.console import Console

import prompt_history_rewrite
from metadata_embed import build_jpeg_exif
from prompt_history_rewrite import (
    ReplacementPlan,
    RewriteError,
    Rule,
    rewrite_database,
    rewrite_jpeg_bytes,
    rewrite_payload_report,
    rewrite_png_bytes,
    run_rewrite,
    scan_database,
)


def _quiet_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False)


def _make_png(path: Path, prompt: str) -> bytes:
    metadata = PngInfo()
    metadata.add_text("parameters", f"{prompt}\nSteps: 20")
    metadata.add_text("Comment", f"{prompt} compressed note", zip=True)
    metadata.add_itxt(
        "stimma",
        json.dumps({"parameters": {"prompt": prompt}}, separators=(",", ":")),
        zip=True,
    )
    exif = build_jpeg_exif(
        f"{prompt}\nSteps: 20",
        {"source": "stimma", "version": 1, "parameters": {"prompt": prompt}},
    )
    image = Image.new("RGB", (3, 2), (12, 34, 56))
    image.save(path, pnginfo=metadata, exif=exif)
    return path.read_bytes()


def _make_lineage_png(path: Path, source_hash: str) -> bytes:
    metadata = PngInfo()
    metadata.add_text(
        "stimma",
        json.dumps(
            {"parameters": {"prompt": "ordinary descendant", "image": f"sha256:{source_hash}"}},
            separators=(",", ":"),
        ),
    )
    Image.new("RGB", (2, 2), (77, 88, 99)).save(path, pnginfo=metadata)
    return path.read_bytes()


def _jpeg_scan_data(data: bytes) -> bytes:
    offset = 2
    while offset < len(data):
        assert data[offset] == 0xFF
        start = offset
        while data[offset] == 0xFF:
            offset += 1
        marker = data[offset]
        offset += 1
        if marker == 0xDA:
            return data[start:]
        if marker in {0x01, *range(0xD0, 0xDA)}:
            continue
        length = int.from_bytes(data[offset:offset + 2], "big")
        offset += length
    raise AssertionError("JPEG has no scan")


def test_replacement_plan_is_simultaneous_and_longest_first():
    plan = ReplacementPlan([Rule("cat", "dog"), Rule("catalog", "index")])

    assert plan.replace("catalog cat")[0] == "index dog"


def test_replacement_plan_rejects_reintroduced_search_term():
    with pytest.raises(RewriteError, match="replacement contains a search term"):
        ReplacementPlan([Rule("private", "still-private")])


def test_rewrite_database_updates_all_text_cells_and_vacuums(tmp_path):
    database = tmp_path / "state.db"
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, prompt TEXT, payload TEXT, raw BLOB)")
        connection.execute(
            "INSERT INTO events(prompt, payload, raw) VALUES (?, ?, ?)",
            ("private prompt", '{"lineage":"private ancestor"}', b"private binary"),
        )
    plan = ReplacementPlan([Rule("private", "clean")])

    dry_run = scan_database(database, plan)
    assert dry_run.occurrences == 3
    before_bytes = database.read_bytes()
    wal_path = Path(f"{database}-wal")
    if wal_path.exists():
        before_bytes += wal_path.read_bytes()
    assert b"private" in before_bytes

    result = rewrite_database(database, plan)

    assert result.occurrences == 3
    assert not Path(f"{database}-wal").exists()
    assert not Path(f"{database}-shm").exists()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        row = connection.execute("SELECT prompt, payload, raw FROM events").fetchone()
    assert row == ("clean prompt", '{"lineage":"clean ancestor"}', b"clean binary")
    assert scan_database(database, plan).occurrences == 0
    assert b"private" not in database.read_bytes()


def test_rewrite_database_merges_colliding_normalized_keywords(tmp_path):
    database = tmp_path / "stimma_v1.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE keywords (
                id INTEGER PRIMARY KEY,
                keyword_text TEXT NOT NULL UNIQUE
            );
            CREATE TABLE media_keywords (
                media_id INTEGER NOT NULL,
                keyword_id INTEGER NOT NULL,
                PRIMARY KEY (media_id, keyword_id)
            );
            INSERT INTO keywords VALUES (1, 'private portrait');
            INSERT INTO keywords VALUES (2, 'clean portrait');
            INSERT INTO keywords VALUES (3, 'very private');
            INSERT INTO media_keywords VALUES (10, 1);
            INSERT INTO media_keywords VALUES (10, 2);
            INSERT INTO media_keywords VALUES (11, 1);
            INSERT INTO media_keywords VALUES (12, 3);
            """
        )

    result = rewrite_database(
        database, ReplacementPlan([Rule("private", "clean")])
    )

    assert result.occurrences == 2
    with sqlite3.connect(database) as connection:
        keywords = connection.execute(
            "SELECT id, keyword_text FROM keywords ORDER BY id"
        ).fetchall()
        associations = connection.execute(
            "SELECT media_id, keyword_id FROM media_keywords ORDER BY media_id, keyword_id"
        ).fetchall()
    assert keywords == [(2, "clean portrait"), (3, "very clean")]
    assert associations == [(10, 2), (11, 2), (12, 3)]


def test_rewrite_database_merges_colliding_tags_and_markers(tmp_path):
    database = tmp_path / "stimma_v1.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE tags (id INTEGER PRIMARY KEY, tag_text TEXT NOT NULL UNIQUE);
            CREATE TABLE media_tags (
                media_id INTEGER NOT NULL, tag_id INTEGER NOT NULL,
                PRIMARY KEY (media_id, tag_id)
            );
            CREATE TABLE asset_tags (
                id INTEGER PRIMARY KEY, asset_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL, deleted_at DATETIME
            );
            CREATE UNIQUE INDEX asset_tags_live
                ON asset_tags(asset_id, tag_id) WHERE deleted_at IS NULL;
            CREATE TABLE markers (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            CREATE TABLE media_markers (
                media_id INTEGER NOT NULL, marker_id INTEGER NOT NULL,
                source TEXT, PRIMARY KEY (media_id, marker_id)
            );
            CREATE TABLE asset_markers (
                id INTEGER PRIMARY KEY, asset_id INTEGER NOT NULL,
                marker_id INTEGER NOT NULL, deleted_at DATETIME
            );
            CREATE UNIQUE INDEX asset_markers_live
                ON asset_markers(asset_id, marker_id) WHERE deleted_at IS NULL;

            INSERT INTO tags VALUES (1, 'private tag'), (2, 'clean tag');
            INSERT INTO media_tags VALUES (10, 1), (10, 2), (11, 1);
            INSERT INTO asset_tags VALUES (1, 20, 1, NULL), (2, 20, 2, NULL);
            INSERT INTO markers VALUES (1, 'private marker'), (2, 'clean marker');
            INSERT INTO media_markers VALUES (10, 1, 'manual'), (10, 2, 'manual');
            INSERT INTO asset_markers VALUES (1, 20, 1, NULL), (2, 20, 2, NULL);
            """
        )

    result = rewrite_database(
        database, ReplacementPlan([Rule("private", "clean")])
    )

    assert result.occurrences == 2
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT id, tag_text FROM tags").fetchall() == [
            (2, "clean tag")
        ]
        assert connection.execute(
            "SELECT media_id, tag_id FROM media_tags ORDER BY media_id"
        ).fetchall() == [(10, 2), (11, 2)]
        assert connection.execute("SELECT id, name FROM markers").fetchall() == [
            (2, "clean marker")
        ]
        assert connection.execute(
            "SELECT media_id, marker_id FROM media_markers"
        ).fetchall() == [(10, 2)]
        live_asset_tags = connection.execute(
            "SELECT id, tag_id FROM asset_tags WHERE deleted_at IS NULL"
        ).fetchall()
        live_asset_markers = connection.execute(
            "SELECT id, marker_id FROM asset_markers WHERE deleted_at IS NULL"
        ).fetchall()
    assert live_asset_tags == [(2, 2)]
    assert live_asset_markers == [(2, 2)]


def test_png_text_and_itxt_are_rewritten_without_touching_pixels(tmp_path):
    source = tmp_path / "source.png"
    original = _make_png(source, "private subject")
    plan = ReplacementPlan([Rule("private", "clean")])

    rewritten, count = rewrite_png_bytes(original, plan)
    destination = tmp_path / "rewritten.png"
    destination.write_bytes(rewritten)

    assert count == 5
    with Image.open(source) as before, Image.open(destination) as after:
        assert list(before.getdata()) == list(after.getdata())
        assert after.info["parameters"] == "clean subject\nSteps: 20"
        assert after.info["Comment"] == "clean subject compressed note"
        assert json.loads(after.info["stimma"])["parameters"]["prompt"] == "clean subject"
        exif_dict = piexif.load(after.info["exif"])
        combined_exif = (
            exif_dict["Exif"][piexif.ExifIFD.UserComment]
            + exif_dict["Exif"][piexif.ExifIFD.MakerNote]
        )
        assert b"private" not in combined_exif
        assert combined_exif.count(b"clean subject") == 2


def test_png_trailing_bytes_are_preserved(tmp_path):
    source = tmp_path / "source.png"
    trailing = b"nonstandard-encoder-trailer\x00\xff"
    original = _make_png(source, "private subject") + trailing

    rewritten, count = rewrite_png_bytes(
        original, ReplacementPlan([Rule("private", "clean")])
    )

    assert count == 5
    assert rewritten.endswith(trailing)
    destination = tmp_path / "rewritten.png"
    destination.write_bytes(rewritten)
    with Image.open(destination) as image:
        assert image.info["parameters"].startswith("clean subject")


def test_rewrite_payload_preserves_file_times_and_inode(tmp_path):
    source = tmp_path / "source.png"
    _make_png(source, "private subject")
    expected_times_ns = (1_700_000_000_123_456_789, 1_700_000_100_987_654_321)
    os.utime(source, ns=expected_times_ns)
    before = source.stat()

    report = rewrite_payload_report(
        source, ReplacementPlan([Rule("private", "clean")])
    )

    after = source.stat()
    assert report.occurrences == 5
    assert after.st_ino == before.st_ino
    assert after.st_atime_ns == before.st_atime_ns
    assert after.st_mtime_ns == before.st_mtime_ns
    if hasattr(before, "st_birthtime"):
        assert after.st_birthtime == before.st_birthtime
    with Image.open(source) as image:
        assert image.info["parameters"].startswith("clean subject")


def test_jpeg_exif_is_rewritten_without_reencoding_scan_data(tmp_path):
    source = tmp_path / "source.jpg"
    sidecar = {
        "source": "stimma",
        "version": 1,
        "parameters": {"prompt": "private subject"},
    }
    exif = build_jpeg_exif("private subject\nSteps: 20", sidecar)
    Image.new("RGB", (4, 3), (90, 80, 70)).save(source, quality=91, exif=exif)
    original = source.read_bytes()

    rewritten, count = rewrite_jpeg_bytes(
        original, ReplacementPlan([Rule("private", "clean")])
    )

    assert count == 2
    assert _jpeg_scan_data(rewritten) == _jpeg_scan_data(original)
    exif_dict = piexif.load(rewritten)
    user_comment = exif_dict["Exif"][piexif.ExifIFD.UserComment]
    maker_note = exif_dict["Exif"][piexif.ExifIFD.MakerNote]
    assert b"clean subject" in user_comment
    assert b"clean subject" in maker_note
    assert b"private" not in user_comment + maker_note


def test_apply_rewrites_profile_db_flow_text_and_managed_png_identity(tmp_path):
    data_dir = tmp_path / "sandbox"
    profile_dir = data_dir / "profile-one"
    profile_dir.mkdir(parents=True)
    database = profile_dir / "stimma_v1.db"

    staging_png = tmp_path / "payload.png"
    original_bytes = _make_png(staging_png, "private subject")
    original_hash = hashlib.sha256(original_bytes).hexdigest()
    original_key = f"sha256/{original_hash[:2]}/{original_hash[2:4]}/{original_hash}"
    object_path = profile_dir / "objects" / original_key
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(original_bytes)
    compatibility_path = profile_dir / "objects" / "media" / "1" / "payload.png"
    compatibility_path.parent.mkdir(parents=True)
    os.link(object_path, compatibility_path)

    descendant_staging = tmp_path / "descendant.png"
    descendant_bytes = _make_lineage_png(descendant_staging, original_hash)
    descendant_hash = hashlib.sha256(descendant_bytes).hexdigest()
    descendant_key = (
        f"sha256/{descendant_hash[:2]}/{descendant_hash[2:4]}/{descendant_hash}"
    )
    descendant_object = profile_dir / "objects" / descendant_key
    descendant_object.parent.mkdir(parents=True, exist_ok=True)
    descendant_object.write_bytes(descendant_bytes)
    descendant_compatibility = profile_dir / "objects" / "media" / "2" / "descendant.png"
    descendant_compatibility.parent.mkdir(parents=True)
    os.link(descendant_object, descendant_compatibility)

    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE storage_objects (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                object_key TEXT UNIQUE,
                external_path TEXT,
                expected_hash TEXT NOT NULL,
                file_size INTEGER,
                verified_at DATETIME
            );
            CREATE TABLE media_items (
                id INTEGER PRIMARY KEY,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                raw_metadata TEXT,
                generation_metadata TEXT,
                storage_object_id INTEGER
            );
            """
        )
        connection.execute(
            "INSERT INTO storage_objects VALUES (1, 'managed', ?, NULL, ?, ?, NULL)",
            (original_key, original_hash, len(original_bytes)),
        )
        connection.execute(
            "INSERT INTO media_items VALUES (1, ?, ?, ?, ?, ?, 1)",
            (
                str(compatibility_path),
                original_hash,
                len(original_bytes),
                "private raw prompt",
                '{"prompt":"private subject","lineage":["private ancestor"]}',
            ),
        )
        connection.execute(
            "INSERT INTO storage_objects VALUES (2, 'managed', ?, NULL, ?, ?, NULL)",
            (descendant_key, descendant_hash, len(descendant_bytes)),
        )
        connection.execute(
            "INSERT INTO media_items VALUES (2, ?, ?, ?, NULL, ?, 2)",
            (
                str(descendant_compatibility),
                descendant_hash,
                len(descendant_bytes),
                json.dumps({"source_fingerprint": f"sha256:{original_hash}"}),
            ),
        )

    flow_program = profile_dir / "flows" / "7" / "program.py"
    flow_program.parent.mkdir(parents=True)
    flow_program.write_text('prompt = "private flow prompt"\n', encoding="utf-8")

    plan = ReplacementPlan([Rule("private", "clean")])
    dry_run = run_rewrite(data_dir, plan, apply=False, console=_quiet_console())

    assert dry_run.occurrences == 9
    assert object_path.exists()
    assert "private" in flow_program.read_text()
    expected_image_times_ns = (
        1_700_000_000_123_456_789,
        1_700_000_100_987_654_321,
    )
    os.utime(object_path, ns=expected_image_times_ns)
    original_object_stat = object_path.stat()

    result = run_rewrite(data_dir, plan, apply=True, console=_quiet_console())

    assert result.occurrences == 9
    with sqlite3.connect(database) as connection:
        media = connection.execute(
            "SELECT file_hash, file_size, raw_metadata, generation_metadata "
            "FROM media_items WHERE id=1"
        ).fetchone()
        storage = connection.execute(
            "SELECT object_key, expected_hash, file_size FROM storage_objects WHERE id=1"
        ).fetchone()
        descendant_media = connection.execute(
            "SELECT file_hash, generation_metadata FROM media_items WHERE id=2"
        ).fetchone()
        descendant_storage = connection.execute(
            "SELECT object_key, expected_hash FROM storage_objects WHERE id=2"
        ).fetchone()
    assert "private" not in media[2] + media[3]
    assert media[0] == storage[1]
    assert media[1] == storage[2]
    assert storage[0].endswith(media[0])
    rewritten_object = profile_dir / "objects" / storage[0]
    assert rewritten_object.exists()
    assert not object_path.exists()
    assert compatibility_path.samefile(rewritten_object)
    rewritten_object_stat = rewritten_object.stat()
    assert rewritten_object_stat.st_ino == original_object_stat.st_ino
    assert rewritten_object_stat.st_atime_ns == original_object_stat.st_atime_ns
    assert rewritten_object_stat.st_mtime_ns == original_object_stat.st_mtime_ns
    if hasattr(original_object_stat, "st_birthtime"):
        assert rewritten_object_stat.st_birthtime == original_object_stat.st_birthtime
    assert hashlib.sha256(rewritten_object.read_bytes()).hexdigest() == media[0]
    with Image.open(rewritten_object) as image:
        assert "private" not in image.info["parameters"]
        assert "clean" in image.info["parameters"]
    assert descendant_media[0] != descendant_hash
    assert descendant_media[0] == descendant_storage[1]
    assert original_hash not in descendant_media[1]
    assert media[0] in descendant_media[1]
    rewritten_descendant = profile_dir / "objects" / descendant_storage[0]
    assert rewritten_descendant.exists()
    assert not descendant_object.exists()
    assert descendant_compatibility.samefile(rewritten_descendant)
    with Image.open(rewritten_descendant) as image:
        assert original_hash not in image.info["stimma"]
        assert media[0] in image.info["stimma"]
    assert flow_program.read_text() == 'prompt = "clean flow prompt"\n'
    assert run_rewrite(data_dir, plan, apply=False, console=_quiet_console()).occurrences == 0


def test_corrupt_png_is_reported_and_does_not_abort_other_media(tmp_path):
    data_dir = tmp_path / "sandbox"
    profile_dir = data_dir / "profile"
    payload_dir = profile_dir / "payloads"
    payload_dir.mkdir(parents=True)
    database = profile_dir / "stimma_v1.db"

    valid = payload_dir / "valid.png"
    valid_bytes = _make_png(valid, "private subject")
    corrupt = payload_dir / "corrupt.png"
    corrupt_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x20tEXtbroken"
    corrupt.write_bytes(corrupt_bytes)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE media_items ("
            "id INTEGER PRIMARY KEY, file_path TEXT, file_hash TEXT, file_size INTEGER)"
        )
        connection.executemany(
            "INSERT INTO media_items VALUES (?, ?, ?, ?)",
            [
                (1, str(valid), hashlib.sha256(valid_bytes).hexdigest(), len(valid_bytes)),
                (2, str(corrupt), hashlib.sha256(corrupt_bytes).hexdigest(), len(corrupt_bytes)),
            ],
        )

    plan = ReplacementPlan([Rule("private", "clean")])
    dry_run = run_rewrite(
        data_dir, plan, apply=False, workers=4, console=_quiet_console()
    )

    assert dry_run.occurrences == 5
    assert len(dry_run.file_report.errors) == 1
    assert "corrupt.png" in dry_run.file_report.errors[0]

    applied = run_rewrite(
        data_dir, plan, apply=True, workers=4, console=_quiet_console()
    )

    assert applied.occurrences == 5
    assert len(applied.file_report.errors) == 1
    assert corrupt.read_bytes() == corrupt_bytes
    with Image.open(valid) as image:
        assert image.info["parameters"].startswith("clean subject")


def test_read_only_scan_uses_multiple_workers(tmp_path, monkeypatch):
    data_dir = tmp_path / "sandbox"
    profile_dir = data_dir / "profile"
    profile_dir.mkdir(parents=True)
    with sqlite3.connect(profile_dir / "stimma_v1.db") as connection:
        connection.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    for index in range(16):
        (profile_dir / f"note-{index}.txt").write_text(
            "private prompt", encoding="utf-8"
        )

    original = prompt_history_rewrite.rewrite_payload_bytes
    lock = threading.Lock()
    active = 0
    max_active = 0

    def tracked_rewrite(data, path, plan):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.02)
            return original(data, path, plan)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(
        prompt_history_rewrite, "rewrite_payload_bytes", tracked_rewrite
    )

    result = run_rewrite(
        data_dir,
        ReplacementPlan([Rule("private", "clean")]),
        apply=False,
        workers=4,
        console=_quiet_console(),
    )

    assert result.occurrences == 16
    assert max_active > 1


def test_lineage_graph_propagates_deep_chain_without_repeated_global_scans(
    tmp_path, monkeypatch
):
    data_dir = tmp_path / "sandbox"
    profile_dir = data_dir / "profile"
    payload_dir = profile_dir / "payloads"
    payload_dir.mkdir(parents=True)
    database = profile_dir / "stimma_v1.db"

    parent = payload_dir / "parent.png"
    parent_bytes = _make_png(parent, "private subject")
    parent_hash = hashlib.sha256(parent_bytes).hexdigest()
    child = payload_dir / "child.png"
    child_bytes = _make_lineage_png(child, parent_hash)
    child_hash = hashlib.sha256(child_bytes).hexdigest()
    grandchild = payload_dir / "grandchild.png"
    grandchild_bytes = _make_lineage_png(grandchild, child_hash)
    grandchild_hash = hashlib.sha256(grandchild_bytes).hexdigest()

    unrelated: list[Path] = []
    for index in range(12):
        path = payload_dir / f"unrelated-{index}.png"
        Image.new("RGB", (2, 2), (index, index, index)).save(path)
        unrelated.append(path)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE media_items ("
            "id INTEGER PRIMARY KEY, file_path TEXT, file_hash TEXT, "
            "file_size INTEGER, generation_metadata TEXT)"
        )
        connection.executemany(
            "INSERT INTO media_items VALUES (?, ?, ?, ?, ?)",
            [
                (
                    1,
                    str(parent),
                    parent_hash,
                    len(parent_bytes),
                    '{"prompt":"private subject"}',
                ),
                (
                    2,
                    str(child),
                    child_hash,
                    len(child_bytes),
                    json.dumps({"source_fingerprint": f"sha256:{parent_hash}"}),
                ),
                (
                    3,
                    str(grandchild),
                    grandchild_hash,
                    len(grandchild_bytes),
                    json.dumps({"source_fingerprint": f"sha256:{child_hash}"}),
                ),
                *[
                    (
                        index + 10,
                        str(path),
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                        path.stat().st_size,
                        None,
                    )
                    for index, path in enumerate(unrelated)
                ],
            ],
        )

    scan_counts: Counter[Path] = Counter()
    original_scan = prompt_history_rewrite.scan_payload_report

    def tracked_scan(path, plan):
        scan_counts[path] += 1
        return original_scan(path, plan)

    monkeypatch.setattr(prompt_history_rewrite, "scan_payload_report", tracked_scan)
    output = io.StringIO()
    result = run_rewrite(
        data_dir,
        ReplacementPlan([Rule("private", "clean")]),
        apply=True,
        workers=4,
        console=Console(file=output, force_terminal=False),
    )

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT file_hash, generation_metadata FROM media_items "
            "WHERE id IN (1, 2, 3) ORDER BY id"
        ).fetchall()
    final_parent_hash, final_child_hash, final_grandchild_hash = (
        row[0] for row in rows
    )
    assert final_parent_hash != parent_hash
    assert final_child_hash != child_hash
    assert final_grandchild_hash != grandchild_hash
    assert parent_hash not in rows[1][1]
    assert final_parent_hash in rows[1][1]
    assert child_hash not in rows[2][1]
    assert final_child_hash in rows[2][1]
    assert result.hash_changes[parent_hash] == final_parent_hash
    assert result.hash_changes[child_hash] == final_child_hash
    assert result.hash_changes[grandchild_hash] == final_grandchild_hash
    assert all(scan_counts[path] == 2 for path in unrelated)
    transcript = output.getvalue()
    assert "Inventorying databases, media, sidecars, and text surfaces" in transcript
    assert "Preflight: scanning every readable surface once" in transcript
    assert "Applying requested replacements" in transcript
    assert "Lineage graph ready: 2 affected media" in transcript
    assert "Vacuuming 1 databases" in transcript
    assert "Final verification: one exhaustive parallel scan" in transcript
    assert "Final verification complete: zero readable matches remain" in transcript
