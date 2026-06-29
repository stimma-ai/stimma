"""Utilities for resolving references in structured media files (sets, grids, markdown)."""
import asyncio
import hashlib
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime as dt
from pathlib import Path
from typing import Optional, Any, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import MediaItem
from generation_metadata import dump_generation_metadata
from utils.query_builder import not_due_for_autodelete
from core.logging import get_logger

log = get_logger(__name__)


# Per-media-item modification locks to prevent concurrent corruption
# Uses reference counting to clean up locks when no longer in use
_modification_locks: dict[int, asyncio.Lock] = {}
_lock_refcounts: dict[int, int] = {}
_locks_lock = asyncio.Lock()


@asynccontextmanager
async def _get_modification_lock(media_id: int):
    """
    Get or create a lock for modifying a specific set/grid.

    Uses reference counting to clean up locks when no longer in use.
    """
    async with _locks_lock:
        if media_id not in _modification_locks:
            _modification_locks[media_id] = asyncio.Lock()
            _lock_refcounts[media_id] = 0
        _lock_refcounts[media_id] += 1
        lock = _modification_locks[media_id]

    try:
        async with lock:
            yield
    finally:
        async with _locks_lock:
            _lock_refcounts[media_id] -= 1
            if _lock_refcounts[media_id] == 0:
                del _modification_locks[media_id]
                del _lock_refcounts[media_id]


