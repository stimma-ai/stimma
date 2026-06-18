"""Query building utilities for filtering media items."""
from datetime import datetime
from typing import Optional, Union
from sqlalchemy import select, or_, and_, func
from database import (
    MediaItem, Keyword, MediaKeyword, MediaMarker, MediaTag, MediaToolLineage,
    Board, BoardItem, BoardSection,
)


# =============================================================================
# MEDIA FORMAT CONSTANTS
# =============================================================================
# Atomic formats: standalone media files (image, video, audio, document)
# Composite formats: containers that reference other media items (sets, grids)

VIDEO_FORMATS = ['mp4', 'webm', 'mov', 'avi', 'mkv']  # Note: .ogg can be audio, handled separately
IMAGE_FORMATS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']
AUDIO_FORMATS = ['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg']
TEXT_FORMATS = ['md']
SET_FORMATS = ['stimmaset.json']
GRID_FORMATS = ['stimmagrid.json']
LAYOUT_FORMATS = ['stimmalayout']

# Composite media: containers that hold references to other media items
# These are "grouping" operations that don't transform media
COMPOSITE_FORMATS = SET_FORMATS + GRID_FORMATS

# Atomic media: standalone files that don't contain other media
ATOMIC_FORMATS = VIDEO_FORMATS + IMAGE_FORMATS + AUDIO_FORMATS + TEXT_FORMATS

# Structured = all non-binary formats (text + composite)
STRUCTURED_FORMATS = TEXT_FORMATS + SET_FORMATS + GRID_FORMATS + LAYOUT_FORMATS


def is_composite_format(file_format: str) -> bool:
    """Check if a file format represents composite media (set or grid)."""
    return file_format in COMPOSITE_FORMATS


def is_atomic_format(file_format: str) -> bool:
    """Check if a file format represents atomic media (not a container)."""
    return file_format not in COMPOSITE_FORMATS


def is_composite_media(media: Union[MediaItem, dict]) -> bool:
    """Check if a media item is composite (set or grid).

    Args:
        media: MediaItem instance or dict with 'file_format' key
    """
    if isinstance(media, dict):
        return media.get('file_format') in COMPOSITE_FORMATS
    return media.file_format in COMPOSITE_FORMATS


def is_atomic_media(media: Union[MediaItem, dict]) -> bool:
    """Check if a media item is atomic (not a container).

    Args:
        media: MediaItem instance or dict with 'file_format' key
    """
    return not is_composite_media(media)

# Resolution mapping for filtering
RESOLUTION_MAP = {
    'small': (None, 0.8),     # < 0.8MP
    'medium': (0.8, 1.5),     # 0.8-1.5MP
    'large': (1.5, 3.0),      # 1.5-3.0MP
    'huge': (3.0, None)       # >= 3.0MP
}


def media_pending_autodelete(now: Optional[datetime] = None):
    """Predicate matching MediaItems the cleanup worker is due to auto-delete.

    Mirrors cleanup_service.cleanup_expired_images exactly: an item is removed once
    auto_delete_at has passed AND it has no tags, boards, or markers (any of those
    makes the worker preserve the item and clear its auto_delete_at). This lets read
    APIs hide expired items the instant their deadline passes, instead of leaving them
    visible until the background worker happens to run. Because the keep-rules are
    matched here too, items the worker would preserve are never hidden.
    """
    if now is None:
        now = datetime.utcnow()

    # correlate(MediaItem) pins each EXISTS to the outer MediaItem row ONLY. Without it,
    # auto-correlation strips any subquery FROM that also appears in the enclosing query —
    # so when the outer query joins media_tags/media_markers/board tables (e.g. the
    # filter-counts facet queries), the subquery loses its own driving table and SQLAlchemy
    # raises "returned no FROM clauses due to auto-correlation".
    has_tag = (
        select(1).select_from(MediaTag)
        .where(MediaTag.media_id == MediaItem.id)
        .correlate(MediaItem)
        .exists()
    )
    has_marker = (
        select(1).select_from(MediaMarker)
        .where(MediaMarker.media_id == MediaItem.id)
        .correlate(MediaItem)
        .exists()
    )
    has_board = (
        select(1).select_from(BoardItem)
        .join(BoardSection, BoardSection.id == BoardItem.board_section_id)
        .join(Board, Board.id == BoardSection.board_id)
        .where(
            BoardItem.media_id == MediaItem.id,
            BoardSection.deleted_at.is_(None),
            Board.deleted_at.is_(None),
        )
        .correlate(MediaItem)
        .exists()
    )
    return and_(
        MediaItem.auto_delete_at.isnot(None),
        MediaItem.auto_delete_at <= now,
        ~has_tag,
        ~has_marker,
        ~has_board,
    )


