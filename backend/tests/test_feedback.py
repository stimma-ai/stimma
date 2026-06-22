"""
Feedback / thumbs / crash-report client tests (WS-F).

Covers:
- log tail + secret scrubber
- conversation package builder (manifest shape, media remap, size cap)
- crash report writer + pending flow + batch semantics + consent gating
- crash rate limiting (write-time dedupe, pending cap, send throttle,
  429 backoff, storm behavior)
- distribution gating (dev build -> thumbs/crash paths inert)
- submission flow against a mocked cloud feedback API
"""
import asyncio
import io
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest


# =====================================================================
# Log tail + scrubber
# =====================================================================


class TestLogTail:
    def test_tail_reads_last_n_lines(self, tmp_path):
        from log_tail import tail_log_lines
        log_dir = tmp_path / "Logs"
        log_dir.mkdir()
        (log_dir / "Stimma_log.00.txt").write_text(
            "\n".join(f"line {i}" for i in range(300))
        )
        lines = tail_log_lines(200, log_dir=log_dir)
        assert len(lines) == 200
        assert lines[0] == "line 100"
        assert lines[-1] == "line 299"

    def test_tail_spills_into_previous_file(self, tmp_path):
        from log_tail import tail_log_lines
        log_dir = tmp_path / "Logs"
        log_dir.mkdir()
        (log_dir / "Stimma_log.01.txt").write_text(
            "\n".join(f"old {i}" for i in range(500))
        )
        (log_dir / "Stimma_log.00.txt").write_text(
            "\n".join(f"new {i}" for i in range(50))
        )
        lines = tail_log_lines(200, log_dir=log_dir)
        assert len(lines) == 200
        # Oldest first: 150 lines from .01, then all 50 from .00
        assert lines[0] == "old 350"
        assert lines[149] == "old 499"
        assert lines[150] == "new 0"
        assert lines[-1] == "new 49"

    def test_tail_missing_dir_returns_empty(self, tmp_path):
        from log_tail import tail_log_lines
        assert tail_log_lines(200, log_dir=tmp_path / "nope") == []

    def test_scrubs_authorization_header(self):
        from log_tail import scrub_secrets
        out = scrub_secrets("sending Authorization: Bearer sk-abc123XYZsecret to api")
        assert "sk-abc123XYZsecret" not in out
        assert "Authorization" in out
        assert "[redacted]" in out

    def test_scrubs_api_key_variants(self):
        from log_tail import scrub_secrets
        for text in (
            "api_key=sk-deadbeef1234",
            'api-key: "sk-deadbeef1234"',
            "APIKEY=sk-deadbeef1234",
        ):
            out = scrub_secrets(text)
            assert "sk-deadbeef1234" not in out, text

    def test_scrubs_token_assignments(self):
        from log_tail import scrub_secrets
        out = scrub_secrets("refresh_token=AMf-vBzQ12345 id_token: eyJfoo")
        assert "AMf-vBzQ12345" not in out

    def test_token_count_lines_survive(self):
        """A naive 'token' substring match would mangle these — they must pass."""
        from log_tail import scrub_secrets
        line = "completion used 1523 tokens (prompt_tokens 800, completion tokens 723)"
        assert scrub_secrets(line) == line

    def test_scrubs_jwt_shaped_strings(self):
        from log_tail import scrub_secrets
        jwt = "eyJhbGciOiJSUzI1NiIsImtpZCI.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4"
        out = scrub_secrets(f"got response {jwt} ok")
        assert jwt not in out


# =====================================================================
# Conversation package builder
# =====================================================================


async def _make_chat_with_items(db_session, tmp_path, media_count=2):
    from database import Chat, ChatItem
    from tests.helpers.media import generate_test_image, create_media_item

    async with db_session() as session:
        chat = Chat(name="Feedback test chat")
        session.add(chat)
        await session.flush()

        media_ids = []
        base = datetime.utcnow()
        for i in range(media_count):
            path = tmp_path / f"img_{i}.png"
            file_hash = generate_test_image(path, color=(i * 40 % 255, 0, 0))
            item = await create_media_item(
                session,
                file_path=path,
                file_hash=file_hash,
                created_date=base + timedelta(minutes=i),
            )
            media_ids.append(item.id)

        session.add(ChatItem(chat_id=chat.id, item_type="user_message",
                             message_text="make me a cat"))
        session.add(ChatItem(chat_id=chat.id, item_type="assistant_message",
                             message_text="Here is a cat."))
        session.add(ChatItem(chat_id=chat.id, item_type="tool_call",
                             tool_name="generate_image",
                             tool_args='{"prompt": "cat"}'))
        session.add(ChatItem(chat_id=chat.id, item_type="generated_media",
                             media_ids=json.dumps(media_ids)))
        await session.commit()
        return chat.id, media_ids


