"""Stimpack index, loading, and saving.

A **stimpack** is the installable PACKAGE / marketplace unit. A **skill** is
one targeted agent capability inside it — the unit the agent discovers and
invokes, flat across packs. A stimpack holds one or more skills:

    stimpacks/
        my-stimpack/
            stimpack.json       # manifest: PACK identity (name, version, ...)
            skills/
                <skill-slug>/
                    SKILL.md    # frontmatter (incl. `environments`) + body
                    lib/        # optional Python modules for run_code
            .marketplace.json   # optional — tracks marketplace origin

Skills are **discovered** by scanning ``skills/*/SKILL.md``; targeting lives in
each skill's frontmatter (`environments:`), not the manifest. A legacy pack
with a root ``SKILL.md`` (with or without a manifest) still loads as a
single-skill stimpack — that's the format ``save_stimpack`` (user/agent
authoring) writes.

Resource types (manifest ``resources[].type``):
    skill            -> legacy root SKILL.md declaration. FULLY WIRED.
    tool | flow | asset | model | flow_guidance
                     -> manifest schema + a lander interface are defined, but
                        the landers are stubs that log "recognized, not yet
                        loaded" until they are wired up.

Stimpacks come from two sources:
- **Local**: created by the user or agent directly on disk
- **Marketplace**: installed from stimma.ai/stimpacks, tracked via .marketplace.json
"""

import json
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from app_dirs import get_data_dir, get_profile_dir
from core.logging import get_logger
from core.profile_context import get_current_profile

log = get_logger(__name__)

SKILL_FILENAME = "SKILL.md"  # the `skill` resource document (resource type name, not the package)
SKILLS_DIRNAME = "skills"  # multi-skill layout: <pack>/skills/<slug>/SKILL.md
STIMPACK_MANIFEST = "stimpack.json"

# Container-format version this loader understands (`format` in stimpack.json;
# absent = 1). Bump when the on-disk contract changes incompatibly; newer packs
# still best-effort load with a warning so an old app degrades, not breaks.
STIMPACK_FORMAT_VERSION = 1
MARKETPLACE_SIDECAR = ".marketplace.json"
AUTO_INSTALL_STATE_FILE = ".marketplace-auto-install-state.json"

# Resource types a stimpack manifest may declare. Only `skill` is fully wired;
# the rest have a manifest schema + a (stub) lander so the framework is in place.
RESOURCE_TYPE_SKILL = "skill"
KNOWN_RESOURCE_TYPES = (
    RESOURCE_TYPE_SKILL,
    "tool",
    "flow",
    "asset",
    "model",
    "flow_guidance",
)


def _title_case_from_slug(slug: str) -> str:
    """Convert a slug like 'batch-variations' to 'Batch Variations'."""
    return slug.replace("-", " ").replace("_", " ").title()


# ---------------------------------------------------------------------------
# Manifest model
# ---------------------------------------------------------------------------

@dataclass
class StimpackResource:
    """One typed resource declared by a stimpack manifest.

    ``spec`` carries the raw, type-specific manifest entry (e.g. ``path`` for a
    skill, an ``id`` for a tool/model, etc.) so landers can read whatever fields
    their type defines without the dataclass having to know them all.
    """
    type: str
    spec: dict = field(default_factory=dict)

    @property
    def path(self) -> Optional[str]:
        """Relative path within the stimpack dir for file-backed resources."""
        return self.spec.get("path")


@dataclass
class StimpackManifest:
    """Parsed ``stimpack.json`` (or a manifest derived from a bare SKILL.md)."""
    name: str
    display_name: str
    description: str
    version: str
    author: str
    tags: list[str]
    format: int = STIMPACK_FORMAT_VERSION  # container-format version
    resources: list[StimpackResource] = field(default_factory=list)

    def resources_of_type(self, resource_type: str) -> list[StimpackResource]:
        return [r for r in self.resources if r.type == resource_type]

    @property
    def resource_types(self) -> list[str]:
        return [r.type for r in self.resources]


@dataclass
class SkillEnvironments:
    """Per-skill eligibility (`environments:` frontmatter block).

    Opt-in: an absent key means the skill is not offered in that environment.
    An absent block entirely defaults to chat-only, so a skill never silently
    does nothing; flow/tool stay strict opt-in.

    ``tool`` is ``True`` (every tool) or scoped via ``tool_task_types``
    (``tool: { task_types: [...] }`` in frontmatter).
    """
    chat: bool = False
    flow: bool = False
    tool: bool = False
    tool_task_types: Optional[list[str]] = None  # None = all task types (when tool=True)

    def eligible_for_tool(self, task_types: list[str] | None) -> bool:
        """True if this skill applies to a tool with the given task types."""
        if not self.tool:
            return False
        if self.tool_task_types is None:
            return True
        return bool(set(self.tool_task_types) & set(task_types or []))

    def to_dict(self) -> dict:
        tool: bool | dict = self.tool
        if self.tool and self.tool_task_types is not None:
            tool = {"task_types": list(self.tool_task_types)}
        return {"chat": self.chat, "flow": self.flow, "tool": tool}


def _parse_environments(fm: dict) -> SkillEnvironments:
    """Parse the `environments:` frontmatter block (absent block => chat only)."""
    env = fm.get("environments")
    if not isinstance(env, dict):
        return SkillEnvironments(chat=True)
    tool_raw = env.get("tool", False)
    tool = False
    tool_task_types: Optional[list[str]] = None
    if isinstance(tool_raw, dict):
        raw_types = tool_raw.get("task_types")
        if isinstance(raw_types, list) and raw_types:
            tool = True
            tool_task_types = [str(t) for t in raw_types]
    elif tool_raw:
        tool = True
    return SkillEnvironments(
        chat=bool(env.get("chat", False)),
        flow=bool(env.get("flow", False)),
        tool=tool,
        tool_task_types=tool_task_types,
    )


