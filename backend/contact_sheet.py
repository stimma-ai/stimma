"""Contact sheets (``.stimmasheet.html``): the agent's review surface.

A contact sheet is the agent's organized, living presentation of work it wants
the user to look at, plus the user's review of it. The document is HTML the
agent writes freely; anything that touches media or review is a kit element,
which the app renders as a live component:

    stimma-section       label, note, collapsible, collapsed
    stimma-media-group   layout = rows | masonry | uniform, size = s | m | l, aspect
    stimma-media         ref, caption
    stimma-columns / stimma-column
    stimma-compare       a, b, caption
    stimma-check         for            (review: yes/no)
    stimma-choice        label, multiple; children stimma-option value, ref
    stimma-rating        for            (review: 1-5)
    stimma-field         label, placeholder   (review: free text)

Refs name library media. The agent may write a media id (``ref="812"``),
``media:812``, ``asset:45`` (that Asset's current payload) or a workspace path;
saving canonicalizes every ref to ``media:<id>`` so a revision always shows
exactly what it showed when it was committed.

Sheets are containers in the asset model: every referenced Media is an exact
embedded member of the revision, so nothing the sheet shows is deleted from
under it. Review (answers and comments) is host data keyed by (sheet asset,
component id), never part of the HTML, so it survives the agent rewriting the
page.
"""

from __future__ import annotations

import hashlib
import html as htmllib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Asset, AssetRevision, ContactSheetReview, MediaItem

SHEET_FORMAT = "stimmasheet.html"
SHEET_EXTENSION = ".stimmasheet.html"
SHEET_DOCUMENT_TYPE = "contact_sheet"

KIT_TAGS = frozenset({
    "stimma-section", "stimma-media-group", "stimma-media", "stimma-columns", "stimma-column",
    "stimma-compare", "stimma-check", "stimma-choice", "stimma-option", "stimma-rating", "stimma-field",
})
# Components that carry an id: review and comments anchor on it.
ANCHORED_TAGS = frozenset({
    "stimma-section", "stimma-media", "stimma-compare",
    "stimma-check", "stimma-choice", "stimma-rating", "stimma-field",
})
REVIEW_TAGS = frozenset({"stimma-check", "stimma-choice", "stimma-rating", "stimma-field"})
ID_PREFIX = {
    "stimma-section": "section", "stimma-media": "media", "stimma-compare": "compare",
    "stimma-check": "check", "stimma-choice": "choice", "stimma-rating": "rating", "stimma-field": "field",
}
# Attributes that hold a media ref, per tag.
REF_ATTRS = {"stimma-media": ("ref",), "stimma-option": ("ref",), "stimma-compare": ("a", "b")}

MAX_SHEET_BYTES = 2 * 1024 * 1024
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_OPEN_TAG_RE = re.compile(r"<(stimma-[a-z][a-z-]*)(\s[^<>]*?)?\s*(/?)>", re.IGNORECASE)
_ATTR_RE = re.compile(
    r"""([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?""",
)
_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_EXTERNAL_RE = re.compile(r"""(?:\b(?:src|href)\s*=\s*["']?\s*(?:https?:)?//|url\(\s*["']?\s*(?:https?:)?//)""", re.IGNORECASE)
_HANDLER_RE = re.compile(r"""<[a-z][^<>]*\son[a-z]+\s*=""", re.IGNORECASE)


class SheetError(ValueError):
    """The sheet cannot be saved as written."""


def is_sheet_format(file_format: Optional[str]) -> bool:
    return (file_format or "").lower() == SHEET_FORMAT


# -- parsing ------------------------------------------------------------------

def _parse_attrs(raw: str) -> list[tuple[str, Optional[str]]]:
    attrs: list[tuple[str, Optional[str]]] = []
    for match in _ATTR_RE.finditer(raw or ""):
        name = match.group(1).lower()
        value = next((g for g in match.group(2, 3, 4) if g is not None), None)
        attrs.append((name, htmllib.unescape(value) if value is not None else None))
    return attrs


def _render_open_tag(tag: str, attrs: list[tuple[str, Optional[str]]]) -> str:
    parts = [tag]
    for name, value in attrs:
        parts.append(name if value is None else f'{name}="{htmllib.escape(value, quote=True)}"')
    return "<" + " ".join(parts) + ">"


def canonical_ref(media_id: int) -> str:
    return f"media:{int(media_id)}"


