"""Validate a stimpack directory with the real loader.

    uv run python -m agent.v2.stimpack_validate <path> [<path> ...]

Wrapped by ``stimma stimpacks validate``. Parses the pack exactly the way the
app does, then reports what the agent would see: pack identity, every skill
with its per-environment eligibility, and importable lib modules. Errors exit
non-zero so the check can gate CI or a publish script.
"""

import json
import sys
from pathlib import Path

from .stimpacks import (
    KNOWN_RESOURCE_TYPES,
    SKILL_FILENAME,
    SKILLS_DIRNAME,
    STIMPACK_FORMAT_VERSION,
    STIMPACK_MANIFEST,
    _parse_frontmatter,
    _parse_stimpack_dir,
    _skill_lib_modules,
)

KNOWN_FRONTMATTER_KEYS = {
    "name", "display_name", "description", "author", "tags", "environments", "provides", "version",
}
KNOWN_ENVIRONMENT_KEYS = {"chat", "flow", "tool"}


def validate_pack(pack_dir: Path) -> tuple[list[str], list[str], list[str]]:
    """Validate one stimpack directory. Returns (report_lines, warnings, errors)."""
    report: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    manifest_path = pack_dir / STIMPACK_MANIFEST
    root_skill = pack_dir / SKILL_FILENAME
    skills_root = pack_dir / SKILLS_DIRNAME

    if not pack_dir.is_dir():
        return report, warnings, [f"not a directory: {pack_dir}"]
    if not manifest_path.is_file() and not root_skill.is_file():
        return report, warnings, [
            f"no {STIMPACK_MANIFEST} or {SKILL_FILENAME} at the pack root — nothing would load"
        ]

    # Raw manifest checks (the loader is forgiving; surface what it papers over)
    if manifest_path.is_file():
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            return report, warnings, [f"{STIMPACK_MANIFEST} is not valid JSON: {e}"]
        if not isinstance(raw, dict):
            return report, warnings, [f"{STIMPACK_MANIFEST} must be a JSON object"]
        for key in ("name", "display_name", "description"):
            if not raw.get(key):
                warnings.append(f"{STIMPACK_MANIFEST}: missing '{key}'")
        raw_format = raw.get("format", STIMPACK_FORMAT_VERSION)
        if not isinstance(raw_format, int):
            warnings.append(f"{STIMPACK_MANIFEST}: 'format' should be an integer (got {raw_format!r})")
        elif raw_format > STIMPACK_FORMAT_VERSION:
            warnings.append(
                f"{STIMPACK_MANIFEST}: format {raw_format} is newer than this build supports "
                f"({STIMPACK_FORMAT_VERSION}); the app loads it best-effort"
            )
        for entry in raw.get("resources") or []:
            rtype = entry.get("type") if isinstance(entry, dict) else None
            if rtype and rtype not in KNOWN_RESOURCE_TYPES:
                warnings.append(f"{STIMPACK_MANIFEST}: unknown resource type '{rtype}' (ignored by the loader)")
    elif root_skill.is_file():
        warnings.append(
            f"no {STIMPACK_MANIFEST} — loads as a legacy single-skill pack with a derived "
            "manifest; published packs should ship a real manifest"
        )

    if skills_root.is_dir() and root_skill.is_file():
        warnings.append(
            f"both {SKILLS_DIRNAME}/ and a root {SKILL_FILENAME} exist — the root file is IGNORED "
            f"when {SKILLS_DIRNAME}/ has skills"
        )

    info = _parse_stimpack_dir(pack_dir)
    if info is None:
        return report, warnings, ["the loader could not parse this pack"]

    report.append(f"pack:    {info.name}  ({info.display_name})  format={info.manifest.format}")
    report.append(f"author:  {info.manifest.author or '(none)'}   version: {info.manifest.version}")
    if info.description:
        report.append(f"desc:    {info.description}")

    if not info.skills:
        errors.append("pack contains no loadable skills")
        return report, warnings, errors

    # Per-skill checks
    seen_slugs: set[str] = set()
    all_modules: dict[str, str] = {}
    report.append(f"skills:  {len(info.skills)}")
    for skill in info.skills:
        env = skill.environments
        tool_desc = "no"
        if env.tool:
            tool_desc = "all task types" if env.tool_task_types is None else ",".join(env.tool_task_types)
        report.append(
            f"  - {skill.qualified_name:40s} chat={'yes' if env.chat else 'no':3s} "
            f"flow={'yes' if env.flow else 'no':3s} tool={tool_desc}"
        )

        if skill.slug in seen_slugs:
            errors.append(f"duplicate skill slug '{skill.slug}'")
        seen_slugs.add(skill.slug)

        if not skill.description:
            warnings.append(
                f"{skill.slug}: no description — the agent picks skills by description, "
                "so an empty one effectively hides it"
            )
        if not (env.chat or env.flow or env.tool):
            warnings.append(f"{skill.slug}: environments block enables nothing — the skill is never offered")

        fm, body = _parse_frontmatter(skill.skill_md.read_text(encoding="utf-8"), skill.skill_md)
        if not body.strip():
            errors.append(f"{skill.slug}: {SKILL_FILENAME} has no body — invoking it injects nothing")
        for key in fm:
            if key not in KNOWN_FRONTMATTER_KEYS:
                warnings.append(f"{skill.slug}: unknown frontmatter key '{key}' (ignored)")
        env_block = fm.get("environments")
        if isinstance(env_block, dict):
            for key in env_block:
                if key not in KNOWN_ENVIRONMENT_KEYS:
                    warnings.append(
                        f"{skill.slug}: unknown environments key '{key}' "
                        f"(known: {', '.join(sorted(KNOWN_ENVIRONMENT_KEYS))})"
                    )

        # lib/ + provides
        modules = _skill_lib_modules(skill.dir_path)
        provides = set(skill.provides)
        for module in provides - set(modules):
            errors.append(f"{skill.slug}: provides '{module}' but lib/ has no such module")
        for module in set(modules) - provides:
            warnings.append(
                f"{skill.slug}: lib/ module '{module}' is not declared in 'provides:' "
                "(it still loads, but the agent isn't told about it)"
            )
        for module in modules:
            if module in all_modules:
                errors.append(
                    f"lib module '{module}' provided by both '{all_modules[module]}' and "
                    f"'{skill.slug}' — the first invoked wins"
                )
            all_modules[module] = skill.slug

    if all_modules:
        report.append(f"lib:     {', '.join(sorted(all_modules))}")
    return report, warnings, errors


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip())
        return 2
    failed = False
    for arg in argv:
        pack_dir = Path(arg).expanduser().resolve()
        print(f"── {pack_dir}")
        report, warnings, errors = validate_pack(pack_dir)
        for line in report:
            print(f"   {line}")
        for w in warnings:
            print(f"   warning: {w}")
        for e in errors:
            print(f"   ERROR:   {e}")
        if errors:
            failed = True
            print("   ✗ invalid")
        elif warnings:
            plural = "s" if len(warnings) != 1 else ""
            print(f"   ✓ valid ({len(warnings)} warning{plural})")
        else:
            print("   ✓ valid")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