@dataclass
class SkillInfo:
    """One skill inside a stimpack — the flat unit the agent discovers/invokes."""
    slug: str  # skill directory name (or frontmatter name for legacy root skills)
    display_name: str
    description: str
    environments: SkillEnvironments
    provides: list[str]  # importable lib/ modules advertised in frontmatter
    skill_md: Path  # absolute path to this skill's SKILL.md
    dir_path: Path  # this skill's directory (contains SKILL.md + optional lib/)
    pack_name: str
    pack_display_name: str

    @property
    def qualified_name(self) -> str:
        """Pack-qualified identity (collision-safe across packs).

        Collapses to the bare slug for legacy single-skill packs where the
        skill is named after its pack.
        """
        if self.slug == self.pack_name:
            return self.slug
        return f"{self.pack_name}/{self.slug}"


@dataclass
class MarketplaceMeta:
    """Metadata from .marketplace.json sidecar file."""
    stimpack_id: str
    name: str
    version: int
    version_id: str
    installed_at: str
    author: str
    author_avatar_key: str = ""


@dataclass
class StimpackInfo:
    name: str
    display_name: str
    description: str
    author: str  # "user" | "agent" | "marketplace"
    tags: list[str]
    path: Path  # the stimpack's primary file (stimpack.json if present, else SKILL.md)
    dir_path: Path  # the stimpack's directory
    tier: str  # "local" | "marketplace"
    manifest: StimpackManifest
    skills: list[SkillInfo] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)  # union of skills' provides
    marketplace: Optional[MarketplaceMeta] = None
    is_dev: bool = False  # Loaded from the dev_stimpacks_dir override (shadows profile copy)

    @property
    def dir(self) -> Path:
        """The stimpack's directory."""
        return self.dir_path

    @property
    def is_marketplace(self) -> bool:
        """True if installed from marketplace and not locally modified."""
        return self.marketplace is not None

    @property
    def skill_md_path(self) -> Optional[Path]:
        """Absolute path to the first skill's SKILL.md, if any (legacy convenience)."""
        return self.skills[0].skill_md if self.skills else None


@dataclass
class StimpackContent:
    info: StimpackInfo
    content: str  # the first skill's markdown body (without frontmatter)


@dataclass
class SkillContent:
    """A loaded skill: its info, owning pack, and markdown body."""
    skill: SkillInfo
    pack: StimpackInfo
    content: str  # markdown body (without frontmatter)


# ---------------------------------------------------------------------------
# Resource landers
#
# A lander knows how to "land" (activate) one resource type when a stimpack is
# invoked. Only the skill lander is fully wired; the others are stubs so the
# framework + registry exist and new resource types can be added incrementally.
# ---------------------------------------------------------------------------

@dataclass
class LanderResult:
    """What a lander contributes when its resource is activated."""
    injection: Optional[str] = None  # markdown to inject into the conversation (skill)
    lib_modules: dict[str, Path] = field(default_factory=dict)  # {module: lib_dir} (skill)
    note: Optional[str] = None  # human-readable status (stub landers)


class ResourceLander(ABC):
    """Interface for activating a stimpack resource of a given type."""

    type: str = ""

    @abstractmethod
    def load(self, info: "StimpackInfo", resource: "StimpackResource") -> LanderResult:
        ...


def _skill_lib_modules(skill_dir: Path) -> dict[str, Path]:
    """Importable modules from a skill's lib/ directory.

    Each top-level package (dir with __init__.py) or module (.py file)
    directly inside lib/ becomes importable in run_code.
    """
    lib_dir = skill_dir / "lib"
    if not lib_dir.is_dir():
        return {}
    module_paths: dict[str, Path] = {}
    for child in lib_dir.iterdir():
        if child.is_dir() and (child / "__init__.py").exists():
            module_paths[child.name] = lib_dir
        elif child.is_file() and child.suffix == ".py" and child.stem != "__init__":
            module_paths[child.stem] = lib_dir
    return module_paths


def _read_skill_body(skill_md: Path) -> Optional[str]:
    """Read a SKILL.md and return its markdown body (frontmatter stripped)."""
    if not skill_md.is_file():
        return None
    try:
        text = skill_md.read_text(encoding="utf-8")
        _, body = _parse_frontmatter(text, skill_md)
        return body
    except Exception as e:  # pragma: no cover - defensive
        log.warning(f"Failed to read skill {skill_md}: {e}")
        return None


class SkillLander(ResourceLander):
    """Fully-wired lander for the `skill` resource: inject SKILL.md + lib/ modules."""

    type = RESOURCE_TYPE_SKILL

    def load(self, info: "StimpackInfo", resource: "StimpackResource") -> LanderResult:
        skill_md = info.dir_path / (resource.path or SKILL_FILENAME)
        injection = _read_skill_body(skill_md)
        return LanderResult(
            injection=injection, lib_modules=_skill_lib_modules(skill_md.parent)
        )

    def load_skill(self, skill: "SkillInfo") -> LanderResult:
        """Land one skill: its SKILL.md body + its lib/ modules."""
        return LanderResult(
            injection=_read_skill_body(skill.skill_md),
            lib_modules=_skill_lib_modules(skill.dir_path),
        )


