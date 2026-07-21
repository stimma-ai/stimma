"""Timeline op core + project store tests (no app/db fixtures needed)."""

import json

import pytest

from timeline.ops import TimelineOpError, apply_op, entry_duration
from timeline.serializer import serialize_snapshot, snapshot_duration
from timeline.store import TimelineProject, TimelineStoreError


@pytest.fixture
def project(tmp_path):
    return TimelineProject(tmp_path / "proj")


def create(project, **kwargs):
    args = {"title": "Test", "fps": 30, "width": 1280, "height": 720, **kwargs}
    return project.append_batch([("create_timeline", args)], author="user")


def video_entries(state):
    return next(t for t in state["tracks"] if t["kind"] == "video")["entries"]


# --- op core -----------------------------------------------------------

def test_create_must_be_first():
    state = apply_op(None, "create_timeline", {"title": "x"})
    with pytest.raises(TimelineOpError):
        apply_op(state, "create_timeline", {"title": "y"})
    with pytest.raises(TimelineOpError):
        apply_op(None, "add_slot", {"id": "a", "duration": 1, "brief": ""})


def test_add_clip_requires_timing():
    state = apply_op(None, "create_timeline", {})
    with pytest.raises(TimelineOpError):
        apply_op(state, "add_clip", {"id": "a", "media_id": 1})
    with pytest.raises(TimelineOpError):
        apply_op(state, "add_clip", {"id": "a", "media_id": 1, "in": 5, "out": 2})


def test_entry_durations():
    assert entry_duration({"kind": "slot", "duration": 4.0}) == 4.0
    assert entry_duration({"kind": "clip", "in": 1.0, "out": 3.5}) == 2.5
    assert entry_duration({"kind": "clip", "in": 0.0, "duration": 2.0}) == 2.0


# --- store: append/undo/redo --------------------------------------------

def test_append_undo_redo_batch(project):
    create(project)
    result = project.append_batch(
        [
            ("add_slot", {"track": "video", "duration": 5, "brief": "opening"}),
            ("add_slot", {"track": "video", "duration": 3, "brief": "b-roll"}),
        ],
        author="agent:run1",
        label="Skeleton",
    )
    assert len(video_entries(result["state"])) == 2
    ids = [e["id"] for e in video_entries(result["state"])]
    assert all(len(i) == 26 for i in ids)

    # Batch undoes as one unit
    result = project.undo()
    assert video_entries(result["state"]) == []
    assert result["can_redo"]

    result = project.redo()
    assert [e["id"] for e in video_entries(result["state"])] == ids


def test_cannot_undo_past_create(project):
    create(project)
    with pytest.raises(TimelineStoreError):
        project.undo()


def test_linear_undo_marks_dead(project):
    create(project)
    project.append_batch([("add_slot", {"duration": 5, "brief": "a"})], author="user")
    project.undo()
    project.append_batch([("add_slot", {"duration": 2, "brief": "b"})], author="user")
    state = project.state()
    assert [e["brief"] for e in video_entries(state)] == ["b"]
    # Redo branch is gone but rows remain, marked dead
    with pytest.raises(TimelineStoreError):
        project.redo()
    assert any(row["dead"] for row in project.history())


def test_batch_atomicity_on_mid_batch_failure(project):
    create(project)
    with pytest.raises(TimelineOpError):
        project.append_batch(
            [
                ("add_slot", {"duration": 5, "brief": "ok"}),
                ("trim_clip", {"entry_id": "missing", "out": 1}),
            ],
            author="user",
        )
    assert video_entries(project.state()) == []
    assert project.status()["can_undo"] is False


def test_persistence_across_reopen(tmp_path):
    first = TimelineProject(tmp_path / "p")
    create(first)
    first.append_batch([("add_slot", {"duration": 5, "brief": "a"})], author="user")
    first.append_batch([("add_slot", {"duration": 2, "brief": "b"})], author="user")
    first.undo()

    reopened = TimelineProject(tmp_path / "p")
    state = reopened.state()
    assert [e["brief"] for e in video_entries(state)] == ["a"]
    assert reopened.status()["can_redo"]
    reopened.redo()
    assert [e["brief"] for e in video_entries(reopened.state())] == ["a", "b"]