def media_id_of_ref(ref: Optional[str]) -> Optional[int]:
    """The media id of a canonical ``media:<id>`` ref, else None."""
    match = re.fullmatch(r"media:(\d+)", (ref or "").strip())
    return int(match.group(1)) if match else None


RefResolver = Callable[[str], Awaitable[int]]


@dataclass
class NormalizedSheet:
    html: str
    media_ids: list[int]
    components: dict[str, str]          # component id -> tag
    warnings: list[str] = field(default_factory=list)


async def normalize_sheet_html(html: str, resolve_ref: RefResolver) -> NormalizedSheet:
    """Canonicalize refs and ids, and lint what the agent wrote.

    ``resolve_ref`` turns whatever the agent wrote in a ref attribute into a
    media id, raising ``SheetError`` (or ValueError) when it cannot. Errors
    stop the save; warnings come back to the agent with the receipt.
    """
    if not isinstance(html, str) or not html.strip():
        raise SheetError("the sheet is empty; write HTML with at least one section or media element")
    if len(html.encode("utf-8")) > MAX_SHEET_BYTES:
        raise SheetError("the sheet is larger than 2 MB; reference media by ref instead of inlining it")

    warnings: list[str] = []
    errors: list[str] = []
    if _SCRIPT_RE.search(html):
        html = _SCRIPT_RE.sub("", html)
        warnings.append("Removed <script>: sheets don't run scripts. Use the review elements for anything interactive.")
    if _HANDLER_RE.search(html):
        warnings.append("Event handler attributes (onclick and the like) are dropped when the sheet renders.")
    if _EXTERNAL_RE.search(html):
        warnings.append("External URLs don't load in a sheet. Show media with <stimma-media ref=...> and keep styles inline.")

    # Pass 1: find every kit tag, the refs to resolve and the ids in use.
    matches = list(_OPEN_TAG_RE.finditer(html))
    used_ids: set[str] = set()
    raw_refs: list[str] = []
    unknown: set[str] = set()
    for match in matches:
        tag = match.group(1).lower()
        if tag not in KIT_TAGS:
            unknown.add(tag)
            continue
        attrs = dict(_parse_attrs(match.group(2) or ""))
        for attr in REF_ATTRS.get(tag, ()):
            value = (attrs.get(attr) or "").strip()
            if value:
                raw_refs.append(value)
            elif tag == "stimma-media" or tag == "stimma-compare":
                errors.append(f"<{tag}> needs {attr}=\"...\" naming the media to show")
        if attrs.get("id"):
            used_ids.add(attrs["id"])
    if unknown:
        warnings.append("Unknown elements render as plain markup: " + ", ".join(f"<{t}>" for t in sorted(unknown)))

    resolved: dict[str, int] = {}
    for ref in dict.fromkeys(raw_refs):
        try:
            resolved[ref] = int(await resolve_ref(ref))
        except (SheetError, ValueError, LookupError, OSError) as exc:
            errors.append(f'ref="{ref}": {exc}')
    if errors:
        raise SheetError("; ".join(errors[:8]))

    # Pass 2: rewrite kit open tags with canonical refs and stable ids.
    components: dict[str, str] = {}
    media_ids: list[int] = []
    counters: dict[str, int] = {}
    seen_ids: set[str] = set()
    out: list[str] = []
    cursor = 0

    def fresh_id(tag: str) -> str:
        prefix = ID_PREFIX[tag]
        while True:
            counters[prefix] = counters.get(prefix, 0) + 1
            candidate = f"{prefix}-{counters[prefix]}"
            if candidate not in used_ids and candidate not in seen_ids:
                return candidate

    for match in matches:
        tag = match.group(1).lower()
        out.append(html[cursor:match.start()])
        cursor = match.end()
        if tag not in KIT_TAGS:
            out.append(match.group(0))
            continue
        attrs = _parse_attrs(match.group(2) or "")
        rewritten: list[tuple[str, Optional[str]]] = []
        has_id = False
        for name, value in attrs:
            if name in REF_ATTRS.get(tag, ()) and value and value.strip() in resolved:
                media_id = resolved[value.strip()]
                if media_id not in media_ids:
                    media_ids.append(media_id)
                value = canonical_ref(media_id)
            if name == "id":
                has_id = True
                if tag in ANCHORED_TAGS:
                    if not value or not _ID_RE.match(value):
                        warnings.append(f'id="{value}" isn\'t a usable id (letters, digits, - and _); replaced it')
                        value = fresh_id(tag)
                    elif value in seen_ids:
                        new_id = fresh_id(tag)
                        warnings.append(f'id="{value}" is used more than once; renamed a copy to "{new_id}"')
                        value = new_id
            rewritten.append((name, value))
        if tag in ANCHORED_TAGS and not has_id:
            rewritten.insert(0, ("id", fresh_id(tag)))
        if tag in ANCHORED_TAGS:
            component_id = next(v for n, v in rewritten if n == "id")
            seen_ids.add(component_id)
            components[component_id] = tag
        out.append(_render_open_tag(tag, rewritten))
        if match.group(3):
            # <stimma-media ... /> is not self-closing in HTML; close it here
            # so following siblings don't end up nested inside it.
            out.append(f"</{tag}>")
    out.append(html[cursor:])
    normalized = "".join(out)

    # A rating or check tied to a picture must name a component that exists.
    for match in _OPEN_TAG_RE.finditer(normalized):
        tag = match.group(1).lower()
        if tag in {"stimma-rating", "stimma-check"}:
            target = dict(_parse_attrs(match.group(2) or "")).get("for")
            if target and components.get(target) not in {"stimma-media", "stimma-compare"}:
                warnings.append(f'<{tag} for="{target}"> doesn\'t name a stimma-media or stimma-compare id on this sheet')
    if not components and not media_ids:
        warnings.append("This sheet has no kit elements, so there's nothing to review. Show media with <stimma-media ref=...>.")
    return NormalizedSheet(html=normalized, media_ids=media_ids, components=components, warnings=warnings)