async def _make_agent_v2_chat(db_session, tmp_path):
    """A chat shaped like a real agent-v2 conversation: media reaches the chat
    through media_display rows, progress_display previews, inline markdown
    refs, tool_result payloads, and a grid composite — not item.media_id(s)."""
    from database import Chat, ChatItem
    from tests.helpers.media import generate_test_image, create_media_item

    async with db_session() as session:
        chat = Chat(name="Agent v2 feedback chat")
        session.add(chat)
        await session.flush()

        base = datetime.utcnow()

        async def mk(name, color, minute, **kwargs):
            path = tmp_path / name
            file_hash = generate_test_image(path, color=color)
            return await create_media_item(
                session, file_path=path, file_hash=file_hash,
                created_date=base + timedelta(minutes=minute), **kwargs,
            )

        gen = await mk("gen_only.png", (10, 10, 10), 0)       # tool_result only
        shown = await mk("shown.png", (200, 0, 0), 1)          # media_display row
        preview = await mk("preview.png", (0, 200, 0), 2)      # progress preview
        inline = await mk("inline.png", (0, 0, 200), 3)        # inline markdown
        cell_a = await mk("cell_a.png", (50, 50, 50), 4)       # grid cell
        cell_b = await mk("cell_b.png", (80, 80, 80), 5)       # grid cell

        # Grid composite referencing the two cells by relative path
        grid_path = tmp_path / "sweep.stimmagrid.json"
        grid_content = {
            "version": 1, "rows": 1, "cols": 2,
            "cells": [{"path": "cell_a.png"}, {"path": "cell_b.png"}],
        }
        grid_path.write_text(json.dumps(grid_content))
        grid = await create_media_item(
            session, file_path=grid_path, file_format="stimmagrid.json",
            created_date=base + timedelta(minutes=6),
            raw_metadata=json.dumps(grid_content),
        )

        # Library row whose file is gone from disk -> must surface as missing
        ghost = await create_media_item(
            session, file_path=tmp_path / "ghost.png",
            created_date=base + timedelta(minutes=7),
        )
        dangling_id = 987654  # referenced by the chat, no MediaItem row

        session.add(ChatItem(chat_id=chat.id, item_type="user_message",
                             message_text="make me a cat"))
        session.add(ChatItem(chat_id=chat.id, item_type="tool_call",
                             tool_name="call_tool", tool_call_id="tc_1",
                             tool_args='{"tool_id": "flux", "parameters": {"prompt": "cat"}}'))
        session.add(ChatItem(
            chat_id=chat.id, item_type="tool_result", tool_call_id="tc_1",
            tool_result=(
                f"<result media_id={gen.id} width=100 height=100>"
                f"Not yet shown to the user. Call show(media_id={gen.id})."
            ),
        ))
        session.add(ChatItem(
            chat_id=chat.id, item_type="media_display",
            item_metadata=json.dumps({"display_data": {
                "title": None, "status": "complete",
                "rows": [
                    {"id": "show_1", "input": {"type": "output_only"},
                     "output": {"status": "complete", "media_id": shown.id}},
                    {"id": "show_2", "input": {"type": "output_only"},
                     "output": {"status": "complete", "media_id": grid.id,
                                "file_format": "stimmagrid.json"}},
                    {"id": "show_3", "input": {"type": "output_only"},
                     "output": {"status": "complete", "media_id": ghost.id}},
                    {"id": "show_4", "input": {"type": "output_only"},
                     "output": {"status": "complete", "media_id": dangling_id}},
                ],
            }}),
        ))
        session.add(ChatItem(
            chat_id=chat.id, item_type="progress_display",
            item_metadata=json.dumps({"display_data": {
                "title": "Generating", "status": "completed",
                "current": 1, "total": 1, "previews": [preview.id],
            }}),
        ))
        session.add(ChatItem(
            chat_id=chat.id, item_type="assistant_message",
            message_text=f"Here you go ![cat](media_id={inline.id})",
        ))
        await session.commit()
        return chat.id, {
            "gen": gen.id, "shown": shown.id, "preview": preview.id,
            "inline": inline.id, "grid": grid.id,
            "cell_a": cell_a.id, "cell_b": cell_b.id,
            "ghost": ghost.id, "dangling": dangling_id,
        }