def _compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    with open(file_path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _is_cache_valid(media_item: MediaItem) -> bool:
    """
    Check if cached raw_metadata is still valid by comparing file hash.

    Returns True if the stored file_hash matches the actual file on disk,
    meaning the cache is still valid.
    """
    if not media_item.file_hash:
        return False

    file_path = Path(media_item.file_path)
    if not file_path.exists():
        return False

    try:
        actual_hash = _compute_file_hash(file_path)
        return actual_hash == media_item.file_hash
    except Exception as e:
        log.warning(f"Failed to validate cache for media {media_item.id}: {e}")
        return False


async def read_composite_content(
    session: AsyncSession,
    media_item: MediaItem,
    *,
    skip_cache_validation: bool = False,
) -> Optional[dict]:
    """
    Read set/grid content, using cache if valid, disk otherwise.

    This is the canonical way to read composite media content. It:
    1. Checks if raw_metadata cache is valid (file_hash matches)
    2. If valid, returns cached content
    3. If invalid/missing, reads from disk and heals the cache

    Args:
        session: Database session (used for cache healing)
        media_item: The MediaItem to read content from
        skip_cache_validation: If True, trust cache without hash check (for performance
                               in read-only scenarios where we just wrote the file)

    Returns:
        Parsed JSON content dict, or None if reading fails
    """
    file_path = Path(media_item.file_path)
    file_exists = file_path.exists()

    # Quick path: use cache if present and valid
    if media_item.raw_metadata:
        # If file doesn't exist on disk, we must use cache (common in tests)
        # Otherwise, validate cache against disk
        cache_valid = (
            skip_cache_validation or
            not file_exists or  # File missing = trust cache if we have it
            _is_cache_valid(media_item)
        )
        if cache_valid:
            try:
                content = json.loads(media_item.raw_metadata)
                log.debug(f"Cache hit for media {media_item.id}")
                return content
            except json.JSONDecodeError:
                log.warning(f"Invalid JSON in raw_metadata for media {media_item.id}, reading from disk")

    # Cache invalid or missing: read from disk
    if not file_exists:
        log.warning(f"Composite file not found: {file_path}")
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = json.load(f)
        log.debug(f"Cache miss for media {media_item.id}, read from disk and healing cache")
    except Exception as e:
        log.error(f"Failed to read composite content from disk for media {media_item.id}: {e}")
        return None

    # Heal the cache (update raw_metadata and file_hash)
    try:
        new_hash = _compute_file_hash(file_path)
        stat_info = file_path.stat()

        media_item.raw_metadata = json.dumps(content)
        media_item.file_hash = new_hash
        media_item.file_size = stat_info.st_size
        media_item.modified_date = dt.fromtimestamp(stat_info.st_mtime)

        # Note: We don't commit here - the caller should commit
        log.info(f"Healed cache for media {media_item.id} (hash: {new_hash[:8]}...)")
    except Exception as e:
        log.warning(f"Failed to heal cache for media {media_item.id}: {e}")
        # Still return content even if cache healing failed

    return content


async def write_composite_content(
    session: AsyncSession,
    media_item: MediaItem,
    content: dict,
) -> None:
    """
    Write content to disk AND update cache atomically.

    This is the canonical way to modify composite media. It:
    1. Writes content to disk
    2. Computes new file hash
    3. Updates raw_metadata, file_hash, file_size, modified_date

    The caller is responsible for:
    - Acquiring the modification lock via _get_modification_lock()
    - Committing the session after this call

    Args:
        session: Database session
        media_item: The MediaItem to update
        content: The new content dict to write
    """
    file_path = Path(media_item.file_path)

    # Write to disk
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(content, f, indent=2)

    # Compute new file hash
    file_hash = _compute_file_hash(file_path)

    # Get updated file stats
    stat_info = file_path.stat()

    # Update DB cache
    media_item.raw_metadata = json.dumps(content)
    media_item.file_hash = file_hash
    media_item.file_size = stat_info.st_size
    media_item.modified_date = dt.fromtimestamp(stat_info.st_mtime)

    log.debug(f"Wrote composite content for media {media_item.id} (hash: {file_hash[:8]}...)")


# Regex to match markdown image syntax: ![alt](path)
MARKDOWN_IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')


def parse_structured_content(raw_metadata: str) -> Optional[dict]:
    """
    Parse raw_metadata JSON string into a dictionary.
    Returns None if parsing fails.
    """
    if not raw_metadata:
        return None
    try:
        return json.loads(raw_metadata)
    except (json.JSONDecodeError, TypeError) as e:
        log.warning(f"Failed to parse structured content: {e}")
        return None


def resolve_path(base_path: Path, ref_path: str) -> Path:
    """
    Resolve a path reference relative to a base file's directory.

    - Relative paths (./foo, ../bar, foo/bar) resolve from base_path's directory
    - Absolute paths (/foo/bar) are used as-is
    """
    ref = Path(ref_path)

    if ref.is_absolute():
        return ref

    # Resolve relative to the base file's parent directory
    return (base_path.parent / ref).resolve()


async def resolve_set_references(
    session: AsyncSession,
    content: dict,
    base_path: Path
) -> dict:
    """
    Resolve file references in a set to their corresponding MediaItems.

    For each item in the set:
    - Resolves the path relative to the set file's location
    - Looks up the MediaItem by file_path
    - Adds 'resolved' field with media item info or null if not found

    Args:
        session: Database session
        content: Parsed set JSON content
        base_path: Path to the .stimmaset.json file

    Returns:
        Updated content dict with resolved references
    """
    result = content.copy()
    items = result.get('items', [])
    resolved_items = []

    for item in items:
        ref_path = item.get('path')
        if not ref_path:
            resolved_items.append({**item, 'resolved': None})
            continue

        # Resolve the path
        full_path = resolve_path(base_path, ref_path)

        # Look up in database
        query = select(MediaItem).where(
            MediaItem.file_path == str(full_path),
            MediaItem.deleted_at.is_(None),
            not_due_for_autodelete(),
        )
        db_result = await session.execute(query)
        media_item = db_result.scalar_one_or_none()

        if media_item:
            resolved_items.append({
                **item,
                'resolved': {
                    'id': media_item.id,
                    'media_id': media_item.id,  # Keep for backwards compat
                    'file_hash': media_item.file_hash,
                    'file_path': media_item.file_path,
                    'file_format': media_item.file_format,
                    'width': media_item.width,
                    'height': media_item.height,
                    'duration': media_item.duration,
                    'vlm_caption': media_item.vlm_caption,
                    'generation_metadata': media_item.generation_metadata,
                    'markers': [],  # Will be populated if needed
                    'tags': [],  # Will be populated if needed
                }
            })
        else:
            log.debug(f"Set reference not found in library: {full_path}")
            resolved_items.append({**item, 'resolved': None})

    result['items'] = resolved_items
    return result


async def resolve_grid_references(
    session: AsyncSession,
    content: dict,
    base_path: Path
) -> dict:
    """
    Resolve file references in a grid to their corresponding MediaItems.

    For each cell in the grid:
    - Resolves the path relative to the grid file's location
    - Looks up the MediaItem by file_path
    - Adds 'resolved' field with media item info or null if not found

    Args:
        session: Database session
        content: Parsed grid JSON content
        base_path: Path to the .stimmagrid.json file

    Returns:
        Updated content dict with resolved references
    """
    result = content.copy()
    cells = result.get('cells', [])
    resolved_cells = []

    for cell in cells:
        ref_path = cell.get('path')
        if not ref_path:
            resolved_cells.append({**cell, 'resolved': None})
            continue

        # Resolve the path
        full_path = resolve_path(base_path, ref_path)

        # Look up in database
        query = select(MediaItem).where(
            MediaItem.file_path == str(full_path),
            MediaItem.deleted_at.is_(None),
            not_due_for_autodelete(),
        )
        db_result = await session.execute(query)
        media_item = db_result.scalar_one_or_none()

        if media_item:
            resolved_cells.append({
                **cell,
                'resolved': {
                    'id': media_item.id,
                    'media_id': media_item.id,  # Keep for backwards compat
                    'file_hash': media_item.file_hash,
                    'file_path': media_item.file_path,
                    'file_format': media_item.file_format,
                    'width': media_item.width,
                    'height': media_item.height,
                    'duration': media_item.duration,
                    'vlm_caption': media_item.vlm_caption,
                    'generation_metadata': media_item.generation_metadata,
                    'markers': [],
                    'tags': [],
                }
            })
        else:
            log.debug(f"Grid reference not found in library: {full_path}")
            resolved_cells.append({**cell, 'resolved': None})

    result['cells'] = resolved_cells
    return result


def extract_markdown_images(content: str) -> list[dict]:
    """
    Extract image references from markdown content.

    Returns list of dicts with 'alt' and 'path' keys for each ![alt](path) found.
    """
    images = []
    for match in MARKDOWN_IMAGE_PATTERN.finditer(content):
        alt_text = match.group(1)
        path = match.group(2)
        images.append({
            'alt': alt_text,
            'path': path
        })
    return images


def is_external_url(path: str) -> bool:
    """Check if a path is an external URL (http/https)."""
    return path.startswith('http://') or path.startswith('https://')


async def resolve_markdown_references(
    session: AsyncSession,
    content: str,
    base_path: Path
) -> list[dict]:
    """
    Resolve markdown image references to their corresponding MediaItems.

    For each image in the markdown:
    - External URLs (http/https) are marked as external, not resolved
    - Relative/absolute paths are resolved to MediaItems if found in library

    Args:
        session: Database session
        content: Markdown content string
        base_path: Path to the .md file

    Returns:
        List of image dicts with 'alt', 'path', 'resolved', and optionally 'external' keys
    """
    images = extract_markdown_images(content)
    resolved_images = []

    for img in images:
        path = img['path']

        # Check if external URL
        if is_external_url(path):
            resolved_images.append({
                **img,
                'resolved': None,
                'external': True
            })
            continue

        # Resolve local path
        full_path = resolve_path(base_path, path)

        # Look up in database
        query = select(MediaItem).where(
            MediaItem.file_path == str(full_path),
            MediaItem.deleted_at.is_(None),
            not_due_for_autodelete(),
        )
        db_result = await session.execute(query)
        media_item = db_result.scalar_one_or_none()

        if media_item:
            resolved_images.append({
                **img,
                'resolved': {
                    'id': media_item.id,
                    'media_id': media_item.id,
                    'file_hash': media_item.file_hash,
                    'file_path': media_item.file_path,
                    'file_format': media_item.file_format,
                    'width': media_item.width,
                    'height': media_item.height,
                    'vlm_caption': media_item.vlm_caption,
                    'generation_metadata': media_item.generation_metadata,
                }
            })
        else:
            log.debug(f"Markdown image reference not found in library: {full_path}")
            resolved_images.append({**img, 'resolved': None})

    return resolved_images


def read_markdown_file(file_path: Path) -> Optional[dict]:
    """
    Read a markdown file from disk and parse frontmatter + content.
    Returns dict with 'frontmatter' and 'content' keys, or None if reading fails.
    """
    try:
        import frontmatter
        with open(file_path, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
        return {
            'frontmatter': dict(post.metadata) if post.metadata else {},
            'content': post.content
        }
    except Exception as e:
        log.warning(f"Failed to read markdown file {file_path}: {e}")
        return None


async def get_structured_content(
    session: AsyncSession,
    media_item: MediaItem
) -> Optional[dict]:
    """
    Get the parsed and resolved content for a structured media item.

    Handles:
    - .md (markdown) - reads from disk, resolves image references to MediaItems
    - .stimmaset.json - resolves item references to MediaItems
    - .stimmagrid.json - resolves cell references to MediaItems

    Returns None for non-structured types or if parsing fails.

    Note: For JSON-based types, this uses read_composite_content() which validates
    the cache and self-heals if needed. The session should be committed by the caller
    if cache healing occurred.
    """
    file_format = media_item.file_format.lower()
    base_path = Path(media_item.file_path)

    if file_format == 'md':
        # Markdown files: read from disk (not database) for fresh content
        parsed = read_markdown_file(base_path)
        if not parsed:
            return None

        frontmatter = parsed.get('frontmatter', {})
        markdown_content = parsed.get('content', '')
        images = await resolve_markdown_references(session, markdown_content, base_path)
        return {
            'format': 'markdown',
            'frontmatter': frontmatter,
            'content': markdown_content,
            'images': images
        }

    # For JSON-based types, use centralized read with cache validation
    if file_format in ('stimmaset.json', 'stimmagrid.json'):
        content = await read_composite_content(session, media_item)
        if not content:
            return None

        if file_format == 'stimmaset.json':
            return await resolve_set_references(session, content, base_path)
        else:
            return await resolve_grid_references(session, content, base_path)

    return None


async def create_batch_output_set(
    session: AsyncSession,
    folder_path: str,
    batch_id: str,
    first_item_path: str,
    title: Optional[str] = None,
) -> MediaItem:
    """
    Create an initial output set for batch processing with the first completed item.

    Args:
        session: Database session
        folder_path: Folder where the set file should be created
        batch_id: Unique batch ID for this batch of jobs
        first_item_path: File path of the first completed result
        title: Optional title for the set

    Returns:
        The created MediaItem for the set
    """
    from config_version import get_config_version_manager
    from utils.websocket import ws_manager

    output_folder = Path(folder_path)
    output_folder.mkdir(parents=True, exist_ok=True)

    # Generate a unique filename
    timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
    base_name = title.replace(" ", "_").replace("/", "-")[:50] if title else "batch_output"
    filename = f"{base_name}_{timestamp}.stimmaset.json"
    set_file_path = output_folder / filename

    # Ensure unique filename
    counter = 1
    while set_file_path.exists():
        filename = f"{base_name}_{timestamp}_{counter}.stimmaset.json"
        set_file_path = output_folder / filename
        counter += 1

    # Build the initial set content with relative path if possible
    first_item = Path(first_item_path)
    if first_item.parent == output_folder:
        path_str = first_item.name
    else:
        try:
            rel_path = first_item.relative_to(output_folder)
            path_str = str(rel_path)
        except ValueError:
            path_str = str(first_item)

    set_data = {
        "version": 1,
        "items": [{"path": path_str}],
    }
    if title:
        set_data["title"] = title

    # Write the file
    with open(set_file_path, 'w', encoding='utf-8') as f:
        json.dump(set_data, f, indent=2)

    # Compute file hash
    with open(set_file_path, 'rb') as f:
        file_content = f.read()
    file_hash = hashlib.sha256(file_content).hexdigest()

    # Get file stats
    stat_info = set_file_path.stat()

    # Create MediaItem for the set
    set_media_item = MediaItem(
        file_path=str(set_file_path),
        file_hash=file_hash,
        file_size=stat_info.st_size,
        file_format='stimmaset.json',
        created_date=dt.utcfromtimestamp(stat_info.st_ctime),
        modified_date=dt.utcfromtimestamp(stat_info.st_mtime),
        indexed_date=dt.utcnow(),
        metadata_status='completed',
        metadata_processed_at=dt.utcnow(),
        metadata_config_version=get_config_version_manager().get_version('metadata'),
        width=0,
        height=0,
        megapixels=0,
        raw_metadata=json.dumps(set_data),
        # Note: vlm_caption is intentionally NOT set for sets - it's for AI captions of visual media
        generation_metadata=dump_generation_metadata(
            task_type='batch-output',
            source='batch',
            extra={'batch_id': batch_id},
        ),
    )

    session.add(set_media_item)
    await session.commit()
    await session.refresh(set_media_item)

    # Broadcast media_added for the new set
    await ws_manager.broadcast('media_added', {
        'media_id': set_media_item.id,
        'count': 1
    })

    log.info(f"Created batch output set {set_media_item.id} for batch {batch_id}")
    return set_media_item


async def append_to_set(
    session: AsyncSession,
    set_media_id: int,
    new_item_path: str,
) -> MediaItem:
    """
    Append a new item to an existing set.

    Uses per-set locking to prevent race conditions when multiple batch jobs
    complete concurrently. Reads current content, appends item, and atomically
    updates both disk and database.

    Args:
        session: Database session
        set_media_id: ID of the set MediaItem to append to
        new_item_path: File path of the new item to add

    Returns:
        The updated set MediaItem
    """
    from utils.websocket import broadcast_media_updated

    # Get the set MediaItem
    result = await session.execute(
        select(MediaItem).where(
            MediaItem.id == set_media_id,
            MediaItem.deleted_at.is_(None)
        )
    )
    set_item = result.scalar_one_or_none()

    if not set_item:
        raise ValueError(f"Set MediaItem {set_media_id} not found")

    if set_item.file_format != 'stimmaset.json':
        raise ValueError(f"MediaItem {set_media_id} is not a set (format: {set_item.file_format})")

    # Validate item is not a structured media type (no nesting) - check before acquiring lock
    if new_item_path.endswith('.stimmaset.json') or new_item_path.endswith('.stimmagrid.json'):
        raise ValueError(f"Cannot add structured media to a set (nested sets/grids not allowed)")

    set_file_path = Path(set_item.file_path)
    output_folder = set_file_path.parent

    # Use locking to prevent concurrent modification race conditions
    async with _get_modification_lock(set_media_id):
        # Read current content (with cache validation - always read fresh inside lock)
        set_data = await read_composite_content(session, set_item)
        if not set_data:
            raise ValueError(f"Failed to read set content for {set_media_id}")

        # Compute path for new item (relative if possible)
        new_item = Path(new_item_path)
        if new_item.parent == output_folder:
            path_str = new_item.name
        else:
            try:
                rel_path = new_item.relative_to(output_folder)
                path_str = str(rel_path)
            except ValueError:
                path_str = str(new_item)

        # Append new item
        set_data['items'].append({"path": path_str})
        item_count = len(set_data['items'])

        # Write back atomically (updates disk + DB cache)
        await write_composite_content(session, set_item, set_data)

    # Note: vlm_caption is intentionally NOT set for sets - it's for AI captions of visual media

    await session.commit()
    await session.refresh(set_item)

    # Broadcast media_updated
    await broadcast_media_updated([set_item], ["file_hash", "file_size", "raw_metadata", "vlm_caption"], session)

    log.debug(f"Appended item to set {set_media_id}, now has {item_count} items")
    return set_item


async def reorder_set_items(
    session: AsyncSession,
    set_media_id: int,
    ordered_paths: List[str],
) -> MediaItem:
    """
    Reorder items in a set to match a specific order.

    Used by batch processing to ensure output items appear in the same order
    as input items, regardless of job completion order.

    Args:
        session: Database session
        set_media_id: ID of the set MediaItem to reorder
        ordered_paths: List of file paths in the desired order

    Returns:
        The updated set MediaItem
    """
    from utils.websocket import broadcast_media_updated

    # Get the set MediaItem
    result = await session.execute(
        select(MediaItem).where(
            MediaItem.id == set_media_id,
            MediaItem.deleted_at.is_(None)
        )
    )
    set_item = result.scalar_one_or_none()

    if not set_item:
        raise ValueError(f"Set MediaItem {set_media_id} not found")

    if set_item.file_format != 'stimmaset.json':
        raise ValueError(f"MediaItem {set_media_id} is not a set (format: {set_item.file_format})")

    set_file_path = Path(set_item.file_path)
    output_folder = set_file_path.parent

    # Use locking to prevent concurrent modification
    async with _get_modification_lock(set_media_id):
        # Read current content
        set_data = await read_composite_content(session, set_item)
        if not set_data:
            raise ValueError(f"Failed to read set content for {set_media_id}")

        # Build a map of path -> item for quick lookup
        # Normalize paths to handle relative vs absolute
        current_items = {}
        for item in set_data.get('items', []):
            item_path = item.get('path', '')
            # Store both relative and absolute forms for matching
            current_items[item_path] = item
            # If it's a relative path, also store the absolute version
            if not Path(item_path).is_absolute():
                abs_path = str(output_folder / item_path)
                current_items[abs_path] = item

        # Reorder items based on ordered_paths
        reordered_items = []
        for path in ordered_paths:
            # Try to find the item by path (could be relative or absolute)
            item = current_items.get(path)
            if not item:
                # Try converting to relative
                try:
                    rel_path = str(Path(path).relative_to(output_folder))
                    item = current_items.get(rel_path)
                except ValueError:
                    pass
            if not item:
                # Try just the filename
                item = current_items.get(Path(path).name)

            if item:
                reordered_items.append(item)
            else:
                log.warning(f"Could not find item for path {path} when reordering set {set_media_id}")

        # Only update if we successfully matched all items
        if len(reordered_items) == len(set_data.get('items', [])):
            set_data['items'] = reordered_items
            # Write back atomically
            await write_composite_content(session, set_item, set_data)
            log.info(f"Reordered set {set_media_id} with {len(reordered_items)} items")
        else:
            log.warning(f"Set {set_media_id} reorder skipped: matched {len(reordered_items)} of {len(set_data.get('items', []))} items")

    await session.commit()
    await session.refresh(set_item)

    # Broadcast media_updated
    await broadcast_media_updated([set_item], ["file_hash", "file_size", "raw_metadata"], session)

    return set_item


async def get_set_item_ids(
    session: AsyncSession,
    set_media_id: int,
) -> List[int]:
    """
    Get the media IDs of all items in a set.

    Args:
        session: Database session
        set_media_id: ID of the set MediaItem

    Returns:
        List of media IDs for items in the set
    """
    # Get the set MediaItem
    result = await session.execute(
        select(MediaItem).where(
            MediaItem.id == set_media_id,
            MediaItem.deleted_at.is_(None)
        )
    )
    set_item = result.scalar_one_or_none()

    if not set_item:
        raise ValueError(f"Set MediaItem {set_media_id} not found")

    if set_item.file_format != 'stimmaset.json':
        raise ValueError(f"MediaItem {set_media_id} is not a set (format: {set_item.file_format})")

    # Use centralized read with cache validation
    set_data = await read_composite_content(session, set_item)
    if not set_data:
        raise ValueError(f"Failed to read set content for {set_media_id}")

    # Resolve each item to get media IDs
    set_file_path = Path(set_item.file_path)
    media_ids = []
    for item in set_data.get('items', []):
        # First check if we have resolved data with the ID
        resolved = item.get('resolved')
        if resolved and 'id' in resolved:
            media_ids.append(resolved['id'])
            continue

        # Fall back to path-based lookup
        ref_path = item.get('path')
        if not ref_path:
            continue

        full_path = resolve_path(set_file_path, ref_path)

        # Look up in database
        query = select(MediaItem.id).where(
            MediaItem.file_path == str(full_path),
            MediaItem.deleted_at.is_(None)
        )
        db_result = await session.execute(query)
        media_id = db_result.scalar_one_or_none()

        if media_id:
            media_ids.append(media_id)

    return media_ids


def get_set_content_type(set_data: dict) -> Optional[str]:
    """
    Determine the content type of a set based on its items.

    Args:
        set_data: Parsed set JSON content with resolved items

    Returns:
        'image', 'video', 'audio', 'document', or None if mixed/unknown
    """
    items = set_data.get('items', [])
    if not items:
        return None

    content_types = set()
    for item in items:
        resolved = item.get('resolved')
        if not resolved:
            continue

        file_format = resolved.get('file_format', '').lower()

        # Map file formats to content types
        if file_format in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'heic', 'heif'):
            content_types.add('image')
        elif file_format in ('mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v'):
            content_types.add('video')
        elif file_format in ('mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg', 'opus'):
            content_types.add('audio')
        elif file_format in ('pdf', 'doc', 'docx', 'txt', 'md'):
            content_types.add('document')

    # Return type if uniform, None if mixed
    if len(content_types) == 1:
        return content_types.pop()
    return None


async def update_set_title(
    session: AsyncSession,
    set_media_id: int,
    new_title: str,
) -> MediaItem:
    """
    Update a set's title in both the JSON file and database.

    Uses per-set locking to prevent race conditions with concurrent modifications.

    Args:
        session: Database session
        set_media_id: ID of the set MediaItem to update
        new_title: New title for the set

    Returns:
        The updated set MediaItem
    """
    from utils.websocket import broadcast_media_updated

    # Get the set MediaItem
    result = await session.execute(
        select(MediaItem).where(
            MediaItem.id == set_media_id,
            MediaItem.deleted_at.is_(None)
        )
    )
    set_item = result.scalar_one_or_none()

    if not set_item:
        raise ValueError(f"Set MediaItem {set_media_id} not found")

    if set_item.file_format != 'stimmaset.json':
        raise ValueError(f"MediaItem {set_media_id} is not a set (format: {set_item.file_format})")

    # Use locking to prevent concurrent modification race conditions
    async with _get_modification_lock(set_media_id):
        # Read current content (with cache validation)
        set_data = await read_composite_content(session, set_item)
        if not set_data:
            raise ValueError(f"Failed to read set content for {set_media_id}")

        # Update the title
        set_data['title'] = new_title
        item_count = len(set_data.get('items', []))

        # Write back atomically (updates disk + DB cache)
        await write_composite_content(session, set_item, set_data)

    # Note: vlm_caption is intentionally NOT set for sets - it's for AI captions of visual media

    await session.commit()
    await session.refresh(set_item)

    # Broadcast media_updated
    await broadcast_media_updated([set_item], ["file_hash", "file_size", "raw_metadata", "vlm_caption"], session)

    log.info(f"Updated set {set_media_id} title to: {new_title}")
    return set_item


async def generate_smart_batch_title(
    session: AsyncSession,
    tool_name: str,
    task_type: str,
    input_set_ids: Optional[List[int]] = None,
    sample_media_ids: Optional[List[int]] = None,
) -> Optional[str]:
    """
    Generate a smart title for a batch output set using LLM.

    Uses input set names and/or sample prompts from media items to generate
    a descriptive, short title.

    Args:
        session: Database session
        tool_name: Name of the tool used (e.g., "Image Upscale")
        task_type: Type of task (e.g., "upscale", "text-to-image")
        input_set_ids: IDs of input sets (to get their titles)
        sample_media_ids: IDs of media items to sample prompts from (up to 5)

    Returns:
        Generated title string, or None if generation fails
    """
    from llm import llm_complete_text
    from llm_resolver import get_effective_llm_config

    try:
        # Gather context for title generation
        context_parts = []

        log.info(f"SMART TITLE: Gathering context - input_set_ids={input_set_ids}, sample_media_ids={sample_media_ids}")

        # Get input set titles
        if input_set_ids:
            for set_id in input_set_ids[:3]:  # Max 3 input sets
                result = await session.execute(
                    select(MediaItem).where(
                        MediaItem.id == set_id,
                        MediaItem.deleted_at.is_(None)
                    )
                )
                set_item = result.scalar_one_or_none()
                log.info(f"SMART TITLE: Input set {set_id} - found={set_item is not None}, has_metadata={set_item.raw_metadata is not None if set_item else False}")
                if set_item and set_item.raw_metadata:
                    try:
                        set_data = json.loads(set_item.raw_metadata)
                        title = set_data.get('title')
                        log.info(f"SMART TITLE: Input set {set_id} title='{title}'")
                        if title and title != 'Untitled':
                            context_parts.append(f"Input set: \"{title}\"")
                    except json.JSONDecodeError:
                        pass

        # Get prompts from INPUT set items (not results) - these are the original images being processed
        if input_set_ids and not context_parts:
            prompts = []
            for set_id in input_set_ids[:1]:  # Just use first input set
                # Get items from the input set
                input_item_ids = await get_set_item_ids(session, set_id)
                log.info(f"SMART TITLE: Input set {set_id} has {len(input_item_ids)} items")
                for media_id in input_item_ids[:5]:  # Max 5 samples
                    result = await session.execute(
                        select(MediaItem.generation_metadata).where(
                            MediaItem.id == media_id,
                            MediaItem.deleted_at.is_(None)
                        )
                    )
                    gen_meta_str = result.scalar_one_or_none()
                    if gen_meta_str:
                        try:
                            gen_meta = json.loads(gen_meta_str)
                            prompt = gen_meta.get('prompt') or gen_meta.get('parameters', {}).get('prompt')
                            log.info(f"SMART TITLE: Input item {media_id} prompt={prompt[:50] if prompt else None}...")
                            if prompt and len(prompt) > 10:
                                # Truncate long prompts
                                prompts.append(prompt[:200] if len(prompt) > 200 else prompt)
                        except json.JSONDecodeError:
                            pass
                    else:
                        log.info(f"SMART TITLE: Input item {media_id} has no generation_metadata")

            if prompts:
                context_parts.append("Sample prompts from input images:")
                for i, p in enumerate(prompts[:3], 1):
                    context_parts.append(f"  {i}. \"{p}\"")

        # If no context available, return None (keep default title)
        if not context_parts:
            log.info(f"SMART TITLE: No context available for title generation")
            return None

        # Build the prompt
        context = "\n".join(context_parts)

        log.info(f"SMART TITLE: Calling LLM with context: {context}")

        # Get LLM config
        llm_config = await get_effective_llm_config('agent-fast')
        log.info(f"SMART TITLE: Using LLM model: {llm_config.get_model()}")

        system_prompt = "You generate short titles (2-5 words). Reply with ONLY the title, no quotes or punctuation."
        user_prompt = f"""Generate a title for batch {task_type} results.

Tool: {tool_name}
{context}

The title should describe the CONTENT (e.g., "Upscaled Hummingbirds" not "Batch Results").

Title:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        result = await llm_complete_text(
            config=llm_config,
            messages=messages,
            max_tokens=1024,
            temperature=0.3,
        )

        log.info(f"SMART TITLE: LLM returned: '{result}'")

        if result:
            # Clean up the result
            title = result.strip().strip('"\'').strip()
            # Validate it's reasonable
            if title and 1 <= len(title.split()) <= 8 and len(title) <= 60:
                log.info(f"Generated smart batch title: {title}")
                return title
            else:
                log.warning(f"Generated title rejected (invalid format): '{title}'")

        return None

    except Exception as e:
        log.warning(f"Failed to generate smart batch title: {e}")
        return None
