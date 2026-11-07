"""Contact sheets: the document format, publishing through the SDK, and review."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import select

from contact_sheet import SheetError, normalize_sheet_html, sheet_components
from database import Asset, AssetRevision, Chat, ChatItem, ContainerMember, MediaItem
from tests.helpers.media import create_media_item


def _png(path: Path, color=(200, 80, 40), size=(64, 48)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG")
    return path


async def _image(session, tmp_path: Path, name: str, color) -> MediaItem:
    import hashlib

    path = _png(tmp_path / name, color)
    return await create_media_item(
        session, file_path=path, file_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
        file_size=path.stat().st_size, width=64, height=48,
    )


async def _resolve_digits(ref: str) -> int:
    text = ref.removeprefix("media:")
    if not text.isdigit():
        raise SheetError("not a media id")
    return int(text)


# -- the document -------------------------------------------------------------

async def test_normalize_canonicalizes_refs_and_assigns_ids():
    html = """
    <style>.x{color:red}</style>
    <stimma-section label="Round 1" note="First pass">
      <stimma-media-group layout="rows">
        <stimma-media ref="12" caption="One"/>
        <stimma-media id="hero" ref="media:13"></stimma-media>
      </stimma-media-group>
    </stimma-section>
    <stimma-rating for="hero"></stimma-rating>
    <stimma-check for="nope">Approved</stimma-check>
    <stimma-choice id="pick" label="Which?"><stimma-option value="a" ref="12">A</stimma-option></stimma-choice>
    <stimma-sparkle></stimma-sparkle>
    <script>alert(1)</script>
    """
    sheet = await normalize_sheet_html(html, _resolve_digits)
    assert sheet.media_ids == [12, 13]
    assert 'ref="media:12"' in sheet.html and 'ref="media:13"' in sheet.html
    # The self-closing media tag is closed, so later siblings don't nest in it.
    assert '<stimma-media id="media-1" ref="media:12" caption="One"></stimma-media>' in sheet.html
    assert sheet.components["hero"] == "stimma-media"
    assert sheet.components["pick"] == "stimma-choice"
    assert {"section-1", "rating-1", "check-1"} <= set(sheet.components)
    assert "<script" not in sheet.html
    joined = " ".join(sheet.warnings)
    assert "Removed <script>" in joined
    assert "<stimma-sparkle>" in joined
    assert 'for="nope"' in joined


async def test_normalize_renames_duplicate_ids_and_rejects_bad_refs():
    sheet = await normalize_sheet_html(
        '<stimma-media id="a" ref="1"></stimma-media><stimma-media id="a" ref="2"></stimma-media>', _resolve_digits)
    assert sheet.html.count('id="a"') == 1
    assert any("more than once" in w for w in sheet.warnings)
    with pytest.raises(SheetError, match='ref="hero.png"'):
        await normalize_sheet_html('<stimma-media ref="hero.png"></stimma-media>', _resolve_digits)
    with pytest.raises(SheetError, match="needs ref"):
        await normalize_sheet_html('<stimma-media></stimma-media>', _resolve_digits)
    with pytest.raises(SheetError, match="empty"):
        await normalize_sheet_html("   ", _resolve_digits)


def test_sheet_components_reads_labels_and_options():
    components = sheet_components(
        '<stimma-check id="ok" for="m">Approved for the shop</stimma-check>'
        '<stimma-choice id="c" label="Which?"><stimma-option value="a" ref="media:4">Evergreen</stimma-option>'
        '<stimma-option value="b">Tide line</stimma-option></stimma-choice>'
    )
    assert components["ok"]["text"] == "Approved for the shop"
    assert [o["label"] for o in components["c"]["options"]] == ["Evergreen", "Tide line"]
    assert components["c"]["options"][0]["ref"] == "media:4"


# -- publishing ---------------------------------------------------------------

def _sdk(session, workspace: Path, chat_id: int):
    return SimpleNamespace(
        session=session, workspace_dir=workspace, project_workspace_dir=None, chat_id=chat_id,
        project_id=None, _shown_media_ids=[], _display_receipts=[], _stdout_print=lambda *_a: None,
        library=None,
    )


@pytest.fixture
def no_agent(monkeypatch):
    calls = []

    async def _fake_run(**kwargs):
        calls.append(kwargs)

    async def _fake_name(*_a, **_k):
        return None

    monkeypatch.setattr("routes.chats._run_agent_background", _fake_run)
    monkeypatch.setattr("routes.chats.auto_name_chat", _fake_name)
    return calls


async def test_publish_open_revise_and_review(client, db_session, tmp_path, no_agent):
    from agent.v2.contact_sheet_sdk import StimmaContactSheetsAPI

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    async with db_session() as session:
        chat = Chat(name="Sheet chat")
        session.add(chat)
        await session.commit()
        a = await _image(session, tmp_path, "a.png", (200, 40, 40))
        b = await _image(session, tmp_path, "b.png", (40, 200, 40))
        c = await _image(session, tmp_path, "c.png", (40, 40, 200))
        api = StimmaContactSheetsAPI(_sdk(session, workspace, chat.id))

        sheet = api.new("Spring directions")
        sheet.set_html(f"""
