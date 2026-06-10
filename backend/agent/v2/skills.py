"""Skill index, loading, and saving for reusable instruction documents.

Skills are stored as directories containing a SKILL.md file plus optional assets.
Layout:
    skills/
        my-skill/
            SKILL.md            # frontmatter + markdown body
            .marketplace.json   # optional — tracks marketplace origin
            example.png         # optional companion files
            lib/                # optional Python modules for run_code

Skills come from two sources:
- **Local**: Created by the user or agent directly on disk
- **Marketplace**: Installed from stimma.ai/skills, tracked via .marketplace.json sidecar
"""

import json
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from app_dirs import get_data_dir, get_profile_dir
from core.logging import get_logger
from core.profile_context import get_current_profile

log = get_logger(__name__)

SKILL_FILENAME = "SKILL.md"
MARKETPLACE_SIDECAR = ".marketplace.json"
AUTO_INSTALL_STATE_FILE = ".marketplace-auto-install-state.json"


def _title_case_from_slug(slug: str) -> str:
    """Convert a slug like 'batch-variations' to 'Batch Variations'."""
    return slug.replace("-", " ").replace("_", " ").title()


@dataclass
class MarketplaceMeta:
    """Metadata from .marketplace.json sidecar file."""
    skill_id: str
    name: str
    version: int
    version_id: str
    installed_at: str
    author: str
    author_avatar_key: str = ""


@dataclass
class SkillInfo:
    name: str
    display_name: str
    description: str
    author: str  # "user" | "agent" | "marketplace"
    tags: list[str]
    path: Path  # path to SKILL.md
    tier: str  # "local" | "marketplace"
    provides: list[str] = field(default_factory=list)
    marketplace: Optional[MarketplaceMeta] = None
    is_dev: bool = False  # Loaded from the dev_skills_dir override (shadows profile copy)

    @property
    def dir(self) -> Path:
        """The skill's directory (parent of SKILL.md)."""
        return self.path.parent

    @property
    def is_marketplace(self) -> bool:
        """True if installed from marketplace and not locally modified."""
        return self.marketplace is not None


@dataclass
class SkillContent:
    info: SkillInfo
    content: str  # markdown body without frontmatter


# Module-level cache keyed by profile_id
_cache: dict[str, list[SkillInfo]] = {}


def _invalidate_cache(profile_id: Optional[str] = None) -> None:
    global _cache
    if profile_id:
        _cache.pop(profile_id, None)
    else:
        _cache.clear()


def get_user_skills_dir(profile_id: Optional[str] = None) -> Path:
    if not profile_id:
        profile_id = get_current_profile()
    d = get_profile_dir(profile_id=profile_id) / "skills"
    d.mkdir(parents=True, exist_ok=True)
    # One-time migration: copy from old flat/global skills dir
    _maybe_migrate_skills(d)
    return d


def get_skill_assets_dir(name: str, profile_id: Optional[str] = None) -> Path:
    """Return the assets directory for a skill (its own directory)."""
    if not profile_id:
        profile_id = get_current_profile()
    # Assets now live alongside SKILL.md in the skill's directory
    d = get_user_skills_dir(profile_id) / _slugify(name)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _iter_skill_dirs(base_dir: Path):
    """Yield SKILL.md paths from skill subdirectories."""
    if not base_dir.is_dir():
        return
    for child in sorted(base_dir.iterdir()):
        if child.is_dir():
            skill_file = child / SKILL_FILENAME
            if skill_file.is_file():
                yield skill_file


_dev_dir_logged: Optional[str] = None


def _dev_skills_dir() -> Optional[Path]:
    """Return the configured dev skills override directory, if set and present.

    When configured (`dev_skills_dir`), skills here are the authority for built-in
    skills: they shadow same-named skills in the profile dir, so editing the
    stimma-skills repo is picked up live with no publish/install round trip.
    """
    global _dev_dir_logged
    try:
        from config import get_settings
        raw = get_settings().dev_skills_dir
    except Exception:
        return None
    if not raw:
        return None
    p = Path(os.path.expanduser(raw))
    if not p.is_dir():
        if _dev_dir_logged != str(p):
            log.warning(f"dev_skills_dir is set but not a directory: {p}")
            _dev_dir_logged = str(p)
        return None
    if _dev_dir_logged != str(p):
        log.info(f"dev skills override active: {p} (shadows profile skills by name)")
        _dev_dir_logged = str(p)
        _track_dev_skills_enabled(p)
    return p