class _ComponentParser(HTMLParser):
    """Collect kit components with their attributes and text, by id."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.components: dict[str, dict[str, Any]] = {}
        self._stack: list[tuple[str, Optional[dict[str, Any]]]] = []
        self._choice: Optional[dict[str, Any]] = None
        self._option: Optional[dict[str, Any]] = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = {k: (v or "") for k, v in attrs}
        entry: Optional[dict[str, Any]] = None
        if tag in ANCHORED_TAGS and attrs_dict.get("id"):
            entry = {"tag": tag, "attrs": attrs_dict, "text": ""}
            if tag == "stimma-choice":
                entry["options"] = []
                self._choice = entry
            self.components[attrs_dict["id"]] = entry
        elif tag == "stimma-option" and self._choice is not None:
            self._option = {"value": attrs_dict.get("value", ""), "ref": attrs_dict.get("ref", ""), "label": ""}
            self._choice["options"].append(self._option)
        self._stack.append((tag, entry))

    def handle_endtag(self, tag):
        while self._stack:
            open_tag, _entry = self._stack.pop()
            if open_tag == "stimma-choice":
                self._choice = None
            if open_tag == "stimma-option":
                self._option = None
            if open_tag == tag:
                break

    def handle_data(self, data):
        if self._option is not None:
            self._option["label"] += data
        for _tag, entry in reversed(self._stack):
            if entry is not None and entry["tag"] in {"stimma-check"}:
                entry["text"] += data
                break


def sheet_components(html: str) -> dict[str, dict[str, Any]]:
    parser = _ComponentParser()
    parser.feed(html or "")
    parser.close()
    for entry in parser.components.values():
        entry["text"] = " ".join(entry.get("text", "").split())
        for option in entry.get("options") or []:
            option["label"] = " ".join(option["label"].split())
    return parser.components


# -- documents and media ------------------------------------------------------

def sheet_metadata(*, title: str, normalized: NormalizedSheet) -> dict[str, Any]:
    return {
        "type": SHEET_DOCUMENT_TYPE,
        "version": 1,
        "title": title,
        "media": normalized.media_ids,
        "components": normalized.components,
    }


def parse_sheet_metadata(raw: Any) -> Optional[dict[str, Any]]:
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw or "{}")
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(raw, dict) or raw.get("type") != SHEET_DOCUMENT_TYPE:
        return None
    return raw


def read_sheet_html(media: MediaItem) -> str:
    return Path(media.file_path).read_text(encoding="utf-8")


async def sheet_member_specs(session: AsyncSession, meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Every referenced Media, embedded exactly, in document order."""
    specs: list[dict[str, Any]] = []
    for media_id in meta.get("media") or []:
        media = await session.get(MediaItem, int(media_id))
        if media is None or media.deleted_at is not None or media.deletion_pending_at is not None:
            continue
        specs.append({"embedded_media_id": media.id, "title": canonical_ref(media.id)})
    return specs


