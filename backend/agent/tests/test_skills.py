"""Backend-mechanics tests for multi-skill stimpacks + per-environment targeting.

Covers the mechanics only (agent behavior is an eval concern, tracked
separately):
- multi-skill parse/load (no resources[0] collapse; stable qualified identity)
- lib/ aggregation across a pack's skills (color-math as the lib fixture)
- eligibility filtering per environment (chat / flow / tool task_types)
- injection strings (the invoke path returns the right body, labeled "skill")
"""

import json
from pathlib import Path

import pytest

import agent.v2.stimpacks as sp
from agent.v2.stimpacks import (
    SkillEnvironments,
    _parse_environments,
    find_skill,
    get_stimpack_lib_modules,
    list_skills,
    load_skill,
    load_stimpack,
)
from agent.v2.system_reminders import build_skills_reminder


# =============================================================================
# Fixture pack builders
# =============================================================================

COLOR_MATH_LIB = '''\
def rgb_to_hex(r, g, b):
    return "#{:02x}{:02x}{:02x}".format(int(r), int(g), int(b))
'''


def _write_skill(pack_dir: Path, slug: str, frontmatter: str, body: str) -> Path:
    skill_dir = pack_dir / "skills" / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return skill_dir


def _write_manifest(pack_dir: Path, name: str) -> None:
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "stimpack.json").write_text(json.dumps({
        "name": name,
        "display_name": name.replace("-", " ").title(),
        "description": f"{name} test pack",
        "version": "1",
        "author": "system",
        "tags": [],
    }), encoding="utf-8")


@pytest.fixture
def stimpacks_dir(tmp_path, monkeypatch):
    """Point the stimpack loader at an isolated temp dir."""
    packs = tmp_path / "stimpacks"
    packs.mkdir()
    monkeypatch.setattr(sp, "get_user_stimpacks_dir", lambda profile_id=None: packs)
    monkeypatch.setattr(sp, "_dev_stimpacks_dir", lambda: None)
    monkeypatch.setattr(sp, "get_current_profile", lambda: "test-profile")
    return packs


@pytest.fixture
def multi_skill_pack(stimpacks_dir) -> Path:
    """A pack with two skills; `color-math` carries lib/ (the lib fixture)."""
    pack = stimpacks_dir / "test-pack"
    _write_manifest(pack, "test-pack")
    _write_skill(
        pack, "alpha",
        "name: alpha\ndisplay_name: Alpha\ndescription: Alpha skill\n"
        "environments:\n  chat: true\n  flow: true\n  tool:\n    task_types: [text-to-image]",
        "Alpha body",
    )
    color_math_dir = _write_skill(
        pack, "color-math",
        "name: color-math\ndisplay_name: Color Math\ndescription: Color helpers\n"
        "provides:\n  - color_math",
        "Color math body",
    )
    lib = color_math_dir / "lib"
    lib.mkdir()
    (lib / "color_math.py").write_text(COLOR_MATH_LIB, encoding="utf-8")
    return pack


@pytest.fixture
def legacy_pack(stimpacks_dir) -> Path:
    """A legacy single-skill pack: root SKILL.md, no skills/ dir."""
    pack = stimpacks_dir / "legacy-pack"
    pack.mkdir()
    (pack / "SKILL.md").write_text(
        "---\nname: legacy-pack\ndisplay_name: Legacy Pack\ndescription: Old layout\n---\n\nLegacy body",
        encoding="utf-8",
    )
    return pack


# =============================================================================
# Multi-skill parse / load
# =============================================================================