class TestPackageBuilder:
    @pytest.mark.asyncio
    async def test_chat_package_shape(self, db_session, tmp_path):
        from feedback_package import build_chat_package

        chat_id, media_ids = await _make_chat_with_items(db_session, tmp_path)
        async with db_session() as session:
            data = await build_chat_package(chat_id, session, agent_context="main")

        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        assert names[0] == "manifest.json"
        assert names[1] == "conversation.json"

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["packageVersion"] == 1
        assert manifest["agentContext"] == "main"
        assert "appVersion" in manifest
        # Both media files present and remapped to media/<n>.<ext>
        for mid in media_ids:
            entry = manifest["mediaMap"][str(mid)]
            assert entry.get("file", "").startswith("media/")
            assert entry["file"] in names

        conversation = json.loads(zf.read("conversation.json"))
        assert conversation["chat"]["id"] == chat_id
        messages = conversation["messages"]
        # Admin-viewer-compatible {role, text, media} entries
        assert messages[0] == {"role": "user", "text": "make me a cat", "media": []}
        assert messages[1]["role"] == "assistant"
        assert any(m["role"] == "tool_call" and "generate_image" in m["text"]
                   for m in messages)
        media_msg = [m for m in messages if m["media"]][0]
        assert all(name.startswith("media/") for name in media_msg["media"])
        # Raw items preserved
        assert len(conversation["items"]) == 4

    @pytest.mark.asyncio
    async def test_agent_v2_attachment_paths_all_collected(self, db_session, tmp_path):
        """Media attached via media_display rows, progress previews, inline
        markdown, tool_result payloads, and grid cells must land in the zip;
        unreadable/unknown media must surface in the manifest as missing."""
        from feedback_package import build_chat_package

        chat_id, ids = await _make_agent_v2_chat(db_session, tmp_path)
        async with db_session() as session:
            data = await build_chat_package(chat_id, session, agent_context="main")

        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))
        media_map = manifest["mediaMap"]

        # Every reachable media file is included and present in the zip
        for key in ("gen", "shown", "preview", "inline", "grid", "cell_a", "cell_b"):
            entry = media_map.get(str(ids[key]))
            assert entry is not None, f"{key} (media_id {ids[key]}) absent from mediaMap"
            assert entry.get("file", "").startswith("media/"), f"{key}: {entry}"
            assert entry["file"] in names, f"{key}: {entry['file']} not in zip"

        # Unreadable-from-disk and unknown ids surface as missing, never silently
        assert media_map[str(ids["ghost"])] == {
            "missing": True, "reason": "file_unavailable"
        }
        assert media_map[str(ids["dangling"])] == {
            "missing": True, "reason": "not_in_library"
        }

        # The media_display-derived message references the packaged files
        conversation = json.loads(zf.read("conversation.json"))
        display_msgs = [m for m in conversation["messages"]
                        if m["role"] == "media_display"]
        assert display_msgs, "media_display item produced no message"
        shown_name = media_map[str(ids["shown"])]["file"]
        assert shown_name in display_msgs[0]["media"]

    @pytest.mark.asyncio
    async def test_media_cap_newest_first_remainder_omitted(self, db_session, tmp_path):
        from feedback_package import build_chat_package
        from database import MediaItem
        from sqlalchemy import select

        chat_id, media_ids = await _make_chat_with_items(
            db_session, tmp_path / "cap", media_count=3
        )
        async with db_session() as session:
            result = await session.execute(
                select(MediaItem).where(MediaItem.id.in_(media_ids))
            )
            sizes = {m.id: Path(m.file_path).stat().st_size
                     for m in result.scalars().all()}
        # Cap that fits exactly one media file (they're all the same size)
        one_size = max(sizes.values())
        async with db_session() as session:
            data = await build_chat_package(
                chat_id, session, max_bytes=one_size + 10
            )

        zf = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf.read("manifest.json"))
        included = [k for k, v in manifest["mediaMap"].items() if "file" in v]
        omitted = [k for k, v in manifest["mediaMap"].items() if v.get("omitted")]
        assert len(included) == 1
        assert len(omitted) == 2
        assert all(v["reason"] == "size_cap"
                   for k, v in manifest["mediaMap"].items() if v.get("omitted"))
        # Newest-first: the included one is the newest (last created)
        assert included[0] == str(media_ids[-1])

    @pytest.mark.asyncio
    async def test_llm_traces_included(self, db_session, tmp_path):
        from feedback_package import build_chat_package
        from database import LLMTrace

        chat_id, _ = await _make_chat_with_items(db_session, tmp_path / "tr",
                                                 media_count=0)
        async with db_session() as session:
            session.add(LLMTrace(
                chat_id=chat_id, trace_type="planner",
                messages=json.dumps([{"role": "user", "content": "hi"}]),
                response="plan", model="test-model",
            ))
            await session.commit()
            data = await build_chat_package(chat_id, session)

        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        assert "llm_traces.json" in names
        # conversation.json comes before llm_traces.json so the admin viewer
        # renders the conversation, not the raw trace messages.
        assert names.index("conversation.json") < names.index("llm_traces.json")
        traces = json.loads(zf.read("llm_traces.json"))["traces"]
        assert traces[0]["trace_type"] == "planner"

    def test_prompt_agent_package(self):
        from feedback_package import build_prompt_agent_package
        data = build_prompt_agent_package({
            "messages": [
                {"role": "user", "content": "more dramatic"},
                {"role": "assistant", "content": "Done — added storm clouds."},
            ],
            "prompt": "a cat in the rain",
            "instructions": "keep it photoreal",
        })
        zf = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["agentContext"] == "prompt-agent"
        assert manifest["packageVersion"] == 1
        conversation = json.loads(zf.read("conversation.json"))
        assert conversation["messages"][0] == {
            "role": "user", "text": "more dramatic", "media": []
        }
        assert conversation["prompt"] == "a cat in the rain"