async def save_sheet_media(
    session: AsyncSession,
    *,
    html: str,
    meta: dict[str, Any],
    profile_id: str,
    chat_id: Optional[int] = None,
    project_id: Optional[int] = None,
    source: str = "agent_v2_run_code",
) -> MediaItem:
    """Write one sheet revision's document into managed storage."""
    import app_dirs
    from config_version import get_config_version_manager
    from generation_metadata import dump_generation_metadata
    from storage_service import cleanup_staged_source, stage_managed_media

    data = html.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    staging = app_dirs.get_managed_staging_dir(profile_id, "generated")
    staging.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", (meta.get("title") or "contact-sheet").lower()).strip("-")[:48] or "contact-sheet"
    path = staging / f"{slug}-{digest[:10]}{SHEET_EXTENSION}"
    path.write_bytes(data)

    now = datetime.utcnow()
    media = MediaItem(
        file_path=str(path),
        file_hash=digest,
        file_size=len(data),
        file_format=SHEET_FORMAT,
        original_filename=path.name,
        created_date=now,
        modified_date=now,
        indexed_date=now,
        metadata_status="completed",
        metadata_processed_at=now,
        metadata_config_version=get_config_version_manager().get_version("metadata"),
        width=0,
        height=0,
        megapixels=0.0,
        has_alpha=False,
        clip_status="skipped",
        face_detection_status="skipped",
        vlm_caption_status="skipped",
        raw_metadata=json.dumps(meta),
        generation_metadata=dump_generation_metadata(
            task_type="contact_sheet",
            source=source,
            source_inputs=[{"media_id": mid, "role": "member"} for mid in meta.get("media") or []],
            extra={"contact_sheet": {"title": meta.get("title"), "member_count": len(meta.get("media") or [])}},
        ),
    )
    session.add(media)
    await session.flush()
    await stage_managed_media(session, media=media, profile_id=profile_id, remove_source=True)
    if chat_id is not None:
        from asset_service import acquire_media_owner

        await acquire_media_owner(
            session,
            media_id=media.id,
            root_kind="chat",
            root_id=chat_id,
            role="result",
            idempotency_key=f"chat:{chat_id}:sheet:{media.id}",
        )
    if project_id is not None:
        from project_service import attach_media_to_project

        await attach_media_to_project(session, project_id, media.id)
    await session.commit()
    await session.refresh(media)
    await cleanup_staged_source(session, media_id=media.id)
    return media


async def _asset_for_media(session: AsyncSession, media_id: int) -> Optional[int]:
    return await session.scalar(
        select(AssetRevision.asset_id)
        .join(Asset, Asset.id == AssetRevision.asset_id)
        .where(
            AssetRevision.primary_media_id == media_id,
            AssetRevision.deleted_at.is_(None),
            Asset.deleted_at.is_(None),
        )
        .limit(1)
    )


async def sheet_content(session: AsyncSession, media: MediaItem) -> Optional[dict[str, Any]]:
    """What the viewer needs: the HTML and every referenced media, resolved."""
    meta = parse_sheet_metadata(media.raw_metadata)
    if meta is None:
        return None
    try:
        html = read_sheet_html(media)
    except OSError:
        return None
    revision = await session.scalar(
        select(AssetRevision).where(
            AssetRevision.primary_media_id == media.id,
            AssetRevision.deleted_at.is_(None),
        )
    )
    asset = await session.get(Asset, revision.asset_id) if revision is not None else None
    members: dict[str, Optional[dict[str, Any]]] = {}
    for media_id in meta.get("media") or []:
        item = await session.get(MediaItem, int(media_id))
        if item is None or item.deleted_at is not None:
            members[str(media_id)] = None
            continue
        members[str(media_id)] = {
            "media_id": item.id,
            "asset_id": await _asset_for_media(session, item.id),
            "file_hash": item.file_hash,
            "file_path": item.file_path,
            "file_format": item.file_format,
            "width": item.width,
            "height": item.height,
            "duration": item.duration,
            "has_alpha": item.has_alpha,
        }
    return {
        "type": SHEET_DOCUMENT_TYPE,
        "version": 1,
        "title": (asset.title if asset is not None else None) or meta.get("title"),
        "asset_id": revision.asset_id if revision is not None else None,
        "revision_id": revision.id if revision is not None else None,
        "revision_number": revision.revision_number if revision is not None else None,
        "html": html,
        "members": members,
    }


async def latest_sheet_for_chat(session: AsyncSession, chat_id: int) -> Optional[Asset]:
    return await session.scalar(
        select(Asset)
        .where(
            Asset.asset_type == "sheet",
            Asset.origin_id == str(chat_id),
            Asset.deleted_at.is_(None),
        )
        .order_by(Asset.id.desc())
        .limit(1)
    )


