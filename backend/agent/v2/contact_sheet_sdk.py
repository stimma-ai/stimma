"""``stimma.contact_sheets``: the agent's side of contact sheets.

The agent writes the sheet as HTML (kit elements for anything that shows media
or asks for review), publishes it, and keeps publishing as the work changes.
Each publish is one revision of the same sheet, shown to the user in the
chat's panel. See ``contact_sheet.py`` for the format.
"""

from __future__ import annotations

import html as htmllib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Optional

if TYPE_CHECKING:  # pragma: no cover
    from .code_runtime import StimmaSDK

_MEDIA_REF_RE = re.compile(r"(?:media:)?(\d+)")
_ASSET_REF_RE = re.compile(r"asset:(\d+)")


def _find_element(html: str, element_id: str) -> tuple[int, int] | None:
    """(inner end index, close tag start) of the kit element with this id."""
    open_re = re.compile(
        r"<(stimma-[a-z-]+)\b[^<>]*\sid\s*=\s*([\"'])" + re.escape(element_id) + r"\2[^<>]*>",
        re.IGNORECASE,
    )
    match = open_re.search(html)
    if match is None:
        return None
    tag = match.group(1).lower()
    depth = 1
    token = re.compile(r"<(/?)" + re.escape(tag) + r"\b[^<>]*?(/?)>", re.IGNORECASE)
    for inner in token.finditer(html, match.end()):
        if inner.group(1):
            depth -= 1
            if depth == 0:
                return match.end(), inner.start()
        elif not inner.group(2):
            depth += 1
    return None