class TestMultiSkillLoad:
    def test_pack_loads_all_skills(self, multi_skill_pack):
        info = sp._parse_stimpack_dir(multi_skill_pack)
        assert info is not None
        assert [s.slug for s in info.skills] == ["alpha", "color-math"]

    def test_qualified_identity_is_pack_qualified_and_stable(self, multi_skill_pack):
        skills = list_skills()
        names = {s.qualified_name for s in skills}
        assert {"test-pack/alpha", "test-pack/color-math"} <= names

    def test_provides_unions_across_skills(self, multi_skill_pack):
        info = sp._parse_stimpack_dir(multi_skill_pack)
        assert info.provides == ["color_math"]

    def test_find_skill_by_qualified_and_unique_bare_name(self, multi_skill_pack):
        assert find_skill("test-pack/alpha")[1].slug == "alpha"
        assert find_skill("alpha")[1].qualified_name == "test-pack/alpha"
        assert find_skill("missing") is None

    def test_bare_name_ambiguous_across_packs_is_rejected(self, stimpacks_dir, multi_skill_pack):
        other = stimpacks_dir / "other-pack"
        _write_manifest(other, "other-pack")
        _write_skill(other, "alpha", "name: alpha\ndescription: Other alpha", "Other alpha body")
        assert find_skill("alpha") is None
        assert find_skill("test-pack/alpha") is not None
        assert find_skill("other-pack/alpha") is not None

    def test_legacy_root_skill_md_still_loads(self, legacy_pack):
        info = sp._parse_stimpack_dir(legacy_pack)
        assert len(info.skills) == 1
        skill = info.skills[0]
        # Slug matches the pack name, so the qualified name collapses.
        assert skill.qualified_name == "legacy-pack"
        loaded = load_skill("legacy-pack")
        assert loaded.content.strip() == "Legacy body"

    def test_pack_level_load_returns_first_skill(self, multi_skill_pack):
        loaded = load_stimpack("test-pack")
        assert loaded is not None
        assert loaded.content.strip() == "Alpha body"

    def test_save_stimpack_refuses_multi_skill_pack(self, multi_skill_pack):
        with pytest.raises(ValueError, match="multiple skills"):
            sp.save_stimpack("test-pack", "new content")


# =============================================================================
# lib/ aggregation
# =============================================================================

class TestLibAggregation:
    def test_lib_modules_resolve_for_invoked_skill(self, multi_skill_pack):
        modules = get_stimpack_lib_modules(["test-pack/color-math"])
        assert set(modules) == {"color_math"}
        assert modules["color_math"] == multi_skill_pack / "skills" / "color-math" / "lib"

    def test_lib_modules_scoped_to_the_carrying_skill(self, multi_skill_pack):
        assert get_stimpack_lib_modules(["test-pack/alpha"]) == {}

    def test_lib_module_importable_via_run_code_import_hook(self, multi_skill_pack):
        from agent.v2.code_runtime import _make_safe_import
        modules = get_stimpack_lib_modules(["test-pack/color-math"])
        safe_import = _make_safe_import(modules)
        color_math = safe_import("color_math")
        assert color_math.rgb_to_hex(255, 0, 0) == "#ff0000"

    def test_collision_across_skills_keeps_first(self, stimpacks_dir, multi_skill_pack):
        other = stimpacks_dir / "other-pack"
        _write_manifest(other, "other-pack")
        clash_dir = _write_skill(
            other, "clash",
            "name: clash\ndescription: Clashing lib\nprovides:\n  - color_math",
            "Clash body",
        )
        (clash_dir / "lib").mkdir()
        (clash_dir / "lib" / "color_math.py").write_text("VALUE = 2\n", encoding="utf-8")

        modules = get_stimpack_lib_modules(["test-pack/color-math", "other-pack/clash"])
        assert modules["color_math"] == multi_skill_pack / "skills" / "color-math" / "lib"


# =============================================================================
# Eligibility filtering
# =============================================================================

class TestEligibility:
    def test_absent_environments_block_means_chat_only(self):
        env = _parse_environments({})
        assert (env.chat, env.flow, env.tool) == (True, False, False)

    def test_absent_key_means_false(self):
        env = _parse_environments({"environments": {"flow": True}})
        assert (env.chat, env.flow, env.tool) == (False, True, False)

    def test_tool_wildcard_and_scoped_forms(self):
        wildcard = _parse_environments({"environments": {"tool": True}})
        assert wildcard.tool and wildcard.tool_task_types is None
        assert wildcard.eligible_for_tool(["anything"])

        scoped = _parse_environments(
            {"environments": {"tool": {"task_types": ["text-to-image", "image-to-image"]}}}
        )
        assert scoped.tool and scoped.tool_task_types == ["text-to-image", "image-to-image"]
        assert scoped.eligible_for_tool(["text-to-image"])
        assert not scoped.eligible_for_tool(["text-to-video"])

    def test_chat_only_skill_not_offered_to_flow(self, multi_skill_pack):
        skills = list_skills()
        chat_reminder = build_skills_reminder(skills, set(), environment="chat") or ""
        flow_reminder = build_skills_reminder(skills, set(), environment="flow") or ""
        # color-math has no environments block -> chat only
        assert "test-pack/color-math" in chat_reminder
        assert "test-pack/color-math" not in flow_reminder
        # alpha opted into both
        assert "test-pack/alpha" in chat_reminder
        assert "test-pack/alpha" in flow_reminder

    def test_tool_eligibility_matches_task_types(self, multi_skill_pack):
        by_name = {s.qualified_name: s for s in list_skills()}
        alpha = by_name["test-pack/alpha"]
        color_math = by_name["test-pack/color-math"]
        assert alpha.environments.eligible_for_tool(["text-to-image"])
        assert not alpha.environments.eligible_for_tool(["upscale"])
        assert not color_math.environments.eligible_for_tool(["text-to-image"])

    def test_invoked_skills_drop_out_of_reminder(self, multi_skill_pack):
        skills = list_skills()
        reminder = build_skills_reminder(skills, {"test-pack/alpha"}, environment="chat") or ""
        assert "test-pack/alpha" not in reminder
        assert "test-pack/color-math" in reminder

    def test_reminder_none_when_nothing_eligible(self, multi_skill_pack):
        skills = list_skills()
        invoked = {s.qualified_name for s in skills}
        assert build_skills_reminder(skills, invoked, environment="chat") is None

    def test_environments_to_dict_round_trip(self):
        env = SkillEnvironments(chat=True, flow=False, tool=True, tool_task_types=["text-to-image"])
        assert env.to_dict() == {"chat": True, "flow": False, "tool": {"task_types": ["text-to-image"]}}