def _track_dev_skills_enabled(dev_dir: Path) -> None:
    """Emit dev_skills_enabled {skillCount} on the configuration *transition*.

    A state file remembers the last-seen dev dir so per-launch re-detection
    doesn't re-fire (per-launch state is session_started.skillCounts.dev).
    Count only — nothing identifying.
    """
    try:
        import app_dirs
        state_path = app_dirs.get_data_dir() / "dev_skills_state"
        previous = state_path.read_text(encoding="utf-8").strip() if state_path.exists() else ""
        current = str(dev_dir)
        if previous == current:
            return
        state_path.write_text(current, encoding="utf-8")
        skill_count = sum(1 for _ in _iter_skill_dirs(dev_dir))
        from telemetry import get_telemetry_client
        get_telemetry_client().track(
            "dev_skills_enabled", {"skillCount": skill_count}, category="skills"
        )
    except Exception:
        pass


def _iter_effective_skill_dirs(profile_id: str):
    """Yield (skill_md_path, is_dev) for all skill dirs, dev override first.

    Dev skills are yielded before profile skills, so callers that resolve by name
    (load_skill, package_skill_as_zip) naturally prefer the dev copy. Shadowing is
    by skill *name* rather than directory name — list_installed_skills dedupes by
    name, keeping the dev copy — because a skill's directory name may differ from
    its frontmatter name (e.g. dir "mood-board" / name "mood-board-studio").
    """
    dev_dir = _dev_skills_dir()
    if dev_dir:
        for p in _iter_skill_dirs(dev_dir):
            yield p, True
    for p in _iter_skill_dirs(get_user_skills_dir(profile_id)):
        yield p, False


def _maybe_migrate_skills(profile_skills_dir: Path) -> None:
    """Migrate skills from old layouts to directory-based layout (one-time).

    Handles two old layouts:
    1. Global flat dir: <data_dir>/skills/*.md
    2. Profile flat dir: <profile>/skills/*.md (files directly in skills/)
    """
    # Migrate old flat .md files in profile dir to subdirectories
    flat_md_files = [p for p in profile_skills_dir.glob("*.md") if p.is_file()]
    if flat_md_files:
        log.info(f"Migrating {len(flat_md_files)} flat skill files to directory layout in {profile_skills_dir}")
        for src in flat_md_files:
            dest_dir = profile_skills_dir / src.stem
            dest_dir.mkdir(exist_ok=True)
            dest = dest_dir / SKILL_FILENAME
            shutil.move(str(src), str(dest))
            # Also move companion assets if they exist in the old skill-assets dir
            old_assets = profile_skills_dir.parent / "skill-assets" / src.stem
            if old_assets.is_dir():
                for asset in old_assets.iterdir():
                    if asset.is_file():
                        shutil.copy2(asset, dest_dir / asset.name)
                shutil.rmtree(old_assets)

    # Migrate from old global skills dir
    global_skills_dir = get_data_dir() / "skills"
    if not global_skills_dir.is_dir():
        return
    global_md_files = list(global_skills_dir.glob("*.md"))
    if not global_md_files:
        return
    existing = list(_iter_skill_dirs(profile_skills_dir))
    if existing:
        return  # Profile dir already has skills, skip migration
    log.info(f"Migrating {len(global_md_files)} skills from global dir to profile dir {profile_skills_dir}")
    for src in global_md_files:
        dest_dir = profile_skills_dir / src.stem
        dest_dir.mkdir(exist_ok=True)
        shutil.copy2(src, dest_dir / SKILL_FILENAME)


def _slugify(name: str) -> str:
    """Convert a skill name to a safe filename slug."""
    # Normalize unicode, lowercase, replace non-alphanum with hyphens
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    s = re.sub(r"[-\s]+", "-", s)
    return s or "skill"