class ContactSheetDraft:
    """One contact sheet being written: its HTML, then publish().

    The document is plain HTML with kit elements. Change it with set_html(),
    or with add() / add_section() for the common case of putting new work on
    the sheet. publish() saves it as the next version and shows it to the user.
    """

    def __init__(self, sdk: "StimmaSDK", title: str, *, asset_id: Optional[int] = None,
                 html: str = "", revision_number: Optional[int] = None):
        self._sdk = sdk
        self._title = title or "Contact sheet"
        self._asset_id = asset_id
        self._html = html
        self._revision_number = revision_number

    def __repr__(self) -> str:
        where = f"asset_id={self._asset_id}, v{self._revision_number}" if self._asset_id else "not published yet"
        return f"<ContactSheet {self._title!r} ({where})>"

    @property
    def asset_id(self) -> Optional[int]:
        return self._asset_id

    @property
    def title(self) -> str:
        return self._title

    def html(self) -> str:
        """The sheet's current HTML."""
        return self._html

    def set_html(self, html: str) -> None:
        """Replace the whole sheet: an HTML string, or a workspace path to one."""
        text = str(html)
        if "<" not in text:
            candidate = Path(text) if Path(text).is_absolute() else self._sdk.workspace_dir / text
            if not candidate.is_file():
                raise FileNotFoundError(f"sheet file not found in workspace: {html}")
            text = candidate.read_text(encoding="utf-8")
        self._html = text

    def write_html(self, path: str = "contact-sheet.html") -> str:
        """Write the current HTML to a workspace file for editing; returns the path.

        Edit it with edit_file, then set_html(path) and publish().
        """
        target = self._sdk.workspace_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self._html, encoding="utf-8")
        return path

    def set_title(self, title: str) -> None:
        self._title = str(title).strip() or self._title

    def _unique_id(self, base: str, reserved: set[str]) -> str:
        n = 1
        while True:
            candidate = f"{base}-{n}"
            if candidate not in reserved and f'id="{candidate}"' not in self._html:
                return candidate
            n += 1

    def append(self, element_id: str, html: str) -> None:
        """Insert markup at the end of the kit element with this id."""
        span = _find_element(self._html, element_id)
        if span is None:
            raise ValueError(f'no kit element with id="{element_id}" on the sheet')
        _start, close = span
        self._html = self._html[:close] + html + self._html[close:]

    def add(self, element_id: str, items: Any, captions: Optional[Iterable[Optional[str]]] = None) -> list[str]:
        """Put media into the element with this id (usually a stimma-media-group).

        ``items`` is one item or a list: ToolResults, media ids, or workspace
        paths. Returns the new tiles' ids, for ratings or checks tied to them.
        """
        values = list(items) if isinstance(items, (list, tuple)) else [items]
        caption_list = list(captions) if captions is not None else []
        ids: list[str] = []
        parts: list[str] = []
        reserved: set[str] = set()
        for index, item in enumerate(values):
            ref = self._ref_for(item)
            tile_id = self._unique_id(element_id, reserved)
            reserved.add(tile_id)
            caption = caption_list[index] if index < len(caption_list) else None
            attrs = f'id="{tile_id}" ref="{htmllib.escape(ref, quote=True)}"'
            if caption:
                attrs += f' caption="{htmllib.escape(str(caption), quote=True)}"'
            parts.append(f"\n  <stimma-media {attrs}></stimma-media>")
            ids.append(tile_id)
        self.append(element_id, "".join(parts) + "\n")
        return ids

    def add_section(self, section_id: str, label: str, note: Optional[str] = None, *,
                    layout: str = "rows", size: str = "m", position: str = "end",
                    collapsed: bool = False) -> str:
        """Add a section with an empty media group; returns the group's id.

        position="start" puts it at the top of the sheet (newest first),
        "end" at the bottom. Fill it with add(group_id, items).
        """
        if layout not in {"rows", "masonry", "uniform"}:
            raise ValueError("layout must be rows, masonry or uniform")
        if size not in {"s", "m", "l"}:
            raise ValueError("size must be s, m or l")
        if f'id="{section_id}"' in self._html:
            raise ValueError(f'id="{section_id}" is already on the sheet')
        group_id = f"{section_id}-media"
        attrs = f'id="{section_id}" label="{htmllib.escape(label, quote=True)}"'
        if note:
            attrs += f' note="{htmllib.escape(note, quote=True)}"'
        if collapsed:
            attrs += " collapsible collapsed"
        block = (f'\n<stimma-section {attrs}>\n'
                 f'  <stimma-media-group id="{group_id}" layout="{layout}" size="{size}"></stimma-media-group>\n'
                 f'</stimma-section>\n')
        if position == "start":
            self._html = block + self._html
        else:
            self._html = self._html + block
        return group_id

    def _ref_for(self, item: Any) -> str:
        from .code_runtime import ToolResult

        if isinstance(item, bool):
            raise TypeError("sheet items are ToolResults, media ids, or workspace paths")
        if isinstance(item, ToolResult):
            if item.media_id is not None:
                return f"media:{int(item.media_id)}"
            return str(item.path)
        if isinstance(item, int):
            return f"media:{item}"
        if isinstance(item, (str, Path)):
            return str(item)
        raise TypeError(f"sheet items are ToolResults, media ids, or workspace paths; got {type(item).__name__}")

    async def _resolve_ref(self, ref: str) -> int:
        from contact_sheet import SheetError, is_sheet_format
        from database import Asset, MediaItem
        from .code_runtime import _make_workspace_resolver

        session = self._sdk.session
        text = ref.strip()
        match = _MEDIA_REF_RE.fullmatch(text)
        if match:
            media = await session.get(MediaItem, int(match.group(1)))
            if media is None or media.deleted_at is not None or media.deletion_pending_at is not None:
                raise SheetError(f"no media {match.group(1)} in the library")
            if is_sheet_format(media.file_format):
                raise SheetError("a contact sheet can't show another contact sheet")
            return media.id
        match = _ASSET_REF_RE.fullmatch(text)
        if match:
            asset = await session.get(Asset, int(match.group(1)))
            if asset is None or asset.deleted_at is not None or asset.current_revision_id is None:
                raise SheetError(f"no asset {match.group(1)} in the library")
            from database import AssetRevision

            revision = await session.get(AssetRevision, asset.current_revision_id)
            if revision is None:
                raise SheetError(f"asset {match.group(1)} has no current version")
            if asset.asset_type == "sheet":
                raise SheetError("a contact sheet can't show another contact sheet")
            return int(revision.primary_media_id)
        resolve = _make_workspace_resolver(self._sdk.workspace_dir, self._sdk.project_workspace_dir, read_only=True)
        try:
            path = resolve(text)
        except Exception as exc:  # noqa: BLE001 - surfaced as a ref error
            raise SheetError(f"not a media id, asset:<id>, or a workspace file ({exc})") from exc
        if not path.is_file():
            raise SheetError("not a media id, asset:<id>, or a file in the workspace")
        saved = await self._sdk.library._save_payload(text)
        return int(saved["media_id"])

    async def publish(self, note: Optional[str] = None) -> dict[str, Any]:
        """Save this HTML as the sheet's next version and show it to the user.

        The first publish opens the sheet in the chat's panel; later ones
        update it in place. Returns {asset_id, version, warnings}. Fix what the
        warnings name, then publish again.
        """
        from contact_sheet import (
            compare_media_ids,
            ingredient_ids,
            normalize_sheet_html,
            require_sheet_asset,
            reviewed_anchors,
            save_sheet_media,
            sheet_metadata,
        )
        from core.profile_context import get_current_profile
        from database import AssetRevision
        from sqlalchemy import select
        from .tools.show import show as show_tool

        session = self._sdk.session
        normalized = await normalize_sheet_html(self._html, self._resolve_ref)
        warnings = list(normalized.warnings)
        ingredients = await ingredient_ids(session, normalized.media_ids,
                                           exempt=compare_media_ids(normalized.html))
        if ingredients:
            warnings.append(
                "Media " + ", ".join(str(i) for i in ingredients[:12])
                + " are what other work on this sheet was made from (start frames, keyframes, sources). "
                "The sheet is for reviewing the finished work, so take them off, collapsed sections "
                "included. Being asked to make them as a step doesn't make them what the user reviews; "
                "keep them only if the user asked to review or choose them."
            )
        if self._asset_id is not None:
            await require_sheet_asset(session, self._asset_id)
            dropped = sorted(await reviewed_anchors(session, self._asset_id)
                             - set(normalized.components) - {"sheet"})
            if dropped:
                warnings.append(
                    "These ids carry the user's review but are no longer on the sheet: "
                    + ", ".join(dropped[:12])
                    + ". Keep ids stable when you rewrite, or the review loses its place."
                )
        media = await save_sheet_media(
            session,
            html=normalized.html,
            meta=sheet_metadata(title=self._title, normalized=normalized),
            profile_id=get_current_profile(),
            chat_id=self._sdk.chat_id,
            project_id=self._sdk.project_id,
        )
        kwargs: dict[str, Any] = {"revision_note": note} if note else {}
        if self._asset_id is None:
            kwargs["artifact"] = True
        else:
            kwargs["revises"] = self._asset_id
        receipt = await show_tool(
            role="final",
            media_ids=[media.id],
            title=self._title,
            session=session,
            chat_id=self._sdk.chat_id,
            workspace_dir=self._sdk.workspace_dir,
            **kwargs,
        )
        if isinstance(receipt, str) and receipt.startswith("Error:"):
            raise ValueError(receipt)
        revision = await session.scalar(select(AssetRevision).where(
            AssetRevision.primary_media_id == media.id, AssetRevision.deleted_at.is_(None)))
        if revision is None:
            raise ValueError("the sheet was saved but didn't become a library item")
        self._asset_id = revision.asset_id
        self._revision_number = revision.revision_number
        self._html = normalized.html
        self._sdk._shown_media_ids.append(media.id)
        self._sdk._display_receipts.append(str(receipt))
        result = {
            "asset_id": self._asset_id,
            "version": self._revision_number,
            "media_count": len(normalized.media_ids),
            "warnings": warnings,
        }
        if warnings:
            (self._sdk._stdout_print or print)("Contact sheet warnings:\n- " + "\n- ".join(warnings))
        return result

    async def review(self) -> dict[str, Any]:
        """The user's review of this sheet so far (answers and comments)."""
        if self._asset_id is None:
            return {"answers": [], "comments": [], "unsent": 0}
        return await sheet_review(self._sdk, self._asset_id)