# =====================================================================
# Crash reports
# =====================================================================


@pytest.fixture
def crash_env(tmp_path, monkeypatch):
    """Isolated crash pending dir + controllable distribution/consent."""
    import crash_reports

    pending = tmp_path / "crashes" / "pending"
    monkeypatch.setattr(crash_reports, "get_pending_dir", lambda: pending)

    state = {"consent": "ask"}
    monkeypatch.setattr(crash_reports, "_crash_consent", lambda: state["consent"])

    # Reset the rate-limited drop-warning window (module state)
    monkeypatch.setattr(crash_reports, "_last_drop_warning", 0.0)

    # Log tail source
    import log_tail
    monkeypatch.setattr(log_tail, "tail_log_lines",
                        lambda n=200, log_dir=None: ["log line 1", "log line 2"])
    return state


def _boom(exc_type=ValueError, msg="kaboom with user content"):
    try:
        raise exc_type(msg)
    except Exception as e:
        return e


def _unique_booms(n):
    """n crashes with n distinct stack hashes (distinct exception types)."""
    return [_boom(type(f"CrashKind{i}Error", (RuntimeError,), {})) for i in range(n)]


class TestCrashReports:
    def test_dev_build_never_writes(self, crash_env, monkeypatch):
        import crash_reports
        monkeypatch.delenv("STIMMA_DISTRIBUTION", raising=False)
        assert crash_reports.record_crash(_boom()) is None
        assert crash_reports.list_pending() == []

    def test_official_writes_pending_report(self, crash_env, monkeypatch):
        import crash_reports
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        path = crash_reports.record_crash(_boom())
        assert path is not None and path.exists()
        report = json.loads(path.read_text())
        assert report["exceptionType"] == "ValueError"
        assert "kaboom" in report["message"]
        assert "ValueError" in report["stack"]
        assert report["stackHash"]
        assert report["logTail"] == ["log line 1", "log line 2"]
        assert report["appVersion"]
        assert report["appBranch"]
        assert report["os"]
        assert "sessionId" in report

    def test_consent_never_discards(self, crash_env, monkeypatch):
        import crash_reports
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        crash_env["consent"] = "never"
        assert crash_reports.record_crash(_boom()) is None
        assert crash_reports.list_pending() == []

    def test_batch_pending_and_discard(self, crash_env, monkeypatch):
        import crash_reports
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        crash_reports.record_crash(_boom(ValueError))
        crash_reports.record_crash(_boom(TypeError))
        crash_reports.record_crash(_boom(RuntimeError))
        pending = crash_reports.list_pending()
        assert len(pending) == 3
        assert {p["errorType"] for p in pending} == {
            "ValueError", "TypeError", "RuntimeError"
        }
        assert crash_reports.discard_pending() == 3
        assert crash_reports.list_pending() == []

    @pytest.mark.asyncio
    async def test_send_pending_submits_each_and_clears(self, crash_env, monkeypatch):
        import crash_reports
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        crash_reports.record_crash(_boom(ValueError))
        crash_reports.record_crash(_boom(TypeError))

        submitted = []

        async def fake_submit(**kwargs):
            submitted.append(kwargs)
            return "fake-id"

        import feedback_client
        monkeypatch.setattr(feedback_client, "submit_feedback", fake_submit)

        sent = await crash_reports.send_pending(track=False)
        assert sent == 2
        assert crash_reports.list_pending() == []
        for call in submitted:
            assert call["kind"] == "crash"
            assert call["error_hash"]
            crash_json = json.loads(call["crash"].decode())
            assert crash_json["exceptionType"] in ("ValueError", "TypeError")
            # Loop-visibility counters ride upstream in crash.json
            assert crash_json["occurrences"] == 1
            assert crash_json["firstSeenAt"] and crash_json["lastSeenAt"]
            assert "logTail" not in crash_json  # rides separately as logs.txt
            assert b"log line 1" in call["logs"]

    @pytest.mark.asyncio
    async def test_send_pending_noop_in_dev(self, crash_env, monkeypatch):
        import crash_reports
        # Write while official…
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        crash_reports.record_crash(_boom())
        # …but sending in a dev build is inert.
        monkeypatch.delenv("STIMMA_DISTRIBUTION", raising=False)
        assert await crash_reports.send_pending(track=False) == 0
        assert len(crash_reports.list_pending()) == 1

    @pytest.mark.asyncio
    async def test_startup_check_always_sends_silently(self, crash_env, monkeypatch):
        import crash_reports
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        crash_env["consent"] = "always"
        crash_reports.record_crash(_boom())

        sent_calls = []

        async def fake_send():
            sent_calls.append(True)

        monkeypatch.setattr(crash_reports, "send_pending_silently", fake_send)
        await crash_reports.startup_check()
        assert sent_calls == [True]

    @pytest.mark.asyncio
    async def test_startup_check_ask_leaves_pending_local(self, crash_env, monkeypatch):
        import crash_reports
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        crash_env["consent"] = "ask"
        crash_reports.record_crash(_boom())

        async def fail_send():
            raise AssertionError("ask-mode startup must not send crash reports")

        monkeypatch.setattr(crash_reports, "send_pending_silently", fail_send)
        await crash_reports.startup_check()
        assert len(crash_reports.list_pending()) == 1

    @pytest.mark.asyncio
    async def test_startup_check_never_discards_leftovers(self, crash_env, monkeypatch):
        import crash_reports
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        crash_reports.record_crash(_boom())
        crash_env["consent"] = "never"
        await crash_reports.startup_check()
        assert crash_reports.list_pending() == []


