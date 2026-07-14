"""Query building utilities for filtering media items."""
from datetime import datetime
from typing import Optional, Union
from sqlalchemy import select, or_, and_, case, func, false, true
from database import (
    AssetMarker,
    AssetRevision,
    AssetTag,
    Keyword,
    MediaItem,
    MediaKeyword,
    MediaToolLineage,
    Project,
    ProjectAsset,
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
    """Compatibility predicate: Media no longer auto-deletes independently."""
    return false()


def not_due_for_autodelete(now: Optional[datetime] = None):
    """Compatibility predicate: Media availability is owner-driven."""
    return true()


def media_is_imported():
    """Return the canonical predicate for an imported Media payload.

    The lineage/history UI treats payloads with no generation metadata as
    imports, as well as externally generated files whose metadata was
    normalized during ingestion. This deliberately does not inspect storage
    location: legacy Stimma generations may still be path-backed.
    """
    safe_metadata = case(
        (func.json_valid(MediaItem.generation_metadata) == 1, MediaItem.generation_metadata),
        else_='{}',
    )
    return or_(
        MediaItem.generation_metadata.is_(None),
        func.json_valid(MediaItem.generation_metadata) == 0,
        func.coalesce(func.json_extract(safe_metadata, '$.source'), '') == 'external',
        func.coalesce(func.json_extract(safe_metadata, '$.task_type'), '') == 'imported',
    )


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
    is_imported: Optional[bool] = None,
    marker_ids: Optional[str] = None,
    excluded_marker_ids: Optional[str] = None,
    tag_ids: Optional[str] = None,
    excluded_tag_ids: Optional[str] = None,
    project_ids: Optional[str] = None,
    excluded_project_ids: Optional[str] = None,
    has_project: Optional[bool] = None,
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
    exclude_expired: bool = True,
    include_ephemeral: bool = False,
    exclude_category: Optional[str] = None,
    asset_id_column=None,
    expiration_column=None,
):
    """
    Apply filters to a query, optionally excluding a specific filter category.

    This is the single source of truth for media filter semantics. All browser-screen
    endpoints (library, trash, project views, find-index, filter-counts) should route
    through here so a filter only has to be implemented once.

    Args:
        query: SQLAlchemy query to apply filters to
        exclude_category: Category to exclude from filtering ('media_types', 'resolutions', 'keywords', 'folders', 'tags', 'projects', 'tools', 'imported')
        project_ids: Comma-separated project IDs; item must belong to at least one (OR logic).
        excluded_project_ids: Comma-separated project IDs; item must NOT belong to any of them.
        has_project: Tri-state membership predicate — True = in at least one (non-deleted) project,
            False = in no project (the "library only" case), None = no constraint. Memberships that
            point at a soft-deleted project don't count, so deleting a project releases its media
            back into "not in any project".
        exclude_expired: When True (default), hide items the auto-delete worker is due to remove so
            expired generations disappear at their deadline even before the worker runs. Trash opts
            out (exclude_expired=False) since it intentionally surfaces already-removed items.
        include_ephemeral: When False (default), hide ephemeral media (rows produced by one-shot
            flow-as-tool runs, tagged with ephemeral_run_id). These never belong in any user-facing
            view; this single filter covers /api/media, trash, find-index, and similar-search.
        asset_id_column: Asset identity for organization predicates. If omitted,
            the current Media row is resolved through its AssetRevision. Bare
            Media has no marker/tag/project organization state.
        Other args: Filter parameters matching /api/media endpoint

    Returns:
        Filtered query
    """
    # Organization is exclusively Asset-level. Compatibility queries that are
    # still rooted in Media resolve the Media payload to its stable Asset here;
    # bare contextual Media therefore cannot acquire browser organization state.
    organization_asset_id = asset_id_column
    if organization_asset_id is None:
        organization_asset_id = (
            select(AssetRevision.asset_id)
            .where(
                AssetRevision.primary_media_id == MediaItem.id,
                AssetRevision.deleted_at.is_(None),
            )
            .correlate(MediaItem)
            .limit(1)
            .scalar_subquery()
        )

    # Ephemeral media (one-shot flow-as-tool run intermediates) are never surfaced to the user.
    # This sits beside the deleted_at filter the callers apply so no browse/search/trash view leaks them.
    if not include_ephemeral:
        query = query.where(MediaItem.ephemeral_run_id.is_(None))

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

    # Import provenance filter. Keep this aligned with the lineage/history UI,
    # not with external-source or managed-storage placement.
    if exclude_category != 'imported' and is_imported is not None:
        imported_predicate = media_is_imported()
        query = query.where(imported_predicate if is_imported else ~imported_predicate)

    # Marker filter (OR logic - item must have at least one of the specified markers)
    # Excludes suppressed markers (source != 'suppressed')
    if marker_ids:
        marker_id_list = [int(mid.strip()) for mid in marker_ids.split(',') if mid.strip()]
        if marker_id_list:
            marker_exists = select(1).select_from(AssetMarker).where(
                AssetMarker.asset_id == organization_asset_id,
                AssetMarker.marker_id.in_(marker_id_list),
                AssetMarker.source != 'suppressed',
                AssetMarker.deleted_at.is_(None),
            ).correlate_except(AssetMarker).exists()
            query = query.where(marker_exists)

    # Excluded marker filter (item must NOT have any of the specified markers)
    # Only considers visible markers (not suppressed)
    if excluded_marker_ids:
        excluded_marker_id_list = [int(mid.strip()) for mid in excluded_marker_ids.split(',') if mid.strip()]
        if excluded_marker_id_list:
            marker_exists = select(1).select_from(AssetMarker).where(
                AssetMarker.asset_id == organization_asset_id,
                AssetMarker.marker_id.in_(excluded_marker_id_list),
                AssetMarker.source != 'suppressed',
                AssetMarker.deleted_at.is_(None),
            ).correlate_except(AssetMarker).exists()
            query = query.where(~marker_exists)

    # Tag filter (OR logic - item must have at least one of the specified tags)
    if exclude_category != 'tags':
        if tag_ids:
            tag_id_list = [int(tid.strip()) for tid in tag_ids.split(',') if tid.strip()]
            if tag_id_list:
                tag_exists = select(1).select_from(AssetTag).where(
                    AssetTag.asset_id == organization_asset_id,
                    AssetTag.tag_id.in_(tag_id_list),
                    AssetTag.deleted_at.is_(None),
                ).correlate_except(AssetTag).exists()
                query = query.where(tag_exists)

        if excluded_tag_ids:
            excluded_tag_id_list = [int(tid.strip()) for tid in excluded_tag_ids.split(',') if tid.strip()]
            if excluded_tag_id_list:
                tag_exists = select(1).select_from(AssetTag).where(
                    AssetTag.asset_id == organization_asset_id,
                    AssetTag.tag_id.in_(excluded_tag_id_list),
                    AssetTag.deleted_at.is_(None),
                ).correlate_except(AssetTag).exists()
                query = query.where(~tag_exists)

    # Project membership filter. Specific project include/exclude work like tags; has_project is a
    # tri-state existence predicate (in any project / in no project). Soft-deleted projects never
    # count toward membership, so a deleted project releases its media back to "not in any project".
    if exclude_category != 'projects':
        if project_ids:
            project_id_list = [int(pid.strip()) for pid in project_ids.split(',') if pid.strip()]
            if project_id_list:
                project_subquery = select(ProjectAsset.asset_id).join(
                    Project, Project.id == ProjectAsset.project_id
                ).where(
                    ProjectAsset.project_id.in_(project_id_list),
                    Project.deleted_at.is_(None),
                    ProjectAsset.deleted_at.is_(None),
                ).distinct()
                query = query.where(organization_asset_id.in_(project_subquery))

        if excluded_project_ids:
            excluded_project_id_list = [int(pid.strip()) for pid in excluded_project_ids.split(',') if pid.strip()]
            if excluded_project_id_list:
                excluded_project_subquery = select(ProjectAsset.asset_id).join(
                    Project, Project.id == ProjectAsset.project_id
                ).where(
                    ProjectAsset.project_id.in_(excluded_project_id_list),
                    Project.deleted_at.is_(None),
                    ProjectAsset.deleted_at.is_(None),
                ).distinct()
                query = query.where(organization_asset_id.notin_(excluded_project_subquery))

        if has_project is not None:
            # correlate(MediaItem) keeps this EXISTS pinned to the outer row even when the enclosing
            # query joins project_media itself (e.g. the filter-counts facet queries).
            membership_exists = (
                select(1).select_from(ProjectAsset)
                .join(Project, Project.id == ProjectAsset.project_id)
                .where(
                    ProjectAsset.asset_id == organization_asset_id,
                    Project.deleted_at.is_(None),
                    ProjectAsset.deleted_at.is_(None),
                )
                .correlate_except(ProjectAsset, Project)
                .exists()
            )
            query = query.where(membership_exists if has_project else ~membership_exists)

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
    if exclude_category != "date_ranges":
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

    # Expiration is exclusively an Asset lifecycle property. Media-only views
    # have no expiring population.
    expires_at = expiration_column
    if exclude_category != "expiring":
        if show_expiring and expires_at is not None:
            query = query.where(expires_at.isnot(None))
        elif show_expiring:
            query = query.where(false())
        if exclude_expiring and expires_at is not None:
            query = query.where(expires_at.is_(None))

    # Direct megapixel range (legacy: only meaningful when `resolutions` is not used)
    if min_mp is not None:
        query = query.where(MediaItem.megapixels >= min_mp)
    if max_mp is not None:
        query = query.where(MediaItem.megapixels <= max_mp)

    return query
