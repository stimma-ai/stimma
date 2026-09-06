"""pack_summary(): the structured twin of validate_pack's report lines."""

import json
from pathlib import Path

from agent.v2.stimpack_validate import pack_summary, validate_pack


def _write_pack(root: Path) -> Path:
    pack = root / "demo-pack"
    (pack / "skills" / "product-photo" / "lib").mkdir(parents=True)
    (pack / "skills" / "notes").mkdir(parents=True)
    (pack / "stimpack.json").write_text(json.dumps({
        "name": "demo-pack",
        "display_name": "Demo Pack",
        "description": "A pack for the validator test",
        "version": "3",
        "format": 1,
        "author": "user",
        "tags": ["test"],
    }), encoding="utf-8")
    (pack / "skills" / "product-photo" / "SKILL.md").write_text(
        "---\n"
        "name: product-photo\n"
        "display_name: Product Photography\n"
        "description: Studio product shots\n"
        "environments:\n"
        "  chat: true\n"
        "  flow: false\n"
        "  tool:\n"
        "    task_types: [text-to-image]\n"
        "provides:\n"
        "  - product_photo_utils\n"
        "---\n\n# Product Photography\n\nShoot it on white.\n",
        encoding="utf-8",
    )
    (pack / "skills" / "product-photo" / "lib" / "product_photo_utils.py").write_text("X = 1\n", encoding="utf-8")
    (pack / "skills" / "notes" / "SKILL.md").write_text(
        "---\n"
        "name: notes\n"
        "display_name: Notes\n"
        "description: Chat-only helper\n"
        "environments:\n"
        "  chat: true\n"
        "---\n\nRemember things.\n",
        encoding="utf-8",
    )
    return pack


def test_pack_summary_mirrors_the_loader(tmp_path):
    pack = _write_pack(tmp_path)

    summary = pack_summary(pack)

    assert summary is not None
    assert summary["name"] == "demo-pack"
    assert summary["display_name"] == "Demo Pack"
    assert summary["author"] == "user"
    assert summary["version"] == "3"
    assert summary["format"] == 1
    assert summary["lib_modules"] == ["product_photo_utils"]

    by_name = {s["name"]: s for s in summary["skills"]}
    assert set(by_name) == {"demo-pack/product-photo", "demo-pack/notes"}
    photo = by_name["demo-pack/product-photo"]
    assert photo["display_name"] == "Product Photography"
    assert (photo["chat"], photo["flow"], photo["tool"]) == (True, False, True)
    assert photo["tool_task_types"] == ["text-to-image"]
    notes = by_name["demo-pack/notes"]
    assert (notes["chat"], notes["flow"], notes["tool"]) == (True, False, False)
    assert notes["tool_task_types"] is None

    # Same pack, same verdict from the line-oriented validator.
    _report, _warnings, errors = validate_pack(pack)
    assert errors == []


def test_pack_summary_is_none_for_unparseable_dir(tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    assert pack_summary(empty) is None