# =====================================================================
# Crash rate limiting (dedupe / cap / send throttle / backoff / storm)
# =====================================================================


class _FakeLog:
    def __init__(self):
        self.warnings = []

    def warning(self, *args, **kwargs):
        self.warnings.append((args, kwargs))

    def info(self, *args, **kwargs):
        pass


class TestCrashRateLimiting:
    def test_dedupe_increments_occurrences(self, crash_env, monkeypatch):
        import crash_reports
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        p1 = crash_reports.record_crash(_boom())
        p2 = crash_reports.record_crash(_boom())
        p3 = crash_reports.record_crash(_boom())
        assert p1 == p2 == p3
        pending = crash_reports.list_pending()
        assert len(pending) == 1
        assert pending[0]["occurrences"] == 3
        data = json.loads(p1.read_text())
        assert data["occurrences"] == 3
        assert data["firstSeenAt"] <= data["lastSeenAt"]

    def test_unique_cap_drops_new_with_one_warning(self, crash_env, monkeypatch):
        import crash_reports
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        fake_log = _FakeLog()
        monkeypatch.setattr(crash_reports, "log", fake_log)

        paths = [crash_reports.record_crash(e) for e in _unique_booms(14)]
        kept = paths[:crash_reports.MAX_UNIQUE_PENDING]
        dropped = paths[crash_reports.MAX_UNIQUE_PENDING:]
        assert all(p is not None for p in kept)
        assert all(p is None for p in dropped)
        assert len(crash_reports.list_pending()) == crash_reports.MAX_UNIQUE_PENDING
        # 4 drops -> exactly ONE warning (the log line itself is rate-limited)
        assert len(fake_log.warnings) == 1
        # A repeat of an already-pending crash still dedupes at the cap
        assert crash_reports.record_crash(_boom(type(
            "CrashKind0Error", (RuntimeError,), {}
        ))) is not None
        assert len(crash_reports.list_pending()) == crash_reports.MAX_UNIQUE_PENDING

    def test_always_mode_evicts_oldest_at_cap(self, crash_env, monkeypatch):
        import crash_reports
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        crash_env["consent"] = "always"
        booms = _unique_booms(11)
        paths = [crash_reports.record_crash(e) for e in booms[:10]]
        assert all(p is not None for p in paths)
        newest = crash_reports.record_crash(booms[10])
        assert newest is not None and newest.exists()  # newest wins
        assert len(crash_reports.list_pending()) == crash_reports.MAX_UNIQUE_PENDING
        assert sum(1 for p in paths if p.exists()) == 9  # one evicted

    @pytest.mark.asyncio
    async def test_send_throttle_rolling_24h(self, crash_env, monkeypatch):
        import time
        import crash_reports
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        for e in _unique_booms(5):
            crash_reports.record_crash(e)

        async def fake_submit(**kwargs):
            return "fake-id"

        import feedback_client
        monkeypatch.setattr(feedback_client, "submit_feedback", fake_submit)

        # Budget is 3 per rolling 24h — the remainder stays pending
        assert await crash_reports.send_pending(track=False) == 3
        assert len(crash_reports.list_pending()) == 2
        assert await crash_reports.send_pending(track=False) == 0
        assert len(crash_reports.list_pending()) == 2

        # Age the recorded sends past the window -> budget refills
        tp = crash_reports._throttle_path()
        state = json.loads(tp.read_text())
        state["sendTimes"] = [t - 25 * 3600 for t in state["sendTimes"]]
        tp.write_text(json.dumps(state))
        assert await crash_reports.send_pending(track=False) == 2
        assert crash_reports.list_pending() == []
        # And the spent budget is persisted again
        state = json.loads(tp.read_text())
        assert len([t for t in state["sendTimes"]
                    if time.time() - t < 24 * 3600]) == 2

    @pytest.mark.asyncio
    async def test_min_interval_between_auto_sends(self, crash_env, monkeypatch):
        import crash_reports
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")

        async def fake_submit(**kwargs):
            return "fake-id"

        import feedback_client
        monkeypatch.setattr(feedback_client, "submit_feedback", fake_submit)

        crash_reports.record_crash(_boom(ValueError))
        assert await crash_reports.send_pending(track=False, auto=True) == 1
        # A fresh crash right after: auto-send is spaced out (10 min)…
        crash_reports.record_crash(_boom(TypeError))
        assert await crash_reports.send_pending(track=False, auto=True) == 0
        assert len(crash_reports.list_pending()) == 1
        # …but a manual dialog send still works (within the daily budget)
        assert await crash_reports.send_pending(track=False) == 1
        assert crash_reports.list_pending() == []

    @pytest.mark.asyncio
    async def test_429_backoff_stops_all_sends(self, crash_env, monkeypatch):
        import time
        import crash_reports
        from feedback_client import FeedbackSubmitError
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        crash_reports.record_crash(_boom(ValueError))
        crash_reports.record_crash(_boom(TypeError))

        async def limited(**kwargs):
            raise FeedbackSubmitError("Daily feedback limit reached", 429)

        import feedback_client
        monkeypatch.setattr(feedback_client, "submit_feedback", limited)
        assert await crash_reports.send_pending(track=False) == 0
        # Reports stay pending; backoff is persisted for ~24h
        assert len(crash_reports.list_pending()) == 2
        state = json.loads(crash_reports._throttle_path().read_text())
        assert state["backoffUntil"] > time.time() + 23 * 3600

        # Even with the server healthy again, sends stay off until backoff ends
        async def fake_submit(**kwargs):
            return "fake-id"

        monkeypatch.setattr(feedback_client, "submit_feedback", fake_submit)
        assert await crash_reports.send_pending(track=False) == 0
        assert await crash_reports.send_pending(track=False, auto=True) == 0
        assert len(crash_reports.list_pending()) == 2

        # Backoff expiry restores sending
        state["backoffUntil"] = time.time() - 1
        crash_reports._throttle_path().write_text(json.dumps(state))
        assert await crash_reports.send_pending(track=False) == 2

    @pytest.mark.asyncio
    async def test_crash_storm_is_deduped_and_quiet(self, crash_env, monkeypatch):
        """100 identical crashes -> 1 pending file, counters right,
        <=1 warning, <=1 dialog (WS) request."""
        import crash_reports
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")

        fake_log = _FakeLog()
        monkeypatch.setattr(crash_reports, "log", fake_log)

        broadcasts = []
        from utils.websocket import ws_manager

        async def fake_broadcast(*args, **kwargs):
            broadcasts.append(args)

        monkeypatch.setattr(ws_manager, "broadcast", fake_broadcast)

        for _ in range(100):
            crash_reports.record_crash(_boom())
        # Flush the (single) broadcast task scheduled by the first crash
        for _ in range(3):
            await asyncio.sleep(0)

        pending = crash_reports.list_pending()
        assert len(pending) == 1
        assert pending[0]["occurrences"] == 100
        report_path = sorted(crash_reports.get_pending_dir().glob("*.json"))[0]
        full = json.loads(report_path.read_text(encoding="utf-8"))
        assert full["occurrences"] == 100
        assert full["firstSeenAt"] <= full["lastSeenAt"]
        assert len(fake_log.warnings) <= 1  # nothing to warn about here
        assert len(broadcasts) <= 1  # ONE dialog request, not 100