async def current_sheet_media(session: AsyncSession, asset: Asset) -> MediaItem:
    revision = await session.get(AssetRevision, asset.current_revision_id) if asset.current_revision_id else None
    media = await session.get(MediaItem, revision.primary_media_id) if revision is not None else None
    if media is None or not is_sheet_format(media.file_format):
        raise SheetError(f"asset {asset.id} is not a contact sheet")
    return media


async def require_sheet_asset(session: AsyncSession, asset_id: int) -> Asset:
    asset = await session.get(Asset, int(asset_id))
    if asset is None or asset.deleted_at is not None or asset.asset_type != "sheet":
        raise SheetError(f"asset {asset_id} is not a contact sheet")
    return asset


# -- review -------------------------------------------------------------------

def _is_empty_answer(value: Any) -> bool:
    return value is None or value is False or value == "" or value == [] or value == 0


async def review_rows(session: AsyncSession, asset_id: int) -> list[ContactSheetReview]:
    return list(await session.scalars(
        select(ContactSheetReview)
        .where(ContactSheetReview.asset_id == asset_id, ContactSheetReview.deleted_at.is_(None))
        .order_by(ContactSheetReview.id)
    ))


def review_row_dict(row: ContactSheetReview) -> dict[str, Any]:
    return {
        "id": row.id,
        "anchor": row.anchor,
        "kind": row.kind,
        "value": json.loads(row.value) if row.value else None,
        "author": {"kind": row.author_kind, "name": row.author_name},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "sent": row.sent_at is not None and (row.kind == "comment" or row.sent_value == row.value),
        # A sent answer that is now cleared is still news: the retraction.
        "was_sent": row.sent_value is not None,
    }


async def get_review(session: AsyncSession, asset_id: int) -> dict[str, Any]:
    rows = await review_rows(session, asset_id)
    answers = {row.anchor: review_row_dict(row) for row in rows if row.kind == "answer"}
    comments = [review_row_dict(row) for row in rows if row.kind == "comment"]
    return {"asset_id": asset_id, "answers": answers, "comments": comments,
            "pending": len(_pending(rows))}


async def set_answer(session: AsyncSession, asset_id: int, anchor: str, value: Any,
                     *, author_kind: str = "owner", author_name: Optional[str] = None) -> ContactSheetReview:
    if not _ID_RE.match(anchor or ""):
        raise SheetError("invalid component id")
    row = await session.scalar(select(ContactSheetReview).where(
        ContactSheetReview.asset_id == asset_id,
        ContactSheetReview.anchor == anchor,
        ContactSheetReview.kind == "answer",
        ContactSheetReview.deleted_at.is_(None),
    ))
    encoded = json.dumps(value)
    now = datetime.utcnow()
    if row is None:
        row = ContactSheetReview(asset_id=asset_id, anchor=anchor, kind="answer", value=encoded,
                                 author_kind=author_kind, author_name=author_name, created_at=now, updated_at=now)
        session.add(row)
    else:
        row.value = encoded
        row.updated_at = now
    await session.flush()
    return row


async def add_comment(session: AsyncSession, asset_id: int, anchor: str, text: str,
                      *, author_kind: str = "owner", author_name: Optional[str] = None) -> ContactSheetReview:
    text = (text or "").strip()
    if not text:
        raise SheetError("a comment needs text")
    if not _ID_RE.match(anchor or ""):
        raise SheetError("invalid component id")
    now = datetime.utcnow()
    row = ContactSheetReview(asset_id=asset_id, anchor=anchor, kind="comment", value=json.dumps(text[:4000]),
                             author_kind=author_kind, author_name=author_name, created_at=now, updated_at=now)
    session.add(row)
    await session.flush()
    return row


def _pending(rows: Iterable[ContactSheetReview]) -> list[ContactSheetReview]:
    out = []
    for row in rows:
        if row.kind == "comment":
            if row.sent_at is None:
                out.append(row)
        elif row.value != row.sent_value:
            value = json.loads(row.value) if row.value else None
            # A cleared answer only matters when the agent saw it set.
            if not _is_empty_answer(value) or row.sent_value is not None:
                out.append(row)
    return out


def _media_label(component: Optional[dict[str, Any]]) -> tuple[str, Optional[int]]:
    if not component:
        return "", None
    attrs = component["attrs"]
    caption = attrs.get("caption") or ""
    media_id = media_id_of_ref(attrs.get("ref") or attrs.get("b"))
    return caption, media_id