async def sheet_review(sdk: "StimmaSDK", asset_id: int) -> dict[str, Any]:
    from contact_sheet import (
        _pending,
        current_sheet_media,
        describe_review_rows,
        read_sheet_html,
        require_sheet_asset,
        review_rows,
        sheet_components,
    )

    asset = await require_sheet_asset(sdk.session, asset_id)
    media = await current_sheet_media(sdk.session, asset)
    rows = await review_rows(sdk.session, asset_id)
    pending_ids = {row.id for row in _pending(rows)}
    described = describe_review_rows(rows, sheet_components(read_sheet_html(media)))
    answers, comments = [], []
    for row, item in zip(rows, described):
        item = dict(item, unsent=row.id in pending_ids)
        (comments if row.kind == "comment" else answers).append(item)
    return {"asset_id": asset_id, "title": asset.title, "answers": answers, "comments": comments,
            "unsent": len(pending_ids)}


class StimmaContactSheetsAPI:
    """``stimma.contact_sheets``: present work for the user to review, and read their review."""

    def __init__(self, sdk: "StimmaSDK"):
        self._sdk = sdk

    def new(self, title: str) -> ContactSheetDraft:
        """Start a sheet. Write its HTML (set_html, add_section, add), then publish()."""
        return ContactSheetDraft(self._sdk, title)

    async def open(self, asset_id: Optional[int] = None) -> ContactSheetDraft:
        """Continue a published sheet. With no id: this chat's most recent sheet."""
        from contact_sheet import (
            SheetError,
            current_sheet_media,
            latest_sheet_for_chat,
            read_sheet_html,
            require_sheet_asset,
        )
        from database import AssetRevision

        session = self._sdk.session
        if asset_id is None:
            asset = await latest_sheet_for_chat(session, self._sdk.chat_id)
            if asset is None:
                raise SheetError("this chat has no contact sheet yet; start one with stimma.contact_sheets.new(title)")
        else:
            asset = await require_sheet_asset(session, int(asset_id))
        media = await current_sheet_media(session, asset)
        revision = await session.get(AssetRevision, asset.current_revision_id)
        return ContactSheetDraft(
            self._sdk, asset.title or "Contact sheet", asset_id=asset.id,
            html=read_sheet_html(media), revision_number=revision.revision_number if revision else None,
        )

    async def review(self, asset_id: Optional[int] = None) -> dict[str, Any]:
        """The user's review of a sheet (this chat's latest when no id)."""
        from contact_sheet import SheetError, latest_sheet_for_chat

        if asset_id is None:
            asset = await latest_sheet_for_chat(self._sdk.session, self._sdk.chat_id)
            if asset is None:
                raise SheetError("this chat has no contact sheet yet")
            asset_id = asset.id
        return await sheet_review(self._sdk, int(asset_id))