# =====================================================================
# Sidecar routes (gating + submission flow against a mocked cloud API)
# =====================================================================


@pytest.fixture(scope="module")
async def feedback_client_fixture(test_app):
    """httpx client with the feedback router mounted."""
    from httpx import ASGITransport
    import httpx as _httpx
    from routes import feedback as feedback_routes

    test_app.include_router(feedback_routes.router)
    transport = ASGITransport(app=test_app)
    async with _httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Profile-ID": "default"},
    ) as ac:
        yield ac


class FakeCloud:
    """Mocked stimma-cloud feedback API capturing the full submit flow."""

    def __init__(self):
        self.posts = []
        self.puts = []
        self.completes = []

    def make_async_client(self, **kwargs):
        fake = self

        class _Resp:
            def __init__(self, status_code, payload=None):
                self.status_code = status_code
                self._payload = payload or {}

            def json(self):
                return self._payload

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None, headers=None, **kw):
                if url.endswith("/complete"):
                    fake.completes.append({"url": url, "headers": headers})
                    return _Resp(200, {"id": "fb-1", "assets": {}})
                fake.posts.append({"url": url, "json": json, "headers": headers})
                wants = (json or {}).get("wants") or {}
                return _Resp(200, {
                    "id": "fb-1",
                    "uploadUrls": {k: f"https://r2.example/{k}" for k in wants},
                })

            async def put(self, url, content=None, **kw):
                fake.puts.append({"url": url, "bytes": len(content or b"")})
                return _Resp(200)

        return _Client()