def test_fill_move_trim_remove_roundtrip(project):
    create(project)
    result = project.append_batch(
        [
            ("add_slot", {"duration": 5, "brief": "hole"}),
            ("add_clip", {"media_id": 7, "in": 0, "out": 4}),
        ],
        author="user",
    )
    slot_id, clip_id = [e["id"] for e in video_entries(result["state"])]

    result = project.append_batch(
        [("fill_slot", {"slot_id": slot_id, "media_id": 9, "in": 0, "out": 5})],
        author="agent:run2",
        label="Fill hole",
    )
    filled = video_entries(result["state"])[0]
    assert filled["kind"] == "clip" and filled["id"] == slot_id
    assert filled["label"] == "hole"  # brief carries over as label

    result = project.undo()
    assert video_entries(result["state"])[0]["kind"] == "slot"
    result = project.redo()

    result = project.append_batch(
        [("move_entry", {"entry_id": clip_id, "position": 0})], author="user"
    )
    assert [e["id"] for e in video_entries(result["state"])] == [clip_id, slot_id]
    result = project.undo()
    assert [e["id"] for e in video_entries(result["state"])] == [slot_id, clip_id]

    project.append_batch(
        [("trim_clip", {"entry_id": clip_id, "in": 1.0, "out": 3.0})], author="user"
    )
    project.append_batch([("remove_entry", {"entry_id": clip_id})], author="user")
    assert len(video_entries(project.state())) == 1
    result = project.undo()
    restored = video_entries(result["state"])[1]
    assert restored["in"] == 1.0 and restored["out"] == 3.0


def test_trim_slot_duration(project):
    create(project)
    result = project.append_batch(
        [("add_slot", {"duration": 5, "brief": "hole"})], author="user"
    )
    slot_id = video_entries(result["state"])[0]["id"]
    result = project.append_batch(
        [("trim_clip", {"entry_id": slot_id, "duration": 2.5})], author="user"
    )
    assert video_entries(result["state"])[0]["duration"] == 2.5
    with pytest.raises(TimelineOpError):
        project.append_batch(
            [("trim_clip", {"entry_id": slot_id, "in": 1})], author="user"
        )
    result = project.undo()
    assert video_entries(result["state"])[0]["duration"] == 5


def test_internal_ops_rejected(project):
    create(project)
    with pytest.raises(TimelineOpError):
        project.append_batch(
            [("_replace_entry", {"entry_id": "x", "entry": {}})], author="user"
        )


def test_audio_silence_slot(project):
    create(project)
    result = project.append_batch(
        [("add_slot", {"track": "audio", "duration": 10, "brief": "", "silence": True})],
        author="user",
    )
    audio = next(t for t in result["state"]["tracks"] if t["kind"] == "audio")
    assert audio["entries"][0]["silence"] is True


# --- serializer ----------------------------------------------------------

def test_serializer_deterministic_and_canonical(project):
    create(project)
    result = project.append_batch(
        [
            ("add_clip", {"media_id": 1, "in": 0, "out": 2, "label": "shot"}),
            ("add_slot", {"duration": 3, "brief": "hole", "notes": "n"}),
            ("add_slot", {"track": "audio", "duration": 5, "silence": True}),
        ],
        author="user",
    )
    state = result["state"]
    paths = {1: "../media/a.mp4"}
    one = json.dumps(serialize_snapshot(state, paths), indent=2)
    two = json.dumps(serialize_snapshot(project.state(), paths), indent=2)
    assert one == two

    snapshot = serialize_snapshot(state, paths)
    assert snapshot["format"] == "stimmatimeline"
    assert snapshot["version"] == 1
    assert list(snapshot.keys()) == ["format", "version", "title", "fps", "width", "height", "tracks"]
    clip = snapshot["tracks"][0]["entries"][0]
    assert clip["media"] == {"path": "../media/a.mp4"}
    assert "media_id" not in json.dumps(snapshot)
    assert snapshot_duration(state) == 5.0


def test_serializer_requires_paths(project):
    create(project)
    result = project.append_batch(
        [("add_clip", {"media_id": 42, "in": 0, "out": 2})], author="user"
    )
    with pytest.raises(TimelineOpError):
        serialize_snapshot(result["state"], {})