<h1>Spring directions</h1>
<stimma-section id="round-1" label="Round 1">
  <stimma-media-group id="round-1-media">
    <stimma-media id="hero" ref="{a.id}" caption="Ridge"></stimma-media>
  </stimma-media-group>
</stimma-section>
<stimma-choice id="direction" label="Which direction should I develop?">
  <stimma-option value="a" ref="{a.id}">Evergreen</stimma-option>
  <stimma-option value="b" ref="{b.id}">Tide line</stimma-option>
</stimma-choice>
<stimma-rating id="rate-hero" for="hero"></stimma-rating>
""")
        first = await sheet.publish("Round 1")
        assert first["version"] == 1 and first["media_count"] == 2
        asset = await session.get(Asset, first["asset_id"])
        assert asset.asset_type == "sheet"
        assert asset.title == "Spring directions"
        revision = await session.get(AssetRevision, asset.current_revision_id)
        members = list(await session.scalars(select(ContainerMember).where(
            ContainerMember.container_revision_id == revision.id, ContainerMember.deleted_at.is_(None))))
        assert sorted(m.embedded_media_id for m in members) == sorted([a.id, b.id])
        display = await session.scalar(select(ChatItem).where(
            ChatItem.chat_id == chat.id, ChatItem.item_type == "media_display").order_by(ChatItem.id.desc()))
        artifact = json.loads(display.item_metadata)["display_data"]["artifact"]
        assert artifact["asset_id"] == asset.id and artifact["revision_number"] == 1
        sheet_media_id = revision.primary_media_id

        # The viewer's content: the HTML and every referenced media, resolved.
        response = await client.get(f"/api/media/{sheet_media_id}/content")
        assert response.status_code == 200, response.text
        content = response.json()
        assert content["type"] == "contact_sheet"
        assert f'ref="media:{a.id}"' in content["html"]
        assert content["members"][str(a.id)]["width"] == 64
        assert content["revision_number"] == 1

        thumb = await client.get(f"/api/media/{sheet_media_id}/thumbnail?profile=default")
        assert thumb.status_code == 200
        assert thumb.headers["content-type"].startswith("image/")

        # Review: an answer and a comment, then send.
        r = await client.put(f"/api/contact-sheets/{asset.id}/review/answers/direction", json={"value": "b"})
        assert r.status_code == 200, r.text
        r = await client.put(f"/api/contact-sheets/{asset.id}/review/answers/rate-hero", json={"value": 4})
        assert r.status_code == 200
        r = await client.post(f"/api/contact-sheets/{asset.id}/review/comments",
                              json={"anchor": "hero", "text": "Love this grey."})
        assert r.status_code == 200
        review = (await client.get(f"/api/contact-sheets/{asset.id}/review")).json()
        assert review["answers"]["direction"]["value"] == "b"
        assert review["pending"] == 3

        sdk_review = await api.review()
        assert sdk_review["unsent"] == 3
        assert {item["text"] for item in sdk_review["answers"]} == {"Tide line", "4 of 5"}

        sent = await client.post(f"/api/contact-sheets/{asset.id}/review/send", json={"chat_id": chat.id})
        assert sent.json() == {"sent": 3, "delivery": "message"}
        assert len(no_agent) == 1
        message = await session.scalar(select(ChatItem).where(
            ChatItem.chat_id == chat.id, ChatItem.item_type == "user_message").order_by(ChatItem.id.desc()))
        assert f'- Which direction should I develop? [direction]: Tide line (media {b.id})' in message.message_text
        assert f'- Rating, for "Ridge" (media {a.id}) [rate-hero]: 4 of 5' in message.message_text
        assert f'- Comment on "Ridge" (media {a.id}) [hero]: Love this grey.' in message.message_text
        assert json.loads(message.item_metadata)["contact_sheet_review"]["asset_id"] == asset.id
        again = await client.post(f"/api/contact-sheets/{asset.id}/review/send", json={"chat_id": chat.id})
        assert again.json() == {"sent": 0, "delivery": None}

        # Continue the sheet: a new section at the top, a new version of the same asset.
        reopened = await api.open()
        assert reopened.asset_id == asset.id
        assert f'ref="media:{a.id}"' in reopened.html()
        group = reopened.add_section("round-2", "Round 2", "Tide line, developed", position="start")
        tile_ids = reopened.add(group, [c.id], captions=["Headland"])
        assert tile_ids == ["round-2-media-1"]
        second = await reopened.publish("Round 2")
        assert second["asset_id"] == asset.id and second["version"] == 2
        assert second["media_count"] == 3
        assert not second["warnings"]

        # Dropping a reviewed component warns: the review would lose its place.
        reopened.set_html(reopened.html().replace('id="hero"', 'id="ridge"').replace('for="hero"', 'for="ridge"'))
        third = await reopened.publish()
        assert any("hero" in w and "review" in w for w in third["warnings"])


async def test_review_routes_reject_non_sheets(client, db_session, tmp_path):
    async with db_session() as session:
        media = await _image(session, tmp_path, "plain.png", (10, 10, 10))
        media_id = media.id
    r = await client.get(f"/api/contact-sheets/{media_id}/review")
    assert r.status_code == 404