class _StubLander(ResourceLander):
    """Placeholder lander: recognizes a resource type but does not load it yet."""

    def __init__(self, resource_type: str):
        self.type = resource_type

    def load(self, info: "StimpackInfo", resource: "StimpackResource") -> LanderResult:
        note = f"'{self.type}' resource in stimpack '{info.name}' recognized, not yet loaded"
        log.info(note)
        return LanderResult(note=note)


_LANDERS: dict[str, ResourceLander] = {}


def register_lander(lander: ResourceLander) -> None:
    _LANDERS[lander.type] = lander


def get_lander(resource_type: str) -> Optional[ResourceLander]:
    return _LANDERS.get(resource_type)


# Register the skill lander (wired) + stubs for the remaining known types.
register_lander(SkillLander())
for _t in KNOWN_RESOURCE_TYPES:
    if _t != RESOURCE_TYPE_SKILL:
        register_lander(_StubLander(_t))


# Module-level cache keyed by profile_id
_cache: dict[str, list[StimpackInfo]] = {}


def _invalidate_cache(profile_id: Optional[str] = None) -> None:
    global _cache
    if profile_id:
        _cache.pop(profile_id, None)
    else:
        _cache.clear()


def get_user_stimpacks_dir(profile_id: Optional[str] = None) -> Path:
    if not profile_id:
        profile_id = get_current_profile()
    d = get_profile_dir(profile_id=profile_id) / "stimpacks"
    d.mkdir(parents=True, exist_ok=True)
    # One-time migration: move contents from the old per-profile skills/ dir
    _maybe_migrate_from_skills_dir(d)
    return d