def _parse_frontmatter(text: str, path: Path) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text.

    Returns (metadata_dict, body_without_frontmatter).
    Falls back to directory-name-based metadata if malformed.
    """
    # Use parent dir name as fallback (since the file is always SKILL.md)
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


def _load_marketplace_sidecar(skill_dir: Path) -> Optional[MarketplaceMeta]:
    """Load .marketplace.json sidecar if present."""
    sidecar_path = skill_dir / MARKETPLACE_SIDECAR
    if not sidecar_path.is_file():
        return None
    try:
        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        return MarketplaceMeta(
            skill_id=data["skillId"],
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
    skill_dir: Path,
    skill_id: str,
    name: str,
    version: int,
    version_id: str,
    author: str,
    author_avatar_key: str = "",
) -> None:
    """Write .marketplace.json sidecar to a skill directory."""
    from datetime import datetime, timezone
    sidecar_path = skill_dir / MARKETPLACE_SIDECAR
    data = {
        "skillId": skill_id,
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


def should_auto_install_skill(name: str, profile_id: Optional[str] = None) -> bool:
    """Return True if this profile should still receive the named auto-install skill."""
    installed_skills = {skill.name for skill in list_installed_skills(profile_id=profile_id)}
    if name in installed_skills:
        return False

    state = _load_auto_install_state(profile_id=profile_id)
    if name in state["removed"]:
        return False
    if name in state["installed"]:
        return False
    return True


def record_auto_installed_skill(name: str, profile_id: Optional[str] = None) -> None:
    """Record that a marketplace skill was auto-installed for this profile."""
    state = _load_auto_install_state(profile_id=profile_id)
    state["installed"] = [skill_name for skill_name in state["installed"] if skill_name != name]
    state["removed"] = [skill_name for skill_name in state["removed"] if skill_name != name]
    state["installed"].append(name)
    _write_auto_install_state(state, profile_id=profile_id)


def record_removed_auto_installed_skill(name: str, profile_id: Optional[str] = None) -> None:
    """Record that the user removed a marketplace skill that should not be reinstalled."""
    state = _load_auto_install_state(profile_id=profile_id)
    state["removed"] = [skill_name for skill_name in state["removed"] if skill_name != name]
    state["removed"].append(name)
    _write_auto_install_state(state, profile_id=profile_id)


def _parse_skill_file(path: Path, is_dev: bool = False) -> Optional[SkillInfo]:
    """Parse a SKILL.md file into SkillInfo, detecting marketplace origin from sidecar."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        log.warning(f"Failed to read skill file {path}: {e}")
        return None

    meta, _ = _parse_frontmatter(text, path)
    name = meta.get("name", path.stem)
    display_name = meta.get("display_name", _title_case_from_slug(name))

    # Check for marketplace sidecar
    marketplace = _load_marketplace_sidecar(path.parent)
    tier = "marketplace" if marketplace else "local"
    author = meta.get("author", "marketplace" if marketplace else "user")

    return SkillInfo(
        name=name,
        display_name=display_name,
        description=meta.get("description", ""),
        author=author,
        tags=meta.get("tags", []),
        path=path,
        tier=tier,
        provides=meta.get("provides", []),
        marketplace=marketplace,
        is_dev=is_dev,
    )


# ---------------------------------------------------------------------------
# Skill listing and loading
# ---------------------------------------------------------------------------

def list_installed_skills(profile_id: Optional[str] = None) -> list[SkillInfo]:
    """Return all skills visible in the user's profile (dev override shadows profile)."""
    if not profile_id:
        profile_id = get_current_profile()

    result = []
    seen: set[str] = set()
    for p, is_dev in _iter_effective_skill_dirs(profile_id):
        info = _parse_skill_file(p, is_dev=is_dev)
        if not info or info.name in seen:
            continue
        seen.add(info.name)
        result.append(info)
    return result


def list_skills(profile_id: Optional[str] = None) -> list[SkillInfo]:
    """List all installed skills. Alias for list_installed_skills."""
    return list_installed_skills(profile_id=profile_id)