def not_due_for_autodelete(now: Optional[datetime] = None):
    """Negation of media_pending_autodelete — add to active read queries so expired
    generations vanish at their deadline while staying consistent with the worker's
    keep rules (tagged/boarded/markered items are never hidden)."""
    return ~media_pending_autodelete(now)


def build_filtered_query(
    query,
    caption_query: Optional[str] = None,
    prompt_query: Optional[str] = None,
    media_types: Optional[str] = None,
    excluded_media_types: Optional[str] = None,
    resolutions: Optional[str] = None,
    excluded_resolutions: Optional[str] = None,
    keywords: Optional[str] = None,
    excluded_keywords: Optional[str] = None,
    folders: Optional[str] = None,
    excluded_folders: Optional[str] = None,
    is_generated: Optional[bool] = None,
    marker_ids: Optional[str] = None,
    excluded_marker_ids: Optional[str] = None,
    tag_ids: Optional[str] = None,
    excluded_tag_ids: Optional[str] = None,
    tool_ids: Optional[str] = None,
    excluded_tool_ids: Optional[str] = None,
    tool_id: Optional[str] = None,
    preset_id: Optional[int] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    show_expiring: Optional[bool] = None,
    exclude_expiring: Optional[bool] = None,
    min_mp: Optional[float] = None,
    max_mp: Optional[float] = None,
    include_superseded: bool = False,
    exclude_expired: bool = True,
    include_ephemeral: bool = False,
    exclude_category: Optional[str] = None,
):
    """
    Apply filters to a query, optionally excluding a specific filter category.

    This is the single source of truth for media filter semantics. All browser-screen
    endpoints (library, trash, project views, find-index, filter-counts) should route
    through here so a filter only has to be implemented once.

    Args:
        query: SQLAlchemy query to apply filters to
        exclude_category: Category to exclude from filtering ('media_types', 'resolutions', 'keywords', 'folders', 'tags', 'tools')
        include_superseded: When True, include items owned by sets/grids (used by Trash so users see everything being trashed)
        exclude_expired: When True (default), hide items the auto-delete worker is due to remove so
            expired generations disappear at their deadline even before the worker runs. Trash opts
            out (exclude_expired=False) since it intentionally surfaces already-removed items.
        include_ephemeral: When False (default), hide ephemeral media (rows produced by one-shot
            flow-as-tool runs, tagged with ephemeral_run_id). These never belong in any user-facing
            view; this single filter covers /api/media, trash, find-index, and similar-search.
        Other args: Filter parameters matching /api/media endpoint

    Returns:
        Filtered query
    """
    # Ephemeral media (one-shot flow-as-tool run intermediates) are never surfaced to the user.
    # This sits beside the deleted_at filter the callers apply so no browse/search/trash view leaks them.
    if not include_ephemeral:
        query = query.where(MediaItem.ephemeral_run_id.is_(None))

    # Filter out items owned by sets/grids unless caller opts in (Trash needs to show them)
    if not include_superseded:
        query = query.where(MediaItem.superseded_by.is_(None))

    # Hide items whose auto-delete deadline has passed, before the background worker
    # physically removes them — see not_due_for_autodelete. Trash opts out.
    if exclude_expired:
        query = query.where(not_due_for_autodelete())

    # Text filters
    if caption_query:
        query = query.where(MediaItem.vlm_caption.ilike(f"%{caption_query}%"))

    if prompt_query:
        # Search both extracted_prompt (imported) and generation_metadata.prompt (generated)
        # Word-boundary-aware: pad with spaces, normalize punctuation, search for ' term '
        from sqlalchemy import literal
        gen_prompt = func.json_extract(MediaItem.generation_metadata, '$.prompt')
        def _word_match_prompt(col, term):
            padded = literal(' ').op('||')(func.coalesce(col, '')).op('||')(literal(' '))
            normalized = func.replace(func.replace(func.replace(func.replace(
                func.replace(padded, ',', ' '), '.', ' '), ';', ' '), ':', ' '), '-', ' ')
            return normalized.ilike(f"% {term} %")
        query = query.where(or_(
            _word_match_prompt(MediaItem.extracted_prompt, prompt_query),
            _word_match_prompt(gen_prompt, prompt_query),
        ))

    # Media type filter (OR within category)
    if exclude_category != 'media_types':
        if media_types:
            types_list = [t.strip() for t in media_types.split(',') if t.strip()]
            format_conditions = []
            for media_type_item in types_list:
                if media_type_item == 'images':
                    format_conditions.append(MediaItem.file_format.in_(IMAGE_FORMATS))
                elif media_type_item == 'videos':
                    format_conditions.append(MediaItem.file_format.in_(VIDEO_FORMATS))
                elif media_type_item == 'audio':
                    format_conditions.append(MediaItem.file_format.in_(AUDIO_FORMATS))
                elif media_type_item == 'text':
                    format_conditions.append(MediaItem.file_format.in_(TEXT_FORMATS))
                elif media_type_item == 'sets':
                    format_conditions.append(MediaItem.file_format.in_(SET_FORMATS))
                elif media_type_item == 'grids':
                    format_conditions.append(MediaItem.file_format.in_(GRID_FORMATS))
                elif media_type_item == 'layouts':
                    format_conditions.append(MediaItem.file_format.in_(LAYOUT_FORMATS))
                elif media_type_item == 'structured':
                    format_conditions.append(MediaItem.file_format.in_(STRUCTURED_FORMATS))
            if format_conditions:
                query = query.where(or_(*format_conditions))

        # Excluded media types (NOT logic)
        if excluded_media_types:
            excluded_types_list = [t.strip() for t in excluded_media_types.split(',') if t.strip()]
            for media_type_item in excluded_types_list:
                if media_type_item == 'images':
                    query = query.where(~MediaItem.file_format.in_(IMAGE_FORMATS))
                elif media_type_item == 'videos':
                    query = query.where(~MediaItem.file_format.in_(VIDEO_FORMATS))
                elif media_type_item == 'audio':
                    query = query.where(~MediaItem.file_format.in_(AUDIO_FORMATS))
                elif media_type_item == 'text':
                    query = query.where(~MediaItem.file_format.in_(TEXT_FORMATS))
                elif media_type_item == 'sets':
                    query = query.where(~MediaItem.file_format.in_(SET_FORMATS))
                elif media_type_item == 'grids':
                    query = query.where(~MediaItem.file_format.in_(GRID_FORMATS))
                elif media_type_item == 'layouts':
                    query = query.where(~MediaItem.file_format.in_(LAYOUT_FORMATS))
                elif media_type_item == 'structured':
                    query = query.where(~MediaItem.file_format.in_(STRUCTURED_FORMATS))

    # Keyword filter (AND logic) - using normalized keywords tables
    if exclude_category != 'keywords':
        if keywords:
            keyword_list = [k.strip().lower() for k in keywords.split(',') if k.strip()]
            for keyword in keyword_list:
                # Use EXISTS subquery to check if media item has this keyword
                # This works with the normalized keywords tables
                keyword_exists = select(1).select_from(MediaKeyword).join(
                    Keyword, MediaKeyword.keyword_id == Keyword.id
                ).where(
                    and_(
                        MediaKeyword.media_id == MediaItem.id,
                        Keyword.keyword_text == keyword
                    )
                ).exists()
                query = query.where(keyword_exists)

        # Excluded keywords filter (NOT logic)
        if excluded_keywords:
            excluded_list = [k.strip().lower() for k in excluded_keywords.split(',') if k.strip()]
            for keyword in excluded_list:
                # Use NOT EXISTS subquery
                keyword_exists = select(1).select_from(MediaKeyword).join(
                    Keyword, MediaKeyword.keyword_id == Keyword.id
                ).where(
                    and_(
                        MediaKeyword.media_id == MediaItem.id,
                        Keyword.keyword_text == keyword
                    )
                ).exists()
                query = query.where(~keyword_exists)

    # Folder filters (OR within category) - ensure paths end with / to avoid partial matches
    if exclude_category != 'folders':
        if folders:
            folder_list = [f.strip().rstrip('/') + '/' for f in folders.split(',') if f.strip()]
            if folder_list:
                folder_conditions = [MediaItem.file_path.startswith(folder) for folder in folder_list]
                query = query.where(or_(*folder_conditions))

        if excluded_folders:
            excluded_folder_list = [f.strip().rstrip('/') + '/' for f in excluded_folders.split(',') if f.strip()]
            for folder in excluded_folder_list:
                query = query.where(~MediaItem.file_path.startswith(folder))

    # Resolution filter (OR within category)
    if exclude_category != 'resolutions':
        if resolutions:
            res_list = [r.strip() for r in resolutions.split(',') if r.strip()]
            res_conditions = []
            for res_name in res_list:
                if res_name in RESOLUTION_MAP:
                    min_val, max_val = RESOLUTION_MAP[res_name]
                    if min_val is not None and max_val is not None:
                        res_conditions.append(and_(
                            MediaItem.megapixels >= min_val,
                            MediaItem.megapixels < max_val
                        ))
                    elif min_val is not None:
                        res_conditions.append(MediaItem.megapixels >= min_val)
                    elif max_val is not None:
                        res_conditions.append(MediaItem.megapixels < max_val)
            if res_conditions:
                query = query.where(or_(*res_conditions))

        # Excluded resolutions (NOT logic)
        if excluded_resolutions:
            excluded_res_list = [r.strip() for r in excluded_resolutions.split(',') if r.strip()]
            for res_name in excluded_res_list:
                if res_name in RESOLUTION_MAP:
                    min_val, max_val = RESOLUTION_MAP[res_name]
                    if min_val is not None and max_val is not None:
                        query = query.where(or_(
                            MediaItem.megapixels < min_val,
                            MediaItem.megapixels >= max_val
                        ))
                    elif min_val is not None:
                        query = query.where(MediaItem.megapixels < min_val)
                    elif max_val is not None:
                        query = query.where(MediaItem.megapixels >= max_val)

    # Generation filter
    if is_generated is not None:
        if is_generated:
            query = query.where(MediaItem.generation_metadata.isnot(None))
        else:
            query = query.where(MediaItem.generation_metadata.is_(None))

    # Marker filter (OR logic - item must have at least one of the specified markers)
    # Excludes suppressed markers (source != 'suppressed')
    if marker_ids:
        marker_id_list = [int(mid.strip()) for mid in marker_ids.split(',') if mid.strip()]
        if marker_id_list:
            marker_subquery = select(MediaMarker.media_id).where(
                and_(
                    MediaMarker.marker_id.in_(marker_id_list),
                    MediaMarker.source != 'suppressed'
                )
            ).distinct()
            query = query.where(MediaItem.id.in_(marker_subquery))

    # Excluded marker filter (item must NOT have any of the specified markers)
    # Only considers visible markers (not suppressed)
    if excluded_marker_ids:
        excluded_marker_id_list = [int(mid.strip()) for mid in excluded_marker_ids.split(',') if mid.strip()]
        if excluded_marker_id_list:
            excluded_marker_subquery = select(MediaMarker.media_id).where(
                and_(
                    MediaMarker.marker_id.in_(excluded_marker_id_list),
                    MediaMarker.source != 'suppressed'
                )
            ).distinct()
            query = query.where(MediaItem.id.notin_(excluded_marker_subquery))

    # Tag filter (OR logic - item must have at least one of the specified tags)
    if exclude_category != 'tags':
        if tag_ids:
            tag_id_list = [int(tid.strip()) for tid in tag_ids.split(',') if tid.strip()]
            if tag_id_list:
                tag_subquery = select(MediaTag.media_id).where(
                    MediaTag.tag_id.in_(tag_id_list)
                ).distinct()
                query = query.where(MediaItem.id.in_(tag_subquery))

        if excluded_tag_ids:
            excluded_tag_id_list = [int(tid.strip()) for tid in excluded_tag_ids.split(',') if tid.strip()]
            if excluded_tag_id_list:
                excluded_tag_subquery = select(MediaTag.media_id).where(
                    MediaTag.tag_id.in_(excluded_tag_id_list)
                ).distinct()
                query = query.where(MediaItem.id.notin_(excluded_tag_subquery))

    # Tool lineage filter (OR logic - item must have at least one of the specified tools in its lineage)
    if exclude_category != 'tools':
        if tool_ids:
            tool_id_list = [tid.strip() for tid in tool_ids.split(',') if tid.strip()]
            if tool_id_list:
                tool_subquery = select(MediaToolLineage.media_id).where(
                    MediaToolLineage.full_tool_id.in_(tool_id_list)
                ).distinct()
                query = query.where(MediaItem.id.in_(tool_subquery))

        if excluded_tool_ids:
            excluded_tool_id_list = [tid.strip() for tid in excluded_tool_ids.split(',') if tid.strip()]
            if excluded_tool_id_list:
                excluded_tool_subquery = select(MediaToolLineage.media_id).where(
                    MediaToolLineage.full_tool_id.in_(excluded_tool_id_list)
                ).distinct()
                query = query.where(MediaItem.id.notin_(excluded_tool_subquery))

    # Single-tool filter: filter by the tool that created the media (not lineage)
    if tool_id:
        query = query.where(MediaItem.tool_id == tool_id)

    # Preset filter: filter by preset that was active during generation
    if preset_id:
        query = query.where(MediaItem.preset_id == preset_id)

    # Date filters (created_date)
    if created_after:
        try:
            date = datetime.fromisoformat(created_after)
            query = query.where(MediaItem.created_date >= date)
        except ValueError:
            pass

    if created_before:
        try:
            date = datetime.fromisoformat(created_before)
            query = query.where(MediaItem.created_date <= date)
        except ValueError:
            pass

    # Expiring (auto_delete_at) filters
    if show_expiring:
        query = query.where(MediaItem.auto_delete_at.isnot(None))
    if exclude_expiring:
        query = query.where(MediaItem.auto_delete_at.is_(None))

    # Direct megapixel range (legacy: only meaningful when `resolutions` is not used)
    if min_mp is not None:
        query = query.where(MediaItem.megapixels >= min_mp)
    if max_mp is not None:
        query = query.where(MediaItem.megapixels <= max_mp)

    return query