def describe_review_rows(rows: Iterable[ContactSheetReview], components: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One readable line per answer or comment, with what it is about."""
    items: list[dict[str, Any]] = []
    for row in rows:
        value = json.loads(row.value) if row.value else None
        component = components.get(row.anchor)
        tag = component["tag"] if component else None
        attrs = component["attrs"] if component else {}
        item: dict[str, Any] = {"kind": row.kind, "id": row.anchor, "media_id": None, "about": None}
        if row.kind == "comment":
            if tag in {"stimma-media", "stimma-compare"}:
                caption, media_id = _media_label(component)
                item.update(about=caption or None, media_id=media_id)
            elif tag == "stimma-section":
                item["about"] = attrs.get("label") or None
            elif row.anchor == "sheet":
                item["about"] = "the whole sheet"
            item["text"] = str(value or "")
        elif tag == "stimma-check":
            target = components.get(attrs.get("for", ""))
            caption, media_id = _media_label(target)
            item.update(kind="check", question=component.get("text") or row.anchor,
                        text="yes" if value else "no", about=caption or None, media_id=media_id)
        elif tag == "stimma-rating":
            target = components.get(attrs.get("for", ""))
            caption, media_id = _media_label(target)
            item.update(kind="rating", question=attrs.get("label") or "Rating",
                        text=f"{int(value or 0)} of 5" if value else "no rating", about=caption or None, media_id=media_id)
        elif tag == "stimma-choice":
            chosen = [value] if isinstance(value, str) else list(value or [])
            options = {o["value"]: o for o in component.get("options") or []}
            labels = [options[v]["label"] if v in options else v for v in chosen]
            first = options.get(chosen[0]) if chosen else None
            item.update(kind="choice", question=attrs.get("label") or row.anchor,
                        text=", ".join(labels) if labels else "no choice",
                        media_id=media_id_of_ref(first["ref"]) if first else None)
        elif tag == "stimma-field":
            item.update(kind="field", question=attrs.get("label") or row.anchor, text=str(value or "") or "(cleared)")
        else:
            item.update(kind="answer", question=row.anchor, text=json.dumps(value))
        items.append(item)
    return items


def format_review_message(*, title: str, asset_id: int, revision_number: Optional[int], items: list[dict[str, Any]]) -> str:
    """The review as the agent reads it in the transcript."""
    head = f'My review of the contact sheet "{title}" (asset_id={asset_id}'
    head += f", v{revision_number})" if revision_number else ")"
    lines = [head + ":"]
    for item in items:
        target = ""
        if item.get("about") and item.get("media_id"):
            target = f'"{item["about"]}" (media {item["media_id"]})'
        elif item.get("about"):
            target = f'"{item["about"]}"' if item["about"] != "the whole sheet" else item["about"]
        elif item.get("media_id"):
            target = f"media {item['media_id']}"
        if item["kind"] == "comment":
            lines.append(f'- Comment on {target or "the sheet"} [{item["id"]}]: {item["text"]}')
        elif item["kind"] == "choice":
            chosen = f'{item["text"]} (media {item["media_id"]})' if item.get("media_id") else item["text"]
            lines.append(f'- {item["question"]} [{item["id"]}]: {chosen}')
        elif target:
            lines.append(f'- {item["question"]}, for {target} [{item["id"]}]: {item["text"]}')
        else:
            lines.append(f'- {item["question"]} [{item["id"]}]: {item["text"]}')
    return "\n".join(lines)


async def take_pending_review(session: AsyncSession, asset_id: int) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Describe and mark sent everything the agent hasn't seen yet."""
    asset = await require_sheet_asset(session, asset_id)
    media = await current_sheet_media(session, asset)
    rows = _pending(await review_rows(session, asset_id))
    if not rows:
        return [], None
    components = sheet_components(read_sheet_html(media))
    items = describe_review_rows(rows, components)
    revision = await session.get(AssetRevision, asset.current_revision_id)
    message = format_review_message(
        title=asset.title or "Contact sheet",
        asset_id=asset.id,
        revision_number=revision.revision_number if revision is not None else None,
        items=items,
    )
    now = datetime.utcnow()
    for row in rows:
        row.sent_at = now
        row.sent_value = row.value
    await session.flush()
    return items, message


async def reviewed_anchors(session: AsyncSession, asset_id: int) -> set[str]:
    return {row.anchor for row in await review_rows(session, asset_id)}