def telemetry_skill_source(info: Optional[SkillInfo]) -> str:
    """Closed telemetry enum ``marketplace | dev | builtin`` for a skill.

    ``dev`` covers both the dev_skills_dir override and user/agent-authored
    skills (the "people building their own skills" signal). Skill names pass
    to telemetry only when the source is ``marketplace`` (D17 — dev/user
    skill names are user content).
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


def load_skill(name: str, profile_id: Optional[str] = None) -> Optional[SkillContent]:
    """Load full skill content by name (dev override shadows profile)."""
    if not profile_id:
        profile_id = get_current_profile()

    for p, is_dev in _iter_effective_skill_dirs(profile_id):
        info = _parse_skill_file(p, is_dev=is_dev)
        if info and info.name == name:
            text = p.read_text(encoding="utf-8")
            _, body = _parse_frontmatter(text, p)
            return SkillContent(info=info, content=body)
    return None


def get_skill_lib_modules(enabled_skills: list[str] | None) -> dict[str, Path]:
    """Build {module_name: lib_dir_path} for enabled skills that have a lib/ directory.

    Each top-level package (directory with __init__.py) or module (.py file) directly
    inside a skill's lib/ directory becomes an importable module in run_code.
    """
    if not enabled_skills:
        return {}
    module_paths: dict[str, Path] = {}
    for skill_name in enabled_skills:
        loaded = load_skill(skill_name)
        if not loaded:
            continue
        lib_dir = loaded.info.dir / "lib"
        if not lib_dir.is_dir():
            continue
        for child in lib_dir.iterdir():
            if child.is_dir() and (child / "__init__.py").exists():
                module_paths[child.name] = lib_dir
            elif child.is_file() and child.suffix == ".py" and child.stem != "__init__":
                module_paths[child.stem] = lib_dir
    return module_paths


# ---------------------------------------------------------------------------
# Skill installation
# ---------------------------------------------------------------------------

def install_skill_from_file(file_path: Path, profile_id: Optional[str] = None) -> Optional[SkillInfo]:
    """Install a skill from a .md or .zip file."""
    if not profile_id:
        profile_id = get_current_profile()

    if file_path.suffix == ".zip":
        return _install_from_zip(file_path, profile_id)
    elif file_path.suffix == ".md":
        return _install_from_md(file_path, profile_id)
    else:
        raise ValueError(f"Unsupported file type: {file_path.suffix}. Use .md or .zip")


def install_skill_from_zip_bytes(
    zip_bytes: bytes,
    profile_id: Optional[str] = None,
    marketplace_meta: Optional[dict] = None,
) -> Optional[SkillInfo]:
    """Install a skill from zip bytes (used by marketplace install flow).

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
                skill_dir=info.dir,
                skill_id=marketplace_meta["skillId"],
                name=marketplace_meta["name"],
                version=marketplace_meta["version"],
                version_id=marketplace_meta["versionId"],
                author=marketplace_meta.get("author", ""),
                author_avatar_key=marketplace_meta.get("authorAvatarKey", ""),
            )
            # Re-parse to pick up the sidecar
            info = _parse_skill_file(info.path)
        return info
    finally:
        tmp_path.unlink(missing_ok=True)
        _invalidate_cache(profile_id)


def _install_from_md(file_path: Path, profile_id: str) -> Optional[SkillInfo]:
    """Install a skill from a single .md file."""
    text = file_path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text, file_path)
    name = meta.get("name", file_path.stem)
    display_name = meta.get("display_name", _title_case_from_slug(name))

    slug = _slugify(name)
    dest_dir = get_user_skills_dir(profile_id) / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / SKILL_FILENAME

    # Ensure display_name is in frontmatter
    if "display_name" not in meta:
        meta["display_name"] = display_name
        text = "---\n" + yaml.dump(meta, default_flow_style=False).strip() + "\n---\n\n" + body

    dest.write_text(text, encoding="utf-8")
    _invalidate_cache(profile_id)
    return _parse_skill_file(dest)