def get_stimpack_assets_dir(name: str, profile_id: Optional[str] = None) -> Path:
    """Return the assets directory for a stimpack (its own directory)."""
    if not profile_id:
        profile_id = get_current_profile()
    # Assets live alongside the manifest/SKILL.md in the stimpack's directory
    d = get_user_stimpacks_dir(profile_id) / _slugify(name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _iter_stimpack_dirs(base_dir: Path):
    """Yield stimpack directories (dirs containing a manifest or a SKILL.md)."""
    if not base_dir.is_dir():
        return
    for child in sorted(base_dir.iterdir()):
        if child.is_dir() and (
            (child / STIMPACK_MANIFEST).is_file() or (child / SKILL_FILENAME).is_file()
        ):
            yield child


_dev_dir_logged: Optional[str] = None


def _dev_stimpacks_dir() -> Optional[Path]:
    """Return the configured dev stimpacks override directory, if set and present.

    When configured (`dev_stimpacks_dir`), stimpacks here are the authority for
    built-in stimpacks: they shadow same-named stimpacks in the profile dir, so
    editing the stimma-skills repo is picked up live with no publish/install
    round trip.
    """
    global _dev_dir_logged
    try:
        from config import get_settings
        raw = get_settings().dev_stimpacks_dir
    except Exception:
        return None
    if not raw:
        return None
    p = Path(os.path.expanduser(raw))
    if not p.is_dir():
        if _dev_dir_logged != str(p):
            log.warning(f"dev_stimpacks_dir is set but not a directory: {p}")
            _dev_dir_logged = str(p)
        return None
    if _dev_dir_logged != str(p):
        log.info(f"dev stimpacks override active: {p} (shadows profile stimpacks by name)")
        _dev_dir_logged = str(p)
        _track_dev_stimpacks_enabled(p)
    return p


def _track_dev_stimpacks_enabled(dev_dir: Path) -> None:
    """Emit dev_stimpacks_enabled {stimpackCount} on the configuration *transition*.

    A state file remembers the last-seen dev dir so per-launch re-detection
    doesn't re-fire (per-launch state is session_started.stimpackCounts.dev).
    Count only — nothing identifying.
    """
    try:
        import app_dirs
        state_path = app_dirs.get_data_dir() / "dev_stimpacks_state"
        previous = state_path.read_text(encoding="utf-8").strip() if state_path.exists() else ""
        current = str(dev_dir)
        if previous == current:
            return
        state_path.write_text(current, encoding="utf-8")
        stimpack_count = sum(1 for _ in _iter_stimpack_dirs(dev_dir))
        from telemetry import get_telemetry_client
        get_telemetry_client().track(
            "dev_stimpacks_enabled", {"stimpackCount": stimpack_count}, category="stimpacks"
        )
    except Exception:
        pass


def _iter_effective_stimpack_dirs(profile_id: str):
    """Yield (stimpack_dir, is_dev) for all stimpack dirs, dev override first.

    Dev stimpacks are yielded before profile stimpacks, so callers that resolve
    by name (load_stimpack, package_stimpack_as_zip) naturally prefer the dev
    copy. Shadowing is by stimpack *name* rather than directory name —
    list_installed_stimpacks dedupes by name, keeping the dev copy — because a
    stimpack's directory name may differ from its manifest name.
    """
    dev_dir = _dev_stimpacks_dir()
    if dev_dir:
        for p in _iter_stimpack_dirs(dev_dir):
            yield p, True
    for p in _iter_stimpack_dirs(get_user_stimpacks_dir(profile_id)):
        yield p, False


def _maybe_migrate_from_skills_dir(profile_stimpacks_dir: Path) -> None:
    """One-time migration: move an old per-profile skills/ dir into stimpacks/.

    Earlier builds stored installable packages under <profile>/skills/. If the
    new stimpacks/ dir is empty and a populated skills/ dir exists alongside it,
    move the package directories over so installs survive the rename.
    """
    try:
        if any(_iter_stimpack_dirs(profile_stimpacks_dir)):
            return  # already has stimpacks
        legacy = profile_stimpacks_dir.parent / "skills"
        if not legacy.is_dir():
            return
        moved = 0
        for child in legacy.iterdir():
            dest = profile_stimpacks_dir / child.name
            if dest.exists():
                continue
            shutil.move(str(child), str(dest))
            moved += 1
        if moved:
            log.info(f"Migrated {moved} package(s) from {legacy} to {profile_stimpacks_dir}")
    except Exception as e:  # pragma: no cover - defensive
        log.warning(f"Stimpack dir migration skipped: {e}")


def _slugify(name: str) -> str:
    """Convert a stimpack name to a safe filename slug."""
    # Normalize unicode, lowercase, replace non-alphanum with hyphens
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    s = re.sub(r"[-\s]+", "-", s)
    return s or "stimpack"


def _parse_frontmatter(text: str, path: Path) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text.

    Returns (metadata_dict, body_without_frontmatter).
    Falls back to directory-name-based metadata if malformed.
    """
    # Use parent dir name as fallback (since the file is typically SKILL.md)
    fallback_name = path.parent.name if path.name == SKILL_FILENAME else path.stem

    if not text.startswith("---"):
        return {"name": fallback_name}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"name": fallback_name}, text

    try:
        meta = yaml.safe_load(parts[1])
        if not isinstance(meta, dict):
            meta = {"name": fallback_name}
    except yaml.YAMLError:
        meta = {"name": fallback_name}

    body = parts[2].lstrip("\n")
    return meta, body


# ---------------------------------------------------------------------------
# Manifest loading / derivation
# ---------------------------------------------------------------------------

def _build_resources(raw_resources: list) -> list[StimpackResource]:
    resources: list[StimpackResource] = []
    for entry in raw_resources or []:
        if not isinstance(entry, dict):
            continue
        rtype = entry.get("type")
        if not rtype:
            continue
        if rtype not in KNOWN_RESOURCE_TYPES:
            log.warning(f"Unknown stimpack resource type '{rtype}' — ignoring")
            continue
        resources.append(StimpackResource(type=rtype, spec=entry))
    return resources


def _parse_manifest(manifest_path: Path, stimpack_dir: Path) -> Optional[StimpackManifest]:
    """Parse a stimpack.json manifest, filling defaults from a skill resource."""
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"Failed to read stimpack manifest {manifest_path}: {e}")
        return None
    if not isinstance(data, dict):
        log.warning(f"Stimpack manifest {manifest_path} is not an object")
        return None

    resources = _build_resources(data.get("resources", []))
    # A manifest with no declared resources but a SKILL.md present still gets a
    # skill resource so the pack is usable.
    if not resources and (stimpack_dir / SKILL_FILENAME).is_file():
        resources = [StimpackResource(type=RESOURCE_TYPE_SKILL, spec={"type": RESOURCE_TYPE_SKILL, "path": SKILL_FILENAME})]

    try:
        pack_format = int(data.get("format", STIMPACK_FORMAT_VERSION))
    except (TypeError, ValueError):
        pack_format = STIMPACK_FORMAT_VERSION
    if pack_format > STIMPACK_FORMAT_VERSION:
        log.warning(
            f"Stimpack {manifest_path} declares format {pack_format}, newer than the "
            f"supported {STIMPACK_FORMAT_VERSION} — loading best-effort; consider updating Stimma"
        )

    name = data.get("name") or stimpack_dir.name
    # Fall back to skill-resource frontmatter for human-facing metadata.
    fm: dict = {}
    skill_res = next((r for r in resources if r.type == RESOURCE_TYPE_SKILL), None)
    if skill_res is not None:
        skill_md = stimpack_dir / (skill_res.path or SKILL_FILENAME)
        if skill_md.is_file():
            try:
                fm, _ = _parse_frontmatter(skill_md.read_text(encoding="utf-8"), skill_md)
            except Exception:
                fm = {}

    return StimpackManifest(
        name=name,
        display_name=data.get("display_name") or fm.get("display_name") or _title_case_from_slug(name),
        description=data.get("description") or fm.get("description", ""),
        version=str(data.get("version", "1")),
        author=data.get("author") or fm.get("author", ""),
        tags=data.get("tags") or fm.get("tags", []) or [],
        format=pack_format,
        resources=resources,
    )


def _derive_manifest_from_skill_md(skill_md: Path, stimpack_dir: Path) -> StimpackManifest:
    """Derive a default single-`skill` manifest from a bare SKILL.md."""
    try:
        fm, _ = _parse_frontmatter(skill_md.read_text(encoding="utf-8"), skill_md)
    except Exception:
        fm = {}
    name = fm.get("name", stimpack_dir.name)
    return StimpackManifest(
        name=name,
        display_name=fm.get("display_name", _title_case_from_slug(name)),
        description=fm.get("description", ""),
        version=str(fm.get("version", "1")),
        author=fm.get("author", ""),
        tags=fm.get("tags", []) or [],
        resources=[StimpackResource(type=RESOURCE_TYPE_SKILL, spec={"type": RESOURCE_TYPE_SKILL, "path": SKILL_FILENAME})],
    )


def _load_or_derive_manifest(stimpack_dir: Path) -> Optional[StimpackManifest]:
    manifest_path = stimpack_dir / STIMPACK_MANIFEST
    if manifest_path.is_file():
        return _parse_manifest(manifest_path, stimpack_dir)
    skill_md = stimpack_dir / SKILL_FILENAME
    if skill_md.is_file():
        return _derive_manifest_from_skill_md(skill_md, stimpack_dir)
    return None


def _load_marketplace_sidecar(stimpack_dir: Path) -> Optional[MarketplaceMeta]:
    """Load .marketplace.json sidecar if present."""
    sidecar_path = stimpack_dir / MARKETPLACE_SIDECAR
    if not sidecar_path.is_file():
        return None
    try:
        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        return MarketplaceMeta(
            stimpack_id=data["stimpackId"],
            name=data["name"],
            version=data["version"],
            version_id=data["versionId"],
            installed_at=data.get("installedAt", ""),
            author=data.get("author", ""),
            author_avatar_key=data.get("authorAvatarKey", ""),
        )
    except Exception as e:
        log.warning(f"Failed to read marketplace sidecar {sidecar_path}: {e}")
        return None


def write_marketplace_sidecar(
    stimpack_dir: Path,
    stimpack_id: str,
    name: str,
    version: int,
    version_id: str,
    author: str,
    author_avatar_key: str = "",
) -> None:
    """Write .marketplace.json sidecar to a stimpack directory."""
    from datetime import datetime, timezone
    sidecar_path = stimpack_dir / MARKETPLACE_SIDECAR
    data = {
        "stimpackId": stimpack_id,
        "name": name,
        "version": version,
        "versionId": version_id,
        "installedAt": datetime.now(timezone.utc).isoformat(),
        "author": author,
        "authorAvatarKey": author_avatar_key,
    }
    sidecar_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _get_auto_install_state_path(profile_id: Optional[str] = None) -> Path:
    """Return the per-profile state file for marketplace auto-installs."""
    if not profile_id:
        profile_id = get_current_profile()
    return get_profile_dir(profile_id=profile_id) / AUTO_INSTALL_STATE_FILE


def _load_auto_install_state(profile_id: Optional[str] = None) -> dict[str, list[str]]:
    """Load per-profile auto-install state."""
    state_path = _get_auto_install_state_path(profile_id)
    if not state_path.is_file():
        return {"installed": [], "removed": []}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"Failed to read auto-install state {state_path}: {e}")
        return {"installed": [], "removed": []}

    installed = data.get("installed", [])
    removed = data.get("removed", [])
    if not isinstance(installed, list):
        installed = []
    if not isinstance(removed, list):
        removed = []
    return {
        "installed": [str(name) for name in installed],
        "removed": [str(name) for name in removed],
    }


def _write_auto_install_state(state: dict[str, list[str]], profile_id: Optional[str] = None) -> None:
    """Persist per-profile auto-install state."""
    state_path = _get_auto_install_state_path(profile_id)
    normalized = {
        "installed": sorted({str(name) for name in state.get("installed", []) if str(name).strip()}),
        "removed": sorted({str(name) for name in state.get("removed", []) if str(name).strip()}),
    }
    state_path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")


def should_auto_install_stimpack(name: str, profile_id: Optional[str] = None) -> bool:
    """Return True if this profile should still receive the named auto-install stimpack."""
    installed_stimpacks = {s.name for s in list_installed_stimpacks(profile_id=profile_id)}
    if name in installed_stimpacks:
        return False

    state = _load_auto_install_state(profile_id=profile_id)
    if name in state["removed"]:
        return False
    if name in state["installed"]:
        return False
    return True


def record_auto_installed_stimpack(name: str, profile_id: Optional[str] = None) -> None:
    """Record that a marketplace stimpack was auto-installed for this profile."""
    state = _load_auto_install_state(profile_id=profile_id)
    state["installed"] = [n for n in state["installed"] if n != name]
    state["removed"] = [n for n in state["removed"] if n != name]
    state["installed"].append(name)
    _write_auto_install_state(state, profile_id=profile_id)


def record_removed_auto_installed_stimpack(name: str, profile_id: Optional[str] = None) -> None:
    """Record that the user removed a marketplace stimpack that should not be reinstalled."""
    state = _load_auto_install_state(profile_id=profile_id)
    state["removed"] = [n for n in state["removed"] if n != name]
    state["removed"].append(name)
    _write_auto_install_state(state, profile_id=profile_id)


def _parse_skill_dir(
    skill_dir: Path,
    skill_md: Path,
    pack_name: str,
    pack_display_name: str,
    slug: Optional[str] = None,
) -> Optional[SkillInfo]:
    """Parse one skill's SKILL.md into a SkillInfo."""
    try:
        fm, _ = _parse_frontmatter(skill_md.read_text(encoding="utf-8"), skill_md)
    except Exception as e:
        log.warning(f"Failed to parse skill frontmatter {skill_md}: {e}")
        return None
    resolved_slug = slug or fm.get("name") or skill_dir.name
    return SkillInfo(
        slug=str(resolved_slug),
        display_name=fm.get("display_name") or _title_case_from_slug(str(resolved_slug)),
        description=fm.get("description", "") or "",
        environments=_parse_environments(fm),
        provides=fm.get("provides", []) or [],
        skill_md=skill_md,
        dir_path=skill_dir,
        pack_name=pack_name,
        pack_display_name=pack_display_name,
    )


def _discover_skills(stimpack_dir: Path, manifest: StimpackManifest) -> list[SkillInfo]:
    """Discover a pack's skills.

    Primary layout: ``skills/<slug>/SKILL.md`` — one skill per subfolder, slug
    from the folder name. Legacy layout: manifest-declared `skill` resources
    (typically a root SKILL.md), slug from frontmatter name (falling back to
    the pack name so a bare legacy pack keeps its old identity).
    """
    skills: list[SkillInfo] = []
    skills_root = stimpack_dir / SKILLS_DIRNAME
    if skills_root.is_dir():
        for child in sorted(skills_root.iterdir()):
            skill_md = child / SKILL_FILENAME
            if child.is_dir() and skill_md.is_file():
                skill = _parse_skill_dir(
                    child, skill_md, manifest.name, manifest.display_name, slug=child.name
                )
                if skill:
                    skills.append(skill)
    if skills:
        return skills

    # Legacy: manifest-declared skill resources rooted in the pack dir.
    for resource in manifest.resources_of_type(RESOURCE_TYPE_SKILL):
        skill_md = stimpack_dir / (resource.path or SKILL_FILENAME)
        if not skill_md.is_file():
            continue
        skill = _parse_skill_dir(
            skill_md.parent, skill_md, manifest.name, manifest.display_name
        )
        if skill:
            skills.append(skill)
    return skills


def _parse_stimpack_dir(stimpack_dir: Path, is_dev: bool = False) -> Optional[StimpackInfo]:
    """Parse a stimpack directory into StimpackInfo via its (loaded/derived) manifest."""
    manifest = _load_or_derive_manifest(stimpack_dir)
    if manifest is None:
        return None

    marketplace = _load_marketplace_sidecar(stimpack_dir)
    tier = "marketplace" if marketplace else "local"
    author = manifest.author or ("marketplace" if marketplace else "user")

    skills = _discover_skills(stimpack_dir, manifest)

    # `provides` (advertised importable lib modules) is the union across skills.
    provides: list[str] = []
    for skill in skills:
        for module in skill.provides:
            if module not in provides:
                provides.append(module)

    manifest_path = stimpack_dir / STIMPACK_MANIFEST
    primary = manifest_path if manifest_path.is_file() else (stimpack_dir / SKILL_FILENAME)

    return StimpackInfo(
        name=manifest.name,
        display_name=manifest.display_name,
        description=manifest.description,
        author=author,
        tags=manifest.tags,
        path=primary,
        dir_path=stimpack_dir,
        tier=tier,
        manifest=manifest,
        skills=skills,
        provides=provides,
        marketplace=marketplace,
        is_dev=is_dev,
    )


# ---------------------------------------------------------------------------
# Stimpack listing and loading
# ---------------------------------------------------------------------------

def list_installed_stimpacks(profile_id: Optional[str] = None) -> list[StimpackInfo]:
    """Return all stimpacks visible in the user's profile (dev override shadows profile)."""
    if not profile_id:
        profile_id = get_current_profile()

    result = []
    seen: set[str] = set()
    for stimpack_dir, is_dev in _iter_effective_stimpack_dirs(profile_id):
        info = _parse_stimpack_dir(stimpack_dir, is_dev=is_dev)
        if not info or info.name in seen:
            continue
        seen.add(info.name)
        result.append(info)
    return result


def list_stimpacks(profile_id: Optional[str] = None) -> list[StimpackInfo]:
    """List all installed stimpacks. Alias for list_installed_stimpacks."""
    return list_installed_stimpacks(profile_id=profile_id)


def telemetry_stimpack_source(info: Optional[StimpackInfo]) -> str:
    """Closed telemetry enum ``marketplace | dev | builtin`` for a stimpack.

    ``dev`` covers both the dev_stimpacks_dir override and user/agent-authored
    stimpacks (the "people building their own" signal). Stimpack names pass to
    telemetry only when the source is ``marketplace`` (D17 — dev/user stimpack
    names are user content).
    """
    if info is None:
        return "dev"
    if info.is_dev:
        return "dev"
    if info.is_marketplace:
        return "marketplace"
    if info.author in ("user", "agent"):
        return "dev"
    return "builtin"


def load_stimpack(name: str, profile_id: Optional[str] = None) -> Optional[StimpackContent]:
    """Load a stimpack by name and return its first skill's content.

    Pack-level convenience for management surfaces (settings CRUD). Runtime
    activation goes through ``load_skill`` — the agent invokes skills, flat.
    Stimpacks without skills return empty content.
    """
    if not profile_id:
        profile_id = get_current_profile()

    for stimpack_dir, is_dev in _iter_effective_stimpack_dirs(profile_id):
        info = _parse_stimpack_dir(stimpack_dir, is_dev=is_dev)
        if info and info.name == name:
            content = ""
            lander = get_lander(RESOURCE_TYPE_SKILL)
            if info.skills and isinstance(lander, SkillLander):
                result = lander.load_skill(info.skills[0])
                content = result.injection or ""
            # Run stub landers for non-skill resources so they are logged.
            for resource in info.manifest.resources:
                if resource.type == RESOURCE_TYPE_SKILL:
                    continue
                stub = get_lander(resource.type)
                if stub is not None:
                    stub.load(info, resource)
            return StimpackContent(info=info, content=content)
    return None


# ---------------------------------------------------------------------------
# Flat skill listing and loading (the agent-facing surface)
# ---------------------------------------------------------------------------

def list_skills(profile_id: Optional[str] = None) -> list[SkillInfo]:
    """Return all skills across installed stimpacks, flat."""
    skills: list[SkillInfo] = []
    for pack in list_installed_stimpacks(profile_id=profile_id):
        skills.extend(pack.skills)
    return skills


def find_skill(
    name: str, profile_id: Optional[str] = None
) -> Optional[tuple[StimpackInfo, SkillInfo]]:
    """Resolve a skill by pack-qualified name, or by bare slug when unique.

    Also accepts a pack name for legacy single-skill packs (old chat history
    and old prompts address packs by name).
    """
    if not name:
        return None
    packs = list_installed_stimpacks(profile_id=profile_id)
    for pack in packs:
        for skill in pack.skills:
            if skill.qualified_name == name:
                return pack, skill
    bare_matches = [
        (pack, skill)
        for pack in packs
        for skill in pack.skills
        if skill.slug == name
    ]
    if len(bare_matches) == 1:
        return bare_matches[0]
    if len(bare_matches) > 1:
        log.warning(f"Skill name '{name}' is ambiguous across packs — use the qualified name")
        return None
    # Legacy: a pack name addressing its only skill.
    for pack in packs:
        if pack.name == name and len(pack.skills) == 1:
            return pack, pack.skills[0]
    return None


def load_skill(name: str, profile_id: Optional[str] = None) -> Optional[SkillContent]:
    """Load one skill by (qualified or unique bare) name for injection."""
    found = find_skill(name, profile_id=profile_id)
    if not found:
        return None
    pack, skill = found
    lander = get_lander(RESOURCE_TYPE_SKILL)
    content = ""
    if isinstance(lander, SkillLander):
        content = lander.load_skill(skill).injection or ""
    return SkillContent(skill=skill, pack=pack, content=content)


def get_stimpack_lib_modules(enabled_skills: list[str] | None) -> dict[str, Path]:
    """Build {module_name: lib_dir_path} for invoked skills' lib/ directories.

    Each top-level package (directory with __init__.py) or module (.py file)
    directly inside a skill's lib/ directory becomes an importable module in
    run_code. Names are skill names (qualified or bare); on module-name
    collision across skills the first wins.
    """
    if not enabled_skills:
        return {}
    module_paths: dict[str, Path] = {}
    for name in enabled_skills:
        found = find_skill(name)
        if not found:
            continue
        _, skill = found
        for module, lib_dir in _skill_lib_modules(skill.dir_path).items():
            if module in module_paths and module_paths[module] != lib_dir:
                log.warning(
                    f"Skill lib module '{module}' from '{skill.qualified_name}' "
                    f"collides with an already-loaded module — keeping the first"
                )
                continue
            module_paths[module] = lib_dir
    return module_paths


# ---------------------------------------------------------------------------
# Stimpack installation
# ---------------------------------------------------------------------------

def install_stimpack_from_file(file_path: Path, profile_id: Optional[str] = None) -> Optional[StimpackInfo]:
    """Install a stimpack from a .md or .zip file."""
    if not profile_id:
        profile_id = get_current_profile()

    if file_path.suffix == ".zip":
        return _install_from_zip(file_path, profile_id)
    elif file_path.suffix == ".md":
        return _install_from_md(file_path, profile_id)
    else:
        raise ValueError(f"Unsupported file type: {file_path.suffix}. Use .md or .zip")


def install_stimpack_from_zip_bytes(
    zip_bytes: bytes,
    profile_id: Optional[str] = None,
    marketplace_meta: Optional[dict] = None,
) -> Optional[StimpackInfo]:
    """Install a stimpack from zip bytes (used by marketplace install flow).

    Args:
        zip_bytes: Raw zip file content
        profile_id: Profile to install to
        marketplace_meta: If provided, write .marketplace.json sidecar with this data
    """
    if not profile_id:
        profile_id = get_current_profile()

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(zip_bytes)
        tmp_path = Path(tmp.name)

    try:
        info = _install_from_zip(tmp_path, profile_id)
        if info and marketplace_meta:
            write_marketplace_sidecar(
                stimpack_dir=info.dir,
                stimpack_id=marketplace_meta["stimpackId"],
                name=marketplace_meta["name"],
                version=marketplace_meta["version"],
                version_id=marketplace_meta["versionId"],
                author=marketplace_meta.get("author", ""),
                author_avatar_key=marketplace_meta.get("authorAvatarKey", ""),
            )
            # Re-parse to pick up the sidecar
            info = _parse_stimpack_dir(info.dir)
        return info
    finally:
        tmp_path.unlink(missing_ok=True)
        _invalidate_cache(profile_id)


def _install_from_md(file_path: Path, profile_id: str) -> Optional[StimpackInfo]:
    """Install a single bare SKILL.md as a single-`skill` stimpack."""
    text = file_path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text, file_path)
    name = meta.get("name", file_path.stem)
    display_name = meta.get("display_name", _title_case_from_slug(name))

    slug = _slugify(name)
    dest_dir = get_user_stimpacks_dir(profile_id) / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / SKILL_FILENAME

    # Ensure display_name is in frontmatter
    if "display_name" not in meta:
        meta["display_name"] = display_name
        text = "---\n" + yaml.dump(meta, default_flow_style=False).strip() + "\n---\n\n" + body

    dest.write_text(text, encoding="utf-8")
    _write_default_manifest(dest_dir, name, display_name, meta.get("description", ""), meta.get("tags", []) or [])
    _invalidate_cache(profile_id)
    return _parse_stimpack_dir(dest_dir)


