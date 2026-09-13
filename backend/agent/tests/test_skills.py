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
def single_skill_pack(stimpacks_dir) -> Path:
    """A single-skill pack: root SKILL.md, no skills/ dir."""
    pack = stimpacks_dir / "single-pack"
    pack.mkdir()
    (pack / "SKILL.md").write_text(
        "---\nname: single-pack\ndisplay_name: Single Pack\ndescription: Root layout\n---\n\nSingle body",
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

    def test_root_skill_md_loads(self, single_skill_pack):
        info = sp._parse_stimpack_dir(single_skill_pack)
        assert len(info.skills) == 1
        skill = info.skills[0]
        # Slug matches the pack name, so the qualified name collapses.
        assert skill.qualified_name == "single-pack"
        loaded = load_skill("single-pack")
        assert loaded.content.strip() == "Single body"

    def test_pack_level_load_returns_first_skill(self, multi_skill_pack):
        loaded = load_stimpack("test-pack")
        assert loaded is not None
        assert loaded.content.strip() == "Alpha body"

    def test_save_stimpack_refuses_multi_skill_pack(self, multi_skill_pack):
        with pytest.raises(ValueError, match="multiple skills"):
            sp.save_stimpack("test-pack", "new content")

    def test_format_version_parsed_with_default(self, multi_skill_pack, stimpacks_dir):
        # No format field -> current version
        info = sp._parse_stimpack_dir(multi_skill_pack)
        assert info.manifest.format == sp.STIMPACK_FORMAT_VERSION

        # A pack from the future still loads (best-effort), carrying its format
        future = stimpacks_dir / "future-pack"
        _write_manifest(future, "future-pack")
        manifest = json.loads((future / "stimpack.json").read_text())
        manifest["format"] = sp.STIMPACK_FORMAT_VERSION + 1
        (future / "stimpack.json").write_text(json.dumps(manifest))
        _write_skill(future, "solo", "name: solo\ndescription: Solo skill", "Solo body")
        info = sp._parse_stimpack_dir(future)
        assert info is not None
        assert info.manifest.format == sp.STIMPACK_FORMAT_VERSION + 1
        assert len(info.skills) == 1


# =============================================================================
# Validator
# =============================================================================

class TestValidator:
    def test_valid_pack_passes(self, multi_skill_pack):
        from agent.v2.stimpack_validate import validate_pack
        report, warnings, errors = validate_pack(multi_skill_pack)
        assert errors == []
        assert any("test-pack" in line for line in report)

    def test_catches_bad_provides_and_empty_body(self, stimpacks_dir):
        from agent.v2.stimpack_validate import validate_pack
        pack = stimpacks_dir / "broken-pack"
        _write_manifest(pack, "broken-pack")
        _write_skill(
            pack, "ghost-lib",
            "name: ghost-lib\ndescription: Claims a lib it lacks\nprovides:\n  - missing_module",
            "Some body",
        )
        _write_skill(pack, "empty", "name: empty\ndescription: No body", "   ")
        report, warnings, errors = validate_pack(pack)
        assert any("missing_module" in e for e in errors)
        assert any("no body" in e for e in errors)

    def test_flags_shadowed_root_skill_and_unknown_env(self, stimpacks_dir):
        from agent.v2.stimpack_validate import validate_pack
        pack = stimpacks_dir / "warn-pack"
        _write_manifest(pack, "warn-pack")
        _write_skill(
            pack, "odd",
            "name: odd\ndescription: Unknown env key\nenvironments:\n  chat: true\n  toolview: true",
            "Body",
        )
        (pack / "SKILL.md").write_text("---\nname: warn-pack\n---\n\nDead root", encoding="utf-8")
        report, warnings, errors = validate_pack(pack)
        assert errors == []
        assert any("IGNORED" in w for w in warnings)
        assert any("toolview" in w for w in warnings)


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


# =============================================================================
# Filesystem authoring: skills/ mount + list shows paths and problems
# =============================================================================

from agent.v2.tools._workspace_files import (
    SKILLS_MOUNT,
    ensure_skills_mount,
    resolve_workspace_path,
    workspace_relative,
)


@pytest.fixture
def workspace(tmp_path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def dev_pack(stimpacks_dir, tmp_path, monkeypatch) -> Path:
    """A single-skill pack served from the dev override dir (read-only)."""
    dev = tmp_path / "dev-packs"
    pack = dev / "dev-pack"
    pack.mkdir(parents=True)
    (pack / "SKILL.md").write_text(
        "---\nname: dev-pack\ndisplay_name: Dev Pack\ndescription: From the dev repo\n---\n\nDev body",
        encoding="utf-8",
    )
    monkeypatch.setattr(sp, "_dev_stimpacks_dir", lambda: dev)
    return pack


class TestSkillsMount:
    def test_mount_symlinks_profile_stimpacks_dir(self, stimpacks_dir, workspace):
        ensure_skills_mount(workspace)
        link = workspace / SKILLS_MOUNT
        assert link.is_symlink() and link.resolve() == stimpacks_dir.resolve()
        # Idempotent, and re-pointed if the target changes.
        ensure_skills_mount(workspace)
        assert link.resolve() == stimpacks_dir.resolve()

    def test_mount_leaves_a_real_skills_dir_alone(self, stimpacks_dir, workspace):
        (workspace / SKILLS_MOUNT).mkdir()
        ensure_skills_mount(workspace)
        assert not (workspace / SKILLS_MOUNT).is_symlink()

    def test_resolve_maps_skills_prefix_with_and_without_symlink(self, stimpacks_dir, workspace):
        # No symlink: prefix maps straight to the stimpacks dir.
        resolved, err = resolve_workspace_path(str(workspace), "skills/foo/SKILL.md")
        assert err is None and resolved == (stimpacks_dir / "foo" / "SKILL.md").resolve()
        # With symlink: same answer, via the link.
        ensure_skills_mount(workspace)
        resolved, err = resolve_workspace_path(str(workspace), "skills/foo/SKILL.md")
        assert err is None and resolved == (stimpacks_dir / "foo" / "SKILL.md").resolve()
        assert workspace_relative(workspace.resolve(), resolved) == "skills/foo/SKILL.md"
        # Traversal is still rejected; the workspace itself still works.
        _, err = resolve_workspace_path(str(workspace), "skills/../secret")
        assert err
        resolved, err = resolve_workspace_path(str(workspace), "out.png")
        assert err is None and resolved == (workspace / "out.png").resolve()

    @pytest.mark.asyncio
    async def test_write_read_glob_grep_through_mount(self, stimpacks_dir, workspace, session, test_chat):
        from agent.v2.tools.write_file import write_file
        from agent.v2.tools.read_file import read_file
        from agent.v2.tools.glob_files import glob_files
        from agent.v2.tools.grep_files import grep_files
        from agent.v2.tools.skill import skill_tool
        ensure_skills_mount(workspace)
        ws = str(workspace)
        body = (
            "---\nname: product-photo\ndisplay_name: Product Photo\n"
            "description: Consistent product shots on white\nauthor: agent\n"
            "provides: [photo_utils]\n---\n\n# Product Photo\n\nUse soft light."
        )
        res = await write_file(file_path="skills/product-photo/SKILL.md", content=body, workspace_dir=ws, session=session, chat_id=test_chat.id)
        assert not res.startswith("Error"), res
        res = await write_file(file_path="skills/product-photo/lib/photo_utils.py", content="def pad(x):\n    return x * 1.2\n", workspace_dir=ws, session=session, chat_id=test_chat.id)
        assert not res.startswith("Error"), res
        assert (stimpacks_dir / "product-photo" / "SKILL.md").read_text(encoding="utf-8") == body

        read = await read_file(file_path="skills/product-photo/SKILL.md", workspace_dir=ws)
        assert "Use soft light." in read
        listed = await glob_files(pattern="skills/*/SKILL.md", workspace_dir=ws)
        assert listed == "skills/product-photo/SKILL.md"
        grepped = await grep_files(pattern="soft light", path="skills", workspace_dir=ws, output_mode="files_with_matches")
        assert "skills/product-photo/SKILL.md" in grepped

        # The loader sees it live: listed with its path, invokable, lib importable.
        result = await skill_tool(action="list", session=session, chat_id=test_chat.id)
        assert "| product-photo | Consistent product shots on white | chat | Product Photo | skills/product-photo/SKILL.md | yours |" in result
        assert "Problems:" not in result
        injected = []
        assert await skill_tool(action="invoke", name="product-photo", session=session, chat_id=test_chat.id, _injected_messages=injected) == "Loaded skill 'Product Photo'."
        assert injected[0]["content"].endswith("Use soft light.")
        assert "photo_utils" in get_stimpack_lib_modules(["product-photo"])

    @pytest.mark.asyncio
    async def test_list_reports_loader_problems(self, stimpacks_dir, dev_pack, session, test_chat):
        from agent.v2.tools.skill import skill_tool
        broken = stimpacks_dir / "broken"
        broken.mkdir()
        (broken / "SKILL.md").write_text("---\nname: broken\ndescription: \nprovides: [nope]\n---\n\nbody", encoding="utf-8")
        (stimpacks_dir / "empty-dir").mkdir()
        result = await skill_tool(action="list", session=session, chat_id=test_chat.id)
        assert "| dev-pack | From the dev repo | chat | Dev Pack | (dev repo, read-only) | dev repo, read-only |" in result
        assert "Problems:" in result
        assert "broken: " in result and "nope" in result
        assert "skills/empty-dir/: not loaded" in result


# =============================================================================
# Precedence: local forks shadow marketplace skills; marketplace is read-only
# =============================================================================

from agent.v2.stimpacks import shadowed_skills
from agent.v2.tools._workspace_files import readonly_workspace_error


def _write_sidecar(pack_dir: Path, name: str) -> None:
    (pack_dir / ".marketplace.json").write_text(json.dumps({
        "stimpackId": "sp_1", "name": name, "version": "1", "versionId": "v_1",
    }), encoding="utf-8")


@pytest.fixture
def marketplace_pack(stimpacks_dir) -> Path:
    """A marketplace-installed two-skill pack (has a sidecar)."""
    pack = stimpacks_dir / "essentials"
    _write_manifest(pack, "essentials")
    _write_skill(
        pack, "variations",
        "name: variations\ndisplay_name: Variations\ndescription: Upstream variations\n"
        "environments:\n  chat: true\n  tool: true",
        "Upstream body",
    )
    _write_skill(pack, "grids", "name: grids\ndescription: Upstream grids", "Grid body")
    _write_sidecar(pack, "essentials")
    return pack


def _write_fork(stimpacks_dir: Path, slug: str, frontmatter: str, body: str) -> Path:
    d = stimpacks_dir / slug
    d.mkdir()
    (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return d


class TestForkPrecedence:
    def test_local_fork_shadows_marketplace_skill_everywhere(self, stimpacks_dir, marketplace_pack):
        _write_fork(
            stimpacks_dir, "variations",
            "name: variations\ndisplay_name: My Variations\ndescription: My variations\nauthor: user\n"
            "environments:\n  chat: true\n  tool: true",
            "Fork body",
        )
        names = [s.qualified_name for s in list_skills()]
        assert "variations" in names and "essentials/variations" not in names
        assert "essentials/grids" in names
        fork = next(s for s in list_skills() if s.slug == "variations")
        assert fork.overrides == "essentials/variations" and fork.is_local
        # Both names resolve to the fork; lib lookups follow.
        assert find_skill("variations")[1].pack_name == "variations"
        assert find_skill("essentials/variations")[1].pack_name == "variations"
        assert [(o.qualified_name, f.qualified_name) for o, f in shadowed_skills()] == [("essentials/variations", "variations")]
        # Reminder labels the fork as yours and omits the original.
        reminder = build_skills_reminder(list_skills(), set(), environment="chat")
        assert "- variations: My variations [yours, overrides essentials/variations]" in reminder
        assert "essentials/variations" not in reminder.replace("overrides essentials/variations", "")

    @pytest.mark.asyncio
    async def test_two_local_skills_with_one_slug_both_stay_visible_and_are_flagged(
        self, stimpacks_dir, multi_skill_pack, session, test_chat
    ):
        from agent.v2.tools.skill import skill_tool
        _write_fork(stimpacks_dir, "alpha", "name: alpha\ndescription: Local alpha", "Local alpha body")
        # No fork semantics between two locals: both visible, qualified names still distinct.
        assert len([s for s in list_skills() if s.slug == "alpha"]) == 2
        assert find_skill("test-pack/alpha")[1].pack_name == "test-pack"
        # A single-skill pack's qualified name *is* its bare slug, so that exact match wins.
        assert find_skill("alpha")[1].pack_name == "alpha"
        result = await skill_tool(action="list", session=session, chat_id=test_chat.id)
        assert "'alpha' and 'test-pack/alpha' both claim the name 'alpha'" in result

    def test_marketplace_pack_is_readonly_to_write_and_edit_tools(self, stimpacks_dir, marketplace_pack):
        err = readonly_workspace_error("skills/essentials/skills/variations/SKILL.md")
        assert err and "marketplace-installed" in err and "skills/<slug>/" in err
        assert readonly_workspace_error("skills/variations/SKILL.md") is None
        assert readonly_workspace_error("out.png") is None

    @pytest.mark.asyncio
    async def test_write_tools_refuse_marketplace_and_allow_fork(self, stimpacks_dir, marketplace_pack, workspace, session, test_chat):
        from agent.v2.tools.write_file import write_file
        from agent.v2.tools.edit_file import edit_file
        ws = str(workspace)
        res = await write_file(file_path="skills/essentials/skills/variations/SKILL.md", content="x", workspace_dir=ws, session=session, chat_id=test_chat.id)
        assert res.startswith("Error") and "fork" in res.lower()
        res = await edit_file(file_path="skills/essentials/skills/variations/SKILL.md", old_string="Upstream", new_string="x", workspace_dir=ws, session=session, chat_id=test_chat.id)
        assert res.startswith("Error")
        assert (marketplace_pack / "skills" / "variations" / "SKILL.md").read_text(encoding="utf-8").endswith("Upstream body")
        res = await write_file(
            file_path="skills/variations/SKILL.md",
            content="---\nname: variations\ndescription: Mine\nauthor: agent\nenvironments:\n  chat: true\n---\n\nFork body",
            workspace_dir=ws, session=session, chat_id=test_chat.id,
        )
        assert not res.startswith("Error"), res
        assert find_skill("essentials/variations")[1].pack_name == "variations"

    @pytest.mark.asyncio
    async def test_list_and_invoke_label_forks_and_flag_narrower_surface(self, stimpacks_dir, marketplace_pack, session, test_chat):
        from agent.v2.tools.skill import skill_tool
        # Fork drops the tool surface the original had.
        _write_fork(stimpacks_dir, "variations", "name: variations\ndisplay_name: My Variations\ndescription: Mine\nauthor: agent", "Fork body")
        result = await skill_tool(action="list", session=session, chat_id=test_chat.id)
        assert "| variations | Mine | chat | My Variations | skills/variations/SKILL.md | yours, overrides essentials/variations |" in result
        assert "| essentials/grids |" in result and "marketplace, read-only — fork to skills/grids/" in result
        assert "| essentials/variations |" not in result
        assert "Hidden by your forks: essentials/variations → variations" in result
        assert "not offered in tool (the original was)" in result
        injected = []
        assert await skill_tool(action="invoke", name="essentials/variations", session=session, chat_id=test_chat.id, _injected_messages=injected) == "Loaded skill 'My Variations'."
        assert injected[0]["content"] == "## Skill: My Variations (your version, overrides essentials/variations)\n\nFork body"
        assert injected[0]["skill_name"] == "variations"


class TestSkillLookupWithoutPackAliases:
    def test_single_skill_uses_skill_names_not_pack_alias(self, stimpacks_dir):
        pack = stimpacks_dir / "original"
        _write_manifest(pack, "original")
        _write_skill(pack, "example", "name: example\ndescription: Original", "Original body")
        assert load_skill("original/example").content == "Original body"
        assert load_skill("example").content == "Original body"
        assert find_skill("original") is None
        _write_sidecar(pack, "original")
        _write_fork(stimpacks_dir, "example", "name: example\ndescription: Fork", "Fork body")
        assert load_skill("original/example").content == "Fork body"
        assert load_skill("example").content == "Fork body"
        assert find_skill("original") is None


class TestSkillsPathAliases:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mounted", [False, True])
    @pytest.mark.parametrize("prefix", ["skills/./", "skills//", "./skills/", "skills/alias/../"])
    async def test_marketplace_aliases_cannot_be_written(
        self, stimpacks_dir, marketplace_pack, workspace, mounted, prefix
    ):
        from agent.v2.tools.write_file import write_file
        from agent.v2.tools.edit_file import edit_file
        from agent.v2.tools.browse_web import _download
        if mounted:
            ensure_skills_mount(workspace)
        path = prefix + "essentials/skills/variations/SKILL.md"
        original = (marketplace_pack / "skills/variations/SKILL.md").read_text()
        assert (await write_file(file_path=path, content="changed", workspace_dir=str(workspace))).startswith("Error")
        assert (await edit_file(file_path=path, old_string="Upstream", new_string="changed", workspace_dir=str(workspace))).startswith("Error")
        # Rejected before any network request.
        assert (await _download("https://example.invalid/skill", path, str(workspace))).startswith("Error")
        assert (marketplace_pack / "skills/variations/SKILL.md").read_text() == original

    @pytest.mark.asyncio
    async def test_symlink_alias_cannot_write_marketplace(self, stimpacks_dir, marketplace_pack, workspace):
        from agent.v2.tools.write_file import write_file
        alias = workspace / "upstream"
        try:
            alias.symlink_to(marketplace_pack, target_is_directory=True)
        except OSError:
            pytest.skip("Symlink creation unavailable")
        result = await write_file(file_path="upstream/skills/variations/SKILL.md", content="changed", workspace_dir=str(workspace))
        assert "marketplace-installed" in result
        assert (marketplace_pack / "skills/variations/SKILL.md").read_text().endswith("Upstream body")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mounted", [False, True])
    async def test_glob_and_read_agree_with_or_without_mount(self, stimpacks_dir, single_skill_pack, workspace, mounted):
        from agent.v2.tools.glob_files import glob_files
        from agent.v2.tools.read_file import read_file
        if mounted:
            ensure_skills_mount(workspace)
        for pattern, path in [("skills/*/SKILL.md", None), ("./skills/*/SKILL.md", "."), ("*/SKILL.md", "./skills")]:
            result = await glob_files(pattern=pattern, path=path, workspace_dir=str(workspace))
            assert result == "skills/single-pack/SKILL.md"
            assert "Single body" in await read_file(file_path=result, workspace_dir=str(workspace))
        assert "must not contain" in await glob_files(pattern="skills/../*", workspace_dir=str(workspace))
