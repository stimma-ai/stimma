"""The element resolver: fast path, budget, pins and exclusions, fallback, cache; Enhance and lineage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elements.resolver import ToolInfo, element_guidance_text, fluent_element_text, resolve
from prompt_programs.store import ProgramStore
from tests.test_elements import _edit_manifest, _library_image, _png, _tool

LORA_PATH = "characters/mira_klein_v2.safetensors"
FINGERPRINT = "stfp1:0123456789abcdef"

MIRA = """# Mira

{{#if lora_active}}
The LoRA draws her face: don't describe it.
{{else}}
Describe her face: olive skin, dark hazel eyes.
{{/if}}
"""


def _info(slots: int = 3) -> ToolInfo:
    return ToolInfo(
        tool_id="test:klein", model_family="flux-3-klein", task_type="image-to-image", max_ref_images=slots,
        lora_values=[LORA_PATH, "styles/film_grain.safetensors"],
        lora_fingerprints={LORA_PATH: FINGERPRINT, "styles/film_grain.safetensors": None},
    )


async def _element(session, tmp_path: Path, slug: str, media: list[dict], loras: list[dict], text: str = MIRA) -> int:
    workspace = tmp_path / f"ws-{slug}"
    menu = []
    for index, m in enumerate(media):
        asset_id, _media_id = await _library_image(session, _png(tmp_path / "lib" / f"{slug}-{index}.png", (index * 40, 90, 30)))
        menu.append({"key": m["key"], "asset_id": asset_id, "title": m.get("title", ""),
                     "conditional": m.get("conditional", False), "usage_hint": m.get("hint", "")})
    await _tool(session, workspace, action="init", slug=slug, name=slug.title(), kind="Character")
    directory = workspace / "elements" / slug
    _edit_manifest(directory, media_menu=menu, loras=loras, cover_member_key=menu[0]["key"] if menu else None)
    (directory / "ELEMENT.md").write_text(text)
    saved = await _tool(session, workspace, action="save", slug=slug)
    return int(saved.split("asset_id ")[1].split(",")[0])


MIRA_LORA = [{"key": "mira-klein-v2", "fingerprint": FINGERPRINT, "display_name": "mira_klein_v2",
              "model_family": "flux-3-klein", "default_weight": 0.8, "trigger": "mira_kl"}]
MIRA_MEDIA = [
    {"key": "face-front", "title": "Front, neutral", "hint": "Default identity anchor."},
    {"key": "expr-angry", "title": "Furious glare", "conditional": True, "hint": "When the prompt asks for anger."},
    {"key": "expr-smile", "title": "Big smile", "conditional": True, "hint": "When the prompt asks for joy."},
]


class FakeModel:
    def __init__(self, reply):
        self.reply = reply
        self.calls: list[list[dict]] = []

    async def __call__(self, messages):
        self.calls.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


@pytest.mark.asyncio
async def test_fast_path_binds_everything_without_a_model(db_session, tmp_path):
    async with db_session() as session:
        place = await _element(session, tmp_path, "market", [{"key": "street"}], [],
                               text="# Night market\nLanterns, wet stone.")
        mira = await _element(session, tmp_path, "mira", MIRA_MEDIA[:1], MIRA_LORA)
        model = FakeModel(AssertionError("no model on the fast path"))
        plan = await resolve(session, elements=[{"asset_id": mira}, {"asset_id": place}], tool_id="test:klein",
                             prompt="Mira at the market", info=_info(3), ask_model=model, use_store=False)
    assert plan["mode"] == "deterministic" and not model.calls
    assert [(r["element_asset_id"], r["member_key"]) for r in plan["selected_refs"]] == [
        (mira, "face-front"), (place, "street")]
    assert all(r["media_id"] for r in plan["selected_refs"])
    assert plan["selected_loras"] == [{"element_asset_id": mira, "lora_key": "mira-klein-v2", "path": LORA_PATH,
                                       "weight": 0.8, "trigger": "mira_kl", "reason": ""}]
    rendered = {e["asset_id"]: e["instructions"] for e in plan["elements"]}
    assert "don't describe it" in rendered[mira]["enhance"] and "olive skin" not in rendered[mira]["enhance"]
    assert set(rendered[mira]) == {"enhance", "fluent", "tool_agent"}


@pytest.mark.asyncio
async def test_several_images_are_a_choice_even_when_all_fit(db_session, tmp_path):
    async with db_session() as session:
        place = await _element(session, tmp_path, "market", [{"key": "street"}, {"key": "stall"}, {"key": "lanterns"}],
                               [], text="# Night market")
        model = FakeModel({"references": [{"element": 1, "key": "stall", "why": "A close shot at a stall"}],
                           "loras": [], "guidance": "[image 1] shows the stall."})
        plan = await resolve(session, elements=[{"asset_id": place}], tool_id="t", prompt="steam rising off a noodle stall",
                             info=_info(8), ask_model=model, use_store=False)
    assert plan["mode"] == "resolved" and len(model.calls) == 1
    assert [r["member_key"] for r in plan["selected_refs"]] == ["stall"]


@pytest.mark.asyncio
async def test_prompt_is_not_part_of_the_fast_path_key(db_session, tmp_path):
    async with db_session() as session:
        mira = await _element(session, tmp_path, "mira", MIRA_MEDIA[:1], MIRA_LORA)
        a = await resolve(session, elements=[{"asset_id": mira}], tool_id="t", prompt="one", info=_info(), use_store=False)
        b = await resolve(session, elements=[{"asset_id": mira}], tool_id="t", prompt="two", info=_info(), use_store=False)
    assert a["key"] == b["key"]


@pytest.mark.asyncio
async def test_model_shares_the_budget_and_bad_picks_are_dropped(db_session, tmp_path):
    async with db_session() as session:
        place = await _element(session, tmp_path, "market", [{"key": "street"}], [], text="# Market")
        mira = await _element(session, tmp_path, "mira", MIRA_MEDIA, MIRA_LORA)
        model = FakeModel({
            "references": [
                {"element": 1, "key": "expr-angry", "why": "She is furious"},
                {"element": 1, "key": "made-up", "why": "x"},
                {"element": 2, "key": "street"},
                {"element": 1, "key": "face-front"},
            ],
            "loras": [{"element": 1, "key": "mira-klein-v2", "weight": 0.7}, {"element": 2, "key": "nope"}],
            "guidance": "Keep her bob. [image 1] shows her glare; [image 3] the street; [image 4] is cut.",
        })
        plan = await resolve(session, elements=[{"asset_id": mira}, {"asset_id": place}], tool_id="t",
                             prompt="Mira glaring across the market", info=_info(2), ask_model=model, use_store=False)
    assert plan["mode"] == "resolved" and len(model.calls) == 1
    assert [(r["element_asset_id"], r["member_key"]) for r in plan["selected_refs"]] == [
        (mira, "expr-angry"), (place, "street")]
    assert plan["selected_refs"][0]["reason"] == "She is furious"
    assert [(lo["lora_key"], lo["weight"]) for lo in plan["selected_loras"]] == [("mira-klein-v2", 0.7)]
    # The model numbered its own list (a dropped pick included); the plan numbers its refs.
    assert plan["resolved_guidance"] == ("Keep her bob. {ref:1} shows her glare; {ref:2} the street; "
                                         "a reference image is cut.")
    user = model.calls[0][1]["content"]
    assert "Free reference image slots: 2." in user and "Mira glaring across the market" in user
    assert 'key "expr-angry"' in user and "use when: When the prompt asks for anger." in user


@pytest.mark.asyncio
async def test_user_slots_pins_and_exclusions_are_respected(db_session, tmp_path):
    async with db_session() as session:
        mira = await _element(session, tmp_path, "mira", MIRA_MEDIA, MIRA_LORA)
        model = FakeModel({"references": [{"element": 1, "key": "expr-smile"}, {"element": 1, "key": "face-front"},
                                          {"element": 1, "key": "expr-angry"}],
                           "loras": [{"element": 1, "key": "mira-klein-v2"}], "guidance": "g"})
        overrides = {
            "user_ref_count": 1,
            "pinned_refs": [{"element_asset_id": mira, "member_key": "face-front"}],
            "excluded_refs": [{"element_asset_id": mira, "member_key": "expr-angry"}],
            "excluded_loras": [{"element_asset_id": mira, "lora_key": "mira-klein-v2"}],
        }
        plan = await resolve(session, elements=[{"asset_id": mira}], tool_id="t", prompt="Mira laughing",
                             info=_info(3), ask_model=model, overrides=overrides, use_store=False)
    # 3 slots - 1 user image - 1 kept pick = 1 free; the kept and removed picks aren't offered.
    assert [r["member_key"] for r in plan["selected_refs"]] == ["expr-smile"]
    assert plan["selected_loras"] == []
    user = model.calls[0][1]["content"]
    assert "Free reference image slots: 1." in user
    assert 'key "face-front"' not in user and 'key "expr-angry"' not in user
    assert "Already placed by the user: face-front" in user


@pytest.mark.asyncio
async def test_model_failure_falls_back_to_main_images(db_session, tmp_path):
    async with db_session() as session:
        place = await _element(session, tmp_path, "market", [{"key": "street"}, {"key": "stall"}], [], text="# M")
        mira = await _element(session, tmp_path, "mira", MIRA_MEDIA, MIRA_LORA)
        for reply in (RuntimeError("model is down"), "I think the angry one!", {"references": [{"element": 9, "key": "x"}]}):
            plan = await resolve(session, elements=[{"asset_id": mira}, {"asset_id": place}], tool_id="t",
                                 prompt="Mira furious", info=_info(2), ask_model=FakeModel(reply), use_store=False)
            assert plan["mode"] == "fallback"
            # Each element's main image, in turns within the budget, and its first LoRA.
            assert [(r["element_asset_id"], r["member_key"]) for r in plan["selected_refs"]] == [
                (mira, "face-front"), (place, "street")]
            assert [lo["lora_key"] for lo in plan["selected_loras"]] == ["mira-klein-v2"]
            assert plan["warnings"]


@pytest.mark.asyncio
async def test_judged_plans_are_cached_and_fallbacks_are_not(db_session, tmp_path):
    store = ProgramStore(tmp_path / "store")
    async with db_session() as session:
        mira = await _element(session, tmp_path, "mira", MIRA_MEDIA, MIRA_LORA)
        args = dict(elements=[{"asset_id": mira}], tool_id="t", prompt="Mira smiling", info=_info(1), store=store)
        broken = FakeModel(RuntimeError("down"))
        assert (await resolve(session, ask_model=broken, **args))["mode"] == "fallback"
        model = FakeModel({"references": [{"element": 1, "key": "expr-smile"}], "loras": [], "guidance": "g"})
        first = await resolve(session, ask_model=model, **args)
        second = await resolve(session, ask_model=model, **args)
        changed = await resolve(session, ask_model=model, **{**args, "prompt": "Mira furious"})
    assert first["mode"] == "resolved" and second["mode"] == "cached" and changed["mode"] == "resolved"
    assert second["selected_refs"] == first["selected_refs"]
    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_a_cached_plan_follows_the_menu_as_it_is_now(db_session, tmp_path):
    from elements import resolver
    store = ProgramStore(tmp_path / "store")
    async with db_session() as session:
        mira = await _element(session, tmp_path, "mira", MIRA_MEDIA, MIRA_LORA)
        args = dict(elements=[{"asset_id": mira}], tool_id="t", prompt="Mira smiling", info=_info(2), store=store)
        model = FakeModel({"references": [{"element": 1, "key": "expr-smile"}, {"element": 1, "key": "face-front"}],
                           "loras": [], "guidance": "[image 1] for the smile, [image 2] for her face."})
        first = await resolve(session, ask_model=model, **args)
        # The stored plan holds media ids from when it was judged; a linked image has moved on since.
        stored = store.get(first["key"])
        stored["selected_refs"][0]["media_id"] = 987654
        store.put(first["key"], stored)
        resolver._memory.clear()
        again = await resolve(session, ask_model=model, **args)
        # A choice no longer on the menu (its image gone) is dropped, and its reference with it.
        stored["selected_refs"][0]["member_key"] = "gone"
        store.put(first["key"], stored)
        resolver._memory.clear()
        dropped = await resolve(session, ask_model=model, **args)
    assert again["mode"] == "cached" and len(model.calls) == 1
    assert [r["media_id"] for r in again["selected_refs"]] == [r["media_id"] for r in first["selected_refs"]]
    assert again["selected_refs"][0]["file_path"]
    assert [r["member_key"] for r in dropped["selected_refs"]] == ["face-front"]
    assert dropped["resolved_guidance"] == "a reference image for the smile, {ref:1} for her face."


@pytest.mark.asyncio
async def test_plans_are_not_shared_across_profiles(db_session, tmp_path):
    async with db_session() as session:
        mira = await _element(session, tmp_path, "mira", MIRA_MEDIA, MIRA_LORA)
        model = FakeModel({"references": [{"element": 1, "key": "expr-smile"}], "loras": [], "guidance": "g"})
        args = dict(elements=[{"asset_id": mira}], tool_id="t", prompt="Mira smiling", info=_info(1), ask_model=model)
        a = await resolve(session, profile_id="a", store=ProgramStore(tmp_path / "a"), **args)
        b = await resolve(session, profile_id="b", store=ProgramStore(tmp_path / "b"), **args)
        a2 = await resolve(session, profile_id="a", store=ProgramStore(tmp_path / "a"), **args)
    assert (a["mode"], b["mode"], a2["mode"]) == ("resolved", "resolved", "cached")
    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_resolve_route_and_lora_for_another_model(client, db_session, tmp_path):
    async with db_session() as session:
        other = [{**MIRA_LORA[0], "model_family": "qwen-image-2.1"}]
        mira = await _element(session, tmp_path, "mira", MIRA_MEDIA[:1], other)
        await session.commit()
    resp = await client.post("/api/elements/resolve", json={
        "elements": [{"asset_id": mira}, {"asset_id": 999999}], "tool_id": "no:such:tool", "prompt": "Mira"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # An unknown tool has no slots; the missing element is skipped, not an error.
    assert body["mode"] == "deterministic" and body["selected_refs"] == []
    assert [e["asset_id"] for e in body["elements"]] == [mira]
    assert any("no longer" in w for w in body["warnings"])


def test_element_guidance_text_is_plain_and_per_surface():
    context = {"guidance": "Image 1 is her face.", "elements": [
        {"name": "Mira", "instructions": {"enhance": "Keep the bob.", "fluent": "Keep the bob (fluent)."}}]}
    text = element_guidance_text(context, "fluent")
    assert "<active_elements>" in text and "Keep the bob (fluent)." in text and "Image 1 is her face." in text
    assert element_guidance_text(None) == "" and element_guidance_text({"elements": []}) == ""


@pytest.mark.asyncio
async def test_enhance_off_sends_the_prompt_verbatim_with_elements():
    from prompt_pipeline import run_prompt_pipeline

    context = {"guidance": "Keep her bob.", "elements": [{"name": "Mira", "instructions": {"enhance": "x"}}]}
    prompt = "Mira at the market, rain"
    out = await run_prompt_pipeline(None, prompt, {"autoImprove": {"enabled": False}}, element_context=context)
    assert out == prompt


def test_generation_element_context_follows_enhance_and_fluent():
    from routes.generation import _element_context

    context = {"guidance": "g", "elements": [{"name": "Mira", "instructions": {"enhance": "E", "fluent": "F"}}]}
    assert _element_context({}, False) is None
    assert _element_context({"elementContext": context}, False) == context
    assert _element_context({"elementContext": context}, True)["elements"][0]["instructions"]["enhance"] == "F"


@pytest.mark.asyncio
async def test_improve_system_prompt_carries_element_guidance(db_session):
    from routes.prompt_enhancement import ImprovePromptRequest, style_guide

    context = {"guidance": "Image 1 is her face.", "elements": [{"name": "Mira", "instructions": {"enhance": "Never describe her face."}}]}
    async with db_session() as session:
        system, _images, _mode = await style_guide(
            ImprovePromptRequest(prompt="Mira in rain", model="flux-dev", element_context=context), session)
    assert "Never describe her face." in system and "<active_elements>" in system


@pytest.mark.asyncio
async def test_job_elements_are_recorded_on_the_output(db_session, tmp_path):
    from sqlalchemy import select

    from database import MediaElement, MediaItem
    from elements.lineage import record_job_elements
    from generation_metadata import INTERNAL_PARAM_KEYS

    assert "_elements" in INTERNAL_PARAM_KEYS
    async with db_session() as session:
        mira = await _element(session, tmp_path, "mira", MIRA_MEDIA[:1], MIRA_LORA)
        _asset, output = await _library_image(session, _png(tmp_path / "out.png"))
        assert await record_job_elements(session, output, {"prompt": "p"}) == []
        entries = await record_job_elements(session, output, {"_elements": [{"asset_id": mira, "carrier": "refs"}]})
        rows = list(await session.scalars(select(MediaElement).where(MediaElement.media_id == output)))
        media = await session.get(MediaItem, output)
    assert [(r.element_asset_id, r.carrier) for r in rows] == [(mira, "refs")]
    assert json.loads(media.generation_metadata)["elements"] == entries


def test_fluent_variant_writer_keeps_to_the_elements_and_pools_are_keyed_by_them():
    from prompt_programs import variants as V
    from prompt_programs.variant_pools import pool_key
    context = {"guidance": "per-prompt, left out", "elements": [
        {"name": "Old Wen", "instructions": {"fluent": "Gray stubble, a white towel on his shoulder.", "enhance": "x"}}]}
    text = fluent_element_text(context)
    assert text == "## Old Wen\nGray stubble, a white towel on his shoulder." and fluent_element_text(None) == ""
    prompt = "<old man> at a noodle stall"
    slot = V.Slot(words="old man", prompt=prompt, span=(0, 9), kind="free", elements=text)
    user = V.messages(slot, V.draw_seeds(__import__("random").Random(1), V.Seeds(), 3, "old man"), V.Seeds())[1]["content"]
    assert V.ELEMENTS_LINE in user and "Gray stubble, a white towel" in user
    plain = V.messages(V.Slot(words="old man", prompt=prompt, span=(0, 9)), V.draw_seeds(
        __import__("random").Random(1), V.Seeds(), 3, "old man"), V.Seeds())[1]["content"]
    assert V.ELEMENTS_LINE not in plain
    assert pool_key("m", "old man", prompt, []) != pool_key("m", "old man", prompt, [], elements="abc")
    assert pool_key("m", "old man", prompt, []) == pool_key("m", "old man", prompt, [], elements="")


@pytest.mark.asyncio
async def test_refs_active_follows_the_images_placed_for_each_element(db_session, tmp_path):
    text = "# Ada\n{{#if refs_active or lora_active}}\nPoint at her image.\n{{else}}\nGray eyes, red braid.\n{{/if}}\n"
    async with db_session() as session:
        ada = await _element(session, tmp_path, "ada", [{"key": "face-front"}], [], text=text)
        with_room = await resolve(session, elements=[{"asset_id": ada}], tool_id="t", prompt="Ada reading",
                                  info=_info(3), use_store=False)
        no_room = await resolve(session, elements=[{"asset_id": ada}], tool_id="t", prompt="Ada reading",
                                info=_info(0), use_store=False)
    assert "Point at her image." in with_room["elements"][0]["instructions"]["enhance"]
    assert "Gray eyes" not in with_room["elements"][0]["instructions"]["enhance"]
    assert "Gray eyes" in no_room["elements"][0]["instructions"]["enhance"]