def _install_from_zip(file_path: Path, profile_id: str) -> Optional[StimpackInfo]:
    """Install a stimpack from a .zip archive (stimpack.json/SKILL.md + companions)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(file_path, "r") as zf:
            # Security: check for path traversal
            for member in zf.namelist():
                if ".." in member or member.startswith("/"):
                    raise ValueError(f"Unsafe path in zip: {member}")
            zf.extractall(tmp_path)

        # Find the stimpack root: dir containing stimpack.json or SKILL.md, at
        # the top level or one directory deep.
        pack_root = _find_pack_root(tmp_path)
        if pack_root is None:
            raise ValueError("No stimpack.json or SKILL.md found in zip archive")

        manifest = _load_or_derive_manifest(pack_root)
        if manifest is None:
            raise ValueError("Could not load stimpack manifest from zip archive")

        slug = _slugify(manifest.name)
        dest_dir = get_user_stimpacks_dir(profile_id) / slug
        # Replace any existing copy so updates are clean.
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Copy the whole pack directory (manifest, SKILL.md, lib/, assets).
        for f in pack_root.rglob("*"):
            if f.is_file():
                rel = f.relative_to(pack_root)
                out = dest_dir / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out)

        _invalidate_cache(profile_id)
        return _parse_stimpack_dir(dest_dir)


def _find_pack_root(root: Path) -> Optional[Path]:
    """Locate the stimpack root dir within an extracted archive."""
    # Prefer a manifest, then a SKILL.md, at depth <= 2.
    for marker in (STIMPACK_MANIFEST, SKILL_FILENAME):
        for candidate in sorted(root.rglob(marker)):
            depth = len(candidate.relative_to(root).parts)
            if depth <= 2:
                return candidate.parent
    return None


def _write_default_manifest(
    stimpack_dir: Path,
    name: str,
    display_name: str,
    description: str,
    tags: list[str],
    author: str = "user",
) -> None:
    """Write a minimal stimpack.json declaring a single `skill` resource."""
    manifest = {
        "name": name,
        "display_name": display_name,
        "description": description,
        "version": "1",
        "format": STIMPACK_FORMAT_VERSION,
        "author": author,
        "tags": tags or [],
        "resources": [{"type": RESOURCE_TYPE_SKILL, "path": SKILL_FILENAME}],
    }
    (stimpack_dir / STIMPACK_MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Stimpack save / delete
# ---------------------------------------------------------------------------

def save_stimpack(
    name: str,
    content: str,
    description: str = "",
    display_name: str = "",
    tags: Optional[list[str]] = None,
    profile_id: Optional[str] = None,
    author: str = "user",
) -> Path:
    """Save a stimpack (a single `skill` resource + manifest) to the profile dir."""
    if not profile_id:
        profile_id = get_current_profile()

    slug = _slugify(name)
    # Prevent path traversal
    if ".." in slug or "/" in slug or "\\" in slug:
        raise ValueError(f"Invalid stimpack name: {name}")

    stimpack_dir = get_user_stimpacks_dir(profile_id) / slug
    if (stimpack_dir / SKILLS_DIRNAME).is_dir():
        # This editor writes the legacy root-SKILL.md layout; overwriting a
        # multi-skill pack with it would orphan the pack's other skills.
        raise ValueError(
            f"Stimpack '{name}' contains multiple skills and cannot be edited here"
        )
    stimpack_dir.mkdir(parents=True, exist_ok=True)
    path = stimpack_dir / SKILL_FILENAME

    resolved_display = display_name or _title_case_from_slug(name)
    resolved_tags = tags or []

    frontmatter: dict = {
        "name": name,
        "display_name": resolved_display,
        "description": description,
        "author": author,
        "tags": resolved_tags,
    }
    text = "---\n" + yaml.dump(frontmatter, default_flow_style=False).strip() + "\n---\n\n" + content
    path.write_text(text, encoding="utf-8")
    _write_default_manifest(stimpack_dir, name, resolved_display, description, resolved_tags, author)
    _invalidate_cache(profile_id)
    return path


def delete_stimpack(name: str, profile_id: Optional[str] = None) -> bool:
    """Delete a stimpack by name."""
    if not profile_id:
        profile_id = get_current_profile()

    user_dir = get_user_stimpacks_dir(profile_id)
    if not user_dir.is_dir():
        return False

    for stimpack_dir in _iter_stimpack_dirs(user_dir):
        info = _parse_stimpack_dir(stimpack_dir)
        if info and info.name == name:
            if info.marketplace is not None:
                record_removed_auto_installed_stimpack(info.name, profile_id=profile_id)
            shutil.rmtree(stimpack_dir)
            _invalidate_cache(profile_id)
            return True
    return False


def uninstall_stimpack(name: str, profile_id: Optional[str] = None) -> bool:
    """Remove a stimpack from the user's profile dir. Alias for delete_stimpack."""
    return delete_stimpack(name, profile_id=profile_id)