@pytest.fixture
def fake_cloud(monkeypatch):
    fake = FakeCloud()
    import feedback_client
    monkeypatch.setattr(feedback_client.httpx, "AsyncClient",
                        lambda **kw: fake.make_async_client(**kw))

    async def no_token():
        return None
    import firebase_auth
    monkeypatch.setattr(firebase_auth, "get_valid_id_token", no_token)
    return fake


class TestFeedbackRoutes:
    @pytest.mark.asyncio
    async def test_state_defaults(self, feedback_client_fixture, monkeypatch):
        monkeypatch.delenv("STIMMA_DISTRIBUTION", raising=False)
        resp = await feedback_client_fixture.get("/api/feedback/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["distribution"] == "dev"
        assert data["thumbs_consent"] == "ask"
        assert data["crash_consent"] == "ask"
        assert data["pending_crashes"] == 0

    @pytest.mark.asyncio
    async def test_thumbs_submit_rejected_in_dev_build(
        self, feedback_client_fixture, fake_cloud, monkeypatch
    ):
        monkeypatch.delenv("STIMMA_DISTRIBUTION", raising=False)
        resp = await feedback_client_fixture.post("/api/feedback/submit", json={
            "kind": "thumbs", "thumb": "up", "message": "",
        })
        assert resp.status_code == 403
        assert fake_cloud.posts == []  # nothing egressed

    @pytest.mark.asyncio
    async def test_thumbs_submit_rejected_when_consent_never(
        self, feedback_client_fixture, fake_cloud, monkeypatch
    ):
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        from config import get_settings
        monkeypatch.setattr(get_settings().feedback, "thumbs_consent", "never")
        resp = await feedback_client_fixture.post("/api/feedback/submit", json={
            "kind": "thumbs", "thumb": "down", "message": "",
        })
        assert resp.status_code == 403
        assert fake_cloud.posts == []

    @pytest.mark.asyncio
    async def test_crash_routes_gated_in_dev_build(
        self, feedback_client_fixture, monkeypatch
    ):
        monkeypatch.delenv("STIMMA_DISTRIBUTION", raising=False)
        resp = await feedback_client_fixture.get("/api/feedback/crashes/pending")
        assert resp.status_code == 200
        assert resp.json()["reports"] == []
        resp = await feedback_client_fixture.post(
            "/api/feedback/crashes/decision", json={"action": "send"}
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_consent_patch_gated_in_dev_build(
        self, feedback_client_fixture, monkeypatch
    ):
        monkeypatch.delenv("STIMMA_DISTRIBUTION", raising=False)
        resp = await feedback_client_fixture.patch("/api/feedback/consent", json={
            "subject": "thumbs", "value": "always",
        })
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_feedback_submit_rejected_in_dev_build(
        self, feedback_client_fixture, fake_cloud
    ):
        resp = await feedback_client_fixture.post("/api/feedback/submit", json={
            "kind": "feedback",
            "message": "test message",
            "include_logs": True,
        })
        assert resp.status_code == 403
        assert fake_cloud.posts == []
        assert fake_cloud.puts == []
        assert fake_cloud.completes == []

    @pytest.mark.asyncio
    async def test_thumbs_submit_with_chat_package(
        self, feedback_client_fixture, fake_cloud, db_session, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        from config import get_settings
        monkeypatch.setattr(get_settings().feedback, "thumbs_consent", "ask")
        chat_id, _ = await _make_chat_with_items(db_session, tmp_path / "submit")

        resp = await feedback_client_fixture.post("/api/feedback/submit", json={
            "kind": "thumbs",
            "thumb": "down",
            "agent_context": "main",
            "message": "it drew a dog",
            "package": {"type": "chat", "chat_id": chat_id},
        })
        assert resp.status_code == 200
        post = fake_cloud.posts[0]
        assert post["json"]["kind"] == "thumbs"
        assert post["json"]["thumb"] == "down"
        assert post["json"]["agentContext"] == "main"
        assert post["json"]["wants"] == {"package": True}
        # The package PUT actually carried zip bytes
        assert fake_cloud.puts[0]["url"].endswith("/package")
        assert fake_cloud.puts[0]["bytes"] > 100

    @pytest.mark.asyncio
    async def test_screenshot_decoding(self, feedback_client_fixture, fake_cloud, monkeypatch):
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        import base64
        png = b"\x89PNG\r\n\x1a\nfakepngbytes"
        data_url = "data:image/png;base64," + base64.b64encode(png).decode()
        resp = await feedback_client_fixture.post("/api/feedback/submit", json={
            "kind": "feedback",
            "message": "with screenshot",
            "screenshot": data_url,
        })
        assert resp.status_code == 200
        assert fake_cloud.posts[-1]["json"]["wants"] == {"screenshot": True}
        assert fake_cloud.puts[-1]["bytes"] == len(png)

    @pytest.mark.asyncio
    async def test_crash_decision_send_while_throttled_keeps_pending(
        self, feedback_client_fixture, monkeypatch
    ):
        """Manual dialog send under the client throttle: nothing egresses,
        reports stay pending, the UI gets a 'rate_limited' status for its
        quiet note."""
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        import crash_reports
        monkeypatch.setattr(crash_reports, "is_send_throttled",
                            lambda auto=False: True)
        monkeypatch.setattr(crash_reports, "list_pending",
                            lambda: [{"file": "1-abc.json"}])

        sends = []

        async def fake_send(*a, **k):
            sends.append(True)
            return 0

        monkeypatch.setattr(crash_reports, "send_pending", fake_send)
        resp = await feedback_client_fixture.post(
            "/api/feedback/crashes/decision", json={"action": "send"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rate_limited"
        assert data["sent"] == 0
        assert data["pending"] == 1
        assert sends == []  # no send attempt at all

    @pytest.mark.asyncio
    async def test_rate_limit_propagates(self, feedback_client_fixture, monkeypatch):
        monkeypatch.setenv("STIMMA_DISTRIBUTION", "official")
        from feedback_client import FeedbackSubmitError

        async def limited(**kwargs):
            raise FeedbackSubmitError("Daily feedback limit reached", 429)

        import routes.feedback  # noqa: F401 — route imports inside handler
        import feedback_client
        monkeypatch.setattr(feedback_client, "submit_feedback", limited)
        resp = await feedback_client_fixture.post("/api/feedback/submit", json={
            "kind": "feedback", "message": "over the cap",
        })
        assert resp.status_code == 429
