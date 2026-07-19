import hashlib
import io
import json
import os
import sqlite3
from pathlib import Path

import piexif
import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from rich.console import Console

from metadata_embed import build_jpeg_exif
from prompt_history_rewrite import (
    ReplacementPlan,
    RewriteError,
    Rule,
    rewrite_database,
    rewrite_jpeg_bytes,
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