def _install_from_zip(file_path: Path, profile_id: str) -> Optional[SkillInfo]:
    """Install a skill from a .zip archive containing SKILL.md + companion files."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(file_path, "r") as zf:
            # Security: check for path traversal
            for member in zf.namelist():
                if ".." in member or member.startswith("/"):
                    raise ValueError(f"Unsafe path in zip: {member}")
            zf.extractall(tmp_path)

        # Find SKILL.md (at top level or one directory deep)
        skill_md = None
        for candidate in tmp_path.rglob(SKILL_FILENAME):
            # Prefer top-level or one-level-deep SKILL.md
            depth = len(candidate.relative_to(tmp_path).parts)
            if depth <= 2:
                skill_md = candidate
                break

        if not skill_md:
            # Fall back to any .md file
            md_files = list(tmp_path.rglob("*.md"))
            if not md_files:
                raise ValueError("No SKILL.md or .md file found in zip archive")
            skill_md = md_files[0]

        info = _install_from_md(skill_md, profile_id)
        if not info:
            return None

        # Copy companion files into the skill's directory
        skill_dir = get_user_skills_dir(profile_id) / _slugify(info.name)
        source_root = skill_md.parent
        for f in source_root.rglob("*"):
            if f.is_file() and f.name != SKILL_FILENAME:
                rel = f.relative_to(source_root)
                dest = skill_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)

        return info


# ---------------------------------------------------------------------------
# Skill save / delete
# ---------------------------------------------------------------------------

def save_skill(
    name: str,
    content: str,
    description: str = "",
    display_name: str = "",
    tags: Optional[list[str]] = None,
    profile_id: Optional[str] = None,
) -> Path:
    """Save a skill to the user skills directory."""
    if not profile_id:
        profile_id = get_current_profile()

    slug = _slugify(name)
    # Prevent path traversal
    if ".." in slug or "/" in slug or "\\" in slug:
        raise ValueError(f"Invalid skill name: {name}")

    skill_dir = get_user_skills_dir(profile_id) / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / SKILL_FILENAME

    frontmatter: dict = {
        "name": name,
        "display_name": display_name or _title_case_from_slug(name),
        "description": description,
        "author": "user",
        "tags": tags or [],
    }
    text = "---\n" + yaml.dump(frontmatter, default_flow_style=False).strip() + "\n---\n\n" + content
    path.write_text(text, encoding="utf-8")
    _invalidate_cache(profile_id)
    return path


def delete_skill(name: str, profile_id: Optional[str] = None) -> bool:
    """Delete a skill by name."""
    if not profile_id:
        profile_id = get_current_profile()

    user_dir = get_user_skills_dir(profile_id)
    if not user_dir.is_dir():
        return False

    for p in _iter_skill_dirs(user_dir):
        info = _parse_skill_file(p)
        if info and info.name == name:
            if info.marketplace is not None:
                record_removed_auto_installed_skill(info.name, profile_id=profile_id)
            shutil.rmtree(p.parent)
            _invalidate_cache(profile_id)
            return True
    return False


def uninstall_skill(name: str, profile_id: Optional[str] = None) -> bool:
    """Remove a skill from the user's profile dir. Alias for delete_skill."""
    return delete_skill(name, profile_id=profile_id)


# ---------------------------------------------------------------------------
# Marketplace helpers
# ---------------------------------------------------------------------------

def get_marketplace_installed_skills(profile_id: Optional[str] = None) -> list[SkillInfo]:
    """Return only marketplace-installed skills (those with .marketplace.json)."""
    return [s for s in list_installed_skills(profile_id) if s.marketplace is not None]


def package_skill_as_zip(name: str, profile_id: Optional[str] = None) -> Optional[bytes]:
    """Package a skill directory as a zip file for publishing."""
    if not profile_id:
        profile_id = get_current_profile()

    for p, is_dev in _iter_effective_skill_dirs(profile_id):
        info = _parse_skill_file(p, is_dev=is_dev)
        if info and info.name == name:
            skill_dir = p.parent
            buf = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024)
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in skill_dir.rglob("*"):
                    if f.is_file() and f.name != MARKETPLACE_SIDECAR:
                        arcname = f.relative_to(skill_dir)
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