# ---------------------------------------------------------------------------
# Marketplace helpers
# ---------------------------------------------------------------------------

def get_marketplace_installed_stimpacks(profile_id: Optional[str] = None) -> list[StimpackInfo]:
    """Return only marketplace-installed stimpacks (those with .marketplace.json)."""
    return [s for s in list_installed_stimpacks(profile_id) if s.marketplace is not None]


def package_stimpack_as_zip(name: str, profile_id: Optional[str] = None) -> Optional[bytes]:
    """Package a stimpack directory as a zip file for publishing."""
    if not profile_id:
        profile_id = get_current_profile()

    for stimpack_dir, is_dev in _iter_effective_stimpack_dirs(profile_id):
        info = _parse_stimpack_dir(stimpack_dir, is_dev=is_dev)
        if info and info.name == name:
            buf = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024)
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in stimpack_dir.rglob("*"):
                    if f.is_file() and f.name != MARKETPLACE_SIDECAR:
                        arcname = f.relative_to(stimpack_dir)
                        zf.write(f, arcname)
            buf.seek(0)
            return buf.read()
    return None


def has_auto_installed(profile_id: Optional[str] = None) -> bool:
    """Backwards-compatible helper: true when any auto-install state exists."""
    state = _load_auto_install_state(profile_id=profile_id)
    return bool(state["installed"] or state["removed"])


def mark_auto_installed(profile_id: Optional[str] = None) -> None:
    """Backwards-compatible no-op retained for older callers."""
    _write_auto_install_state(_load_auto_install_state(profile_id=profile_id), profile_id=profile_id)