# =============================================================================
# Injection strings (the invoke path)
# =============================================================================

class TestInjection:
    @pytest.mark.asyncio
    async def test_invoke_injects_skill_body_labeled_skill(self, multi_skill_pack, session, test_chat):
        from agent.v2.tools.skill import skill_tool
        injected = []
        result = await skill_tool(
            action="invoke",
            name="test-pack/alpha",
            session=session,
            chat_id=test_chat.id,
            _injected_messages=injected,
        )
        assert result == "Loaded skill 'Alpha'."
        assert len(injected) == 1
        assert injected[0]["skill_name"] == "test-pack/alpha"
        assert injected[0]["skill_display_name"] == "Alpha"
        assert injected[0]["content"] == "## Skill: Alpha\n\nAlpha body"

    @pytest.mark.asyncio
    async def test_invoke_unknown_skill_errors(self, multi_skill_pack, session, test_chat):
        from agent.v2.tools.skill import skill_tool
        result = await skill_tool(
            action="invoke", name="nope", session=session, chat_id=test_chat.id,
            _injected_messages=[],
        )
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_invoke_chat_only_skill_rejected_in_flow_chat(self, multi_skill_pack, session):
        from agent.v2.tools.skill import skill_tool
        from database import Chat, Flow
        flow = Flow(name="Test Flow")
        session.add(flow)
        await session.commit()
        chat = Chat(name="Flow Chat", flow_id=flow.id)
        session.add(chat)
        await session.commit()

        injected = []
        # color-math is chat-only (no environments block)
        result = await skill_tool(
            action="invoke",
            name="test-pack/color-math",
            session=session,
            chat_id=chat.id,
            _injected_messages=injected,
        )
        assert "not available in this environment" in result
        assert injected == []

        # alpha opted into flow — loads fine
        result = await skill_tool(
            action="invoke",
            name="test-pack/alpha",
            session=session,
            chat_id=chat.id,
            _injected_messages=injected,
        )
        assert result == "Loaded skill 'Alpha'."

    @pytest.mark.asyncio
    async def test_list_is_environment_filtered_and_labeled(self, multi_skill_pack, session, test_chat):
        from agent.v2.tools.skill import skill_tool
        result = await skill_tool(action="list", session=session, chat_id=test_chat.id)
        assert "test-pack/alpha" in result
        assert "test-pack/color-math" in result
        assert "Test Pack" in result  # pack attribution column

    @pytest.mark.asyncio
    async def test_already_invoked_reported_via_legacy_metadata_key(self, multi_skill_pack, session, test_chat):
        from agent.v2.tools.skill import skill_tool
        from database import ChatItem
        item = ChatItem(
            chat_id=test_chat.id,
            item_type="stimpack_injection",
            message_text="## Skill: Alpha\n\nAlpha body",
            item_metadata=json.dumps({"stimpack_name": "test-pack/alpha"}),
        )
        session.add(item)
        await session.commit()
        result = await skill_tool(
            action="invoke", name="test-pack/alpha",
            session=session, chat_id=test_chat.id, _injected_messages=[],
        )
        assert "already loaded" in result
