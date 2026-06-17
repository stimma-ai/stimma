"""Media file serving routes (thumbnails and original files)."""
import asyncio
import os
import uuid
from typing import Optional, List
from core.logging import get_logger
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from queue import LifoQueue
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from PIL import Image, ImageOps
import io
import json
import hashlib

from pydantic import BaseModel
from database import Face, MediaItem, MediaLineage, MediaMarker, MediaThumbnailCache
from core.dependencies import get_db_session
from core.profile_context import get_current_profile, set_current_profile
from database_registry import get_database_registry
from config import get_settings
import metadata_embed

router = APIRouter(prefix="/api", tags=["media_files"])


# Cache headers for immutable content (db_guid in URL makes it globally unique)
# Note: CORS headers are added here because FileResponse doesn't always get
# processed by the CORS middleware correctly in all contexts (e.g., image loading
# from cross-origin in Tauri dev mode)
CACHE_HEADERS = {
    'Cache-Control': 'public, max-age=31536000, immutable',
    'X-Content-Type-Options': 'nosniff',
    'Access-Control-Allow-Origin': '*',
}

THEMED_FORMATS = {'md', 'stimmaset.json', 'stimmagrid.json', 'stimmalayout', 'mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg'}


def _sharded_cache_path(cache_dir: Path, cache_key: str, ext: str) -> Path:
    """Return a sharded path: cache_dir/ab/cd/cache_key.ext using the first 4 hex chars."""
    return cache_dir / cache_key[:2] / cache_key[2:4] / f"{cache_key}.{ext}"


async def _record_thumbnail_cache(session: AsyncSession, media_id: int, cache_path: Path) -> None:
    stmt = sqlite_insert(MediaThumbnailCache).values(
        media_id=media_id,
        cache_path=str(cache_path),
    ).on_conflict_do_nothing(index_elements=['media_id', 'cache_path'])
    await session.execute(stmt)
    await session.commit()

THEME_PALETTES = {
    'dark': {
        'set_bg': '#181818', 'set_card_border': '#000000',
        'grid_bg': '#181818', 'grid_accent': '#06b6d4', 'grid_empty_fill': '#2a2a3e',
        'text_bg': '#1e293b', 'text_title': '#f1f5f9', 'text_separator': '#475569', 'text_body': '#94a3b8',
        'audio_bg': '#1a1a2e', 'audio_fallback_icon': '#9333ea',
        'placeholder_set_bg': '#1a1a2e', 'placeholder_grid_bg': '#1a1a2e', 'placeholder_default_bg': '#1f2937',
    },
    'light': {
        'set_bg': '#f4f4f5', 'set_card_border': '#d4d4d8',
        'grid_bg': '#f4f4f5', 'grid_accent': '#0891b2', 'grid_empty_fill': '#e4e4e7',
        'text_bg': '#f1f5f9', 'text_title': '#1e293b', 'text_separator': '#cbd5e1', 'text_body': '#475569',
        'audio_bg': '#f0f0ff', 'audio_fallback_icon': '#7c3aed',
        'placeholder_set_bg': '#f0f0ff', 'placeholder_grid_bg': '#f0f0ff', 'placeholder_default_bg': '#f1f5f9',
    },
}


async def get_db_session_by_guid(db_guid: str):
    """
    Dependency to get database session by db_guid.
    Resolves db_guid to profile and sets profile context.
    """
    registry = get_database_registry()
    profile_id = registry.get_profile_by_db_guid(db_guid)

    if not profile_id:
        raise HTTPException(status_code=404, detail=f"Unknown database: {db_guid}")

    # Set the profile context for this request
    set_current_profile(profile_id)

    db = registry.get_database(profile_id)
    async for session in db.get_session():
        yield session


log = get_logger(__name__)

# Suppress WeasyPrint's CSS warnings (unsupported properties like box-shadow,
# viewport units) and image-load errors — these are expected during thumbnail
# generation and not actionable.
import logging as _logging
_logging.getLogger('weasyprint').setLevel(_logging.CRITICAL)


class LifoThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor that processes newest requests first (LIFO).

    This improves thumbnail loading UX when jumping to distant scroll positions -
    visible items get processed first while scrolled-past items sink to the back.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._work_queue = LifoQueue()


# Global thread pool for thumbnail generation (LIFO so newest requests processed first)
thumbnail_executor = LifoThreadPoolExecutor(max_workers=16, thread_name_prefix="thumbnail")

def _generate_audio_waveform(file_path: str, size: int, palette=None) -> Image.Image:
    """Generate a waveform visualization for an audio file."""
    import ffmpeg
    import struct

    palette = palette or THEME_PALETTES['dark']

    try:
        # Get audio samples using ffmpeg
        out, _ = (
            ffmpeg
            .input(str(file_path))
            .output('pipe:', format='s16le', acodec='pcm_s16le', ac=1, ar=8000)
            .run(capture_stdout=True, capture_stderr=True, quiet=True)
        )

        # Parse audio samples
        samples = struct.unpack(f'{len(out)//2}h', out)

        if not samples:
            raise ValueError("No audio samples")

        # Create waveform image
        width = size
        height = size
        img = Image.new('RGB', (width, height), palette['audio_bg'])

        # Calculate number of samples per column
        samples_per_col = max(1, len(samples) // width)

        # Draw waveform
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)

        # Gradient colors for waveform (purple to cyan)
        for x in range(width):
            start_idx = x * samples_per_col
            end_idx = min(start_idx + samples_per_col, len(samples))
            chunk = samples[start_idx:end_idx]

            if chunk:
                # Get max amplitude for this column
                max_amp = max(abs(min(chunk)), abs(max(chunk)))
                normalized = max_amp / 32768  # Normalize to 0-1
                bar_height = int(normalized * (height * 0.8))

                # Center the bar
                y_start = (height - bar_height) // 2
                y_end = y_start + bar_height

                # Color gradient from purple (#9333ea) to cyan (#06b6d4)
                t = x / width
                r = int(147 * (1 - t) + 6 * t)
                g = int(51 * (1 - t) + 182 * t)
                b = int(234 * (1 - t) + 212 * t)

                draw.line([(x, y_start), (x, y_end)], fill=(r, g, b))

        return img

    except Exception as e:
        # Fallback: create a simple music note icon placeholder
        img = Image.new('RGB', (size, size), palette['audio_bg'])
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)

        # Draw simple music note symbol
        center = size // 2
        note_color = palette['audio_fallback_icon']
        draw.ellipse([center - size//6, center - size//6, center + size//6, center + size//6], fill=note_color)

        return img


def _generate_text_preview(file_path: str, size: int, palette=None) -> Image.Image:
    """Generate a styled markdown thumbnail using WeasyPrint (markdown → HTML → image).

    Renders the top of the document at full width, cropped to a square.
    Theme follows the palette parameter (light or dark).
    Falls back to a simple text render if WeasyPrint is unavailable.
    """
    import re
    from pathlib import Path as PathLib

    palette = palette or THEME_PALETTES['dark']
    is_dark = palette is THEME_PALETTES['dark']

    try:
        import frontmatter
        with open(file_path, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
        title = post.metadata.get('title', '') if post.metadata else ''
        content = post.content or ''
    except Exception:
        title = ''
        content = ''

    # Convert markdown to HTML
    try:
        from markdown_it import MarkdownIt
        md = MarkdownIt()
        body_html = md.render(content)
    except ImportError:
        body_html = f'<p>{content[:500]}</p>'

    # Resolve local image paths to absolute file:// URLs so WeasyPrint can load them
    md_dir = PathLib(file_path).parent
    def _resolve_src(match):
        tag_before = match.group(1)
        src = match.group(2)
        tag_after = match.group(3)
        if src.startswith(('http://', 'https://', 'data:', 'file://')):
            return match.group(0)
        resolved = (md_dir / src).resolve()
        if resolved.exists():
            return f'{tag_before}file://{resolved}{tag_after}'
        return match.group(0)
    body_html = re.sub(r'(<img\s[^>]*src=["\'])([^"\']+)(["\'][^>]*>)', _resolve_src, body_html)

    # Theme-aware colors
    if is_dark:
        bg = '#1e293b'; text_color = '#e2e8f0'; title_color = '#f1f5f9'
        muted = '#94a3b8'; border_color = '#475569'; code_bg = '#334155'; link_color = '#60a5fa'
    else:
        bg = '#ffffff'; text_color = '#1e293b'; title_color = '#111827'
        muted = '#6b7280'; border_color = '#d1d5db'; code_bg = '#f1f5f9'; link_color = '#2563eb'

    # Render tall, then crop to square from top — like a screenshot of the doc
    doc_width = 800
    doc_height = doc_width * 3  # Render 3x tall so content has room

    title_html = f'<h1 class="doc-title">{title}</h1>' if title else ''

    html_content = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body>
{title_html}
{body_html}
</body>
</html>'''

    css_string = f'''
    @page {{ size: {doc_width}px {doc_height}px; margin: 0; }}
    body {{
        margin: 0; padding: 48px 56px;
        background: {bg}; color: {text_color};
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        font-size: 16px; line-height: 1.75;
        overflow: hidden;
    }}
    .doc-title {{
        font-size: 2em; font-weight: 600; color: {title_color};
        margin: 0 0 0.5em 0;
    }}
    h1, h2, h3, h4, h5, h6 {{
        color: {title_color}; font-weight: 600;
        margin-top: 1.5em; margin-bottom: 0.5em;
    }}
    h1 {{ font-size: 2em; }} h2 {{ font-size: 1.5em; }} h3 {{ font-size: 1.25em; }}
    p {{ margin-bottom: 1em; }}
    a {{ color: {link_color}; text-decoration: underline; }}
    strong {{ color: {title_color}; font-weight: 600; }}
    code {{
        background: {code_bg}; padding: 0.2em 0.4em;
        border-radius: 0.25rem; font-size: 0.875em;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }}
    pre {{
        background: {code_bg}; border: 1px solid {border_color};
        border-radius: 0.5rem; padding: 1em; overflow: hidden; margin: 1em 0;
    }}
    pre code {{ background: transparent; padding: 0; }}
    ul, ol {{ margin: 1em 0; padding-left: 1.5em; }}
    ul {{ list-style-type: disc; }} ol {{ list-style-type: decimal; }}
    li {{ margin: 0.25em 0; }}
    blockquote {{
        border-left: 4px solid {border_color}; padding-left: 1em;
        margin: 1em 0; color: {muted}; font-style: italic;
    }}
    hr {{ border: none; border-top: 1px solid {border_color}; margin: 2em 0; }}
    img {{ max-width: 100%; height: auto; border-radius: 0.5rem; margin: 1em 0; }}
    table {{ width: 100%; border-collapse: collapse; margin: 1em 0; }}
    th, td {{ border: 1px solid {border_color}; padding: 0.5em 0.75em; text-align: left; }}
    th {{ background: {code_bg}; font-weight: 600; }}
    '''

    try:
        from weasyprint import HTML, CSS
        import pypdfium2 as pdfium

        base_url = str(PathLib(file_path).parent.resolve())

        # Render tall page, then crop to square from top
        page_css = CSS(string=css_string)
        pdf_bytes = HTML(string=html_content, base_url=base_url).write_pdf(
            stylesheets=[page_css],
            presentational_hints=True,
        )
        pdf = pdfium.PdfDocument(pdf_bytes)
        page = pdf[0]
        # Render at 2x for sharp text
        bitmap = page.render(scale=2)
        img = bitmap.to_pil()

        # Crop to square from top (full width), then resize to thumbnail
        w, h = img.size
        img = img.crop((0, 0, w, w))
        img = img.resize((size, size), Image.LANCZOS)
        return img

    except Exception as e:
        log.warning(f"WeasyPrint markdown thumbnail failed for {file_path}: {e}, falling back to simple text")
        # Minimal fallback: plain text thumbnail
        img = Image.new('RGB', (size, size), palette['text_bg'])
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", max(10, size // 16))
        except Exception:
            font = ImageFont.load_default()
        margin = size // 12
        if title:
            draw.text((margin, margin), title[:40], fill=palette['text_title'], font=font)
        return img


def _generate_placeholder_thumbnail(size: int, icon_type: str = 'default', palette=None) -> Image.Image:
    """Generate a placeholder thumbnail for structured types (fallback when no content available)."""
    palette = palette or THEME_PALETTES['dark']

    # Background colors by type
    bg_colors = {
        'set': palette['placeholder_set_bg'],
        'grid': palette['placeholder_grid_bg'],
        'default': palette['placeholder_default_bg'],
    }

    # Icon colors by type
    icon_colors = {
        'set': '#f59e0b',   # Amber
        'grid': '#06b6d4',  # Cyan
        'default': '#6b7280'
    }

    img = Image.new('RGB', (size, size), bg_colors.get(icon_type, bg_colors['default']))

    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    color = icon_colors.get(icon_type, icon_colors['default'])
    center = size // 2
    unit = size // 10

    if icon_type == 'set':
        # Draw stacked rectangles
        for i in range(3):
            offset = i * unit
            draw.rectangle([
                center - 3*unit + offset, center - 2*unit + offset,
                center + 2*unit + offset, center + 3*unit + offset
            ], outline=color, width=max(1, size // 64))
    elif icon_type == 'grid':
        # Draw a 3x3 grid
        for row in range(3):
            for col in range(3):
                x1 = center - 3*unit + col * 2*unit
                y1 = center - 3*unit + row * 2*unit
                draw.rectangle([x1, y1, x1 + unit + unit//2, y1 + unit + unit//2], outline=color, width=max(1, size // 64))
    else:
        # Document icon
        draw.rectangle([center - 2*unit, center - 3*unit, center + 2*unit, center + 3*unit], outline=color, width=max(1, size // 64))
        # Fold corner
        draw.polygon([
            (center + unit, center - 3*unit),
            (center + 2*unit, center - 2*unit),
            (center + unit, center - 2*unit)
        ], fill=color)

    return img


def _generate_set_preview(file_path: str, size: int, palette=None) -> Image.Image:
    """Generate a stacked card preview for a set from its contained media items."""
    import json
    from pathlib import Path as PathLib

    palette = palette or THEME_PALETTES['dark']

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        items = data.get('items', [])
        base_path = PathLib(file_path).parent

        # Collect valid image paths (up to 3 for stacked cards)
        image_paths = []
        for item in items[:3]:
            ref_path = item.get('path')
            if not ref_path:
                continue

            # Resolve relative path
            ref = PathLib(ref_path)
            if ref.is_absolute():
                full_path = ref
            else:
                full_path = (base_path / ref).resolve()

            # Check if it's an image file that exists
            if full_path.exists() and full_path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}:
                image_paths.append(str(full_path))

        if not image_paths:
            # Fall back to placeholder if no valid images
            return _generate_placeholder_thumbnail(size, 'set', palette=palette)

        # Create stacked cards preview
        return _create_stacked_cards(image_paths, size, palette=palette)

    except Exception as e:
        log.warning(f"Failed to generate set preview for {file_path}: {e}")
        return _generate_placeholder_thumbnail(size, 'set', palette=palette)


def _generate_grid_preview(file_path: str, size: int, palette=None) -> Image.Image:
    """Generate a grid preview that reflects the actual grid dimensions."""
    import json
    from pathlib import Path as PathLib

    palette = palette or THEME_PALETTES['dark']

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        cells = data.get('cells', [])
        actual_rows = data.get('rows', 2)
        actual_cols = data.get('cols', 3)
        base_path = PathLib(file_path).parent

        # Build a cell lookup by (row, col) position
        cell_lookup = {}
        for cell in cells:
            row = cell.get('row', 0)
            col = cell.get('col', 0)
            cell_lookup[(row, col)] = cell

        # Determine how many cells to show in the preview
        # Show up to 5 cols and 4 rows fully, plus one more row/col for partial clipping
        max_full_cols = 5
        max_full_rows = 5

        # Calculate what we'll show
        full_cols = min(actual_cols, max_full_cols)
        full_rows = min(actual_rows, max_full_rows)
        has_more_cols = actual_cols > max_full_cols
        has_more_rows = actual_rows > max_full_rows

        # Include one extra row/col if there's more (for the clipped partial cells)
        show_cols = full_cols + (1 if has_more_cols else 0)
        show_rows = full_rows + (1 if has_more_rows else 0)

        def resolve_cell_path(row, col):
            """Resolve a cell's image path, return None if not found."""
            cell = cell_lookup.get((row, col))
            if not cell:
                return None
            ref_path = cell.get('path')
            if not ref_path:
                return None
            ref = PathLib(ref_path)
            if ref.is_absolute():
                full_path = ref
            else:
                full_path = (base_path / ref).resolve()
            if full_path.exists() and full_path.suffix.lower() in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}:
                return str(full_path)
            return None

        # Collect image paths in grid order (including partial row/col)
        image_paths = []
        for row in range(show_rows):
            for col in range(show_cols):
                image_paths.append(resolve_cell_path(row, col))

        if not any(image_paths):
            # Fall back to placeholder if no valid images
            return _generate_placeholder_thumbnail(size, 'grid', palette=palette)

        # Create grid preview with actual dimensions
        return _create_grid_mosaic(
            image_paths, size, palette['grid_accent'],
            grid_cols=show_cols,
            grid_rows=show_rows,
            clip_last_col=has_more_cols,
            clip_last_row=has_more_rows,
            palette=palette,
        )

    except Exception as e:
        log.warning(f"Failed to generate grid preview for {file_path}: {e}")
        return _generate_placeholder_thumbnail(size, 'grid', palette=palette)


def _create_stacked_cards(image_paths: list, size: int, palette=None) -> Image.Image:
    """Create a stacked cards preview (like a deck of photos) from up to 3 images."""
    from PIL import ImageDraw

    palette = palette or THEME_PALETTES['dark']

    # Create base image with background matching app theme
    img = Image.new('RGB', (size, size), palette['set_bg'])

    # Card dimensions - slightly smaller than the canvas
    card_width = int(size * 0.65)
    card_height = int(size * 0.65)

    # Stack offset for each card
    offset = size // 12

    # Reverse so the first item appears on top
    paths_to_draw = list(reversed(image_paths[:3]))

    for i, path in enumerate(paths_to_draw):
        try:
            # Calculate position - cards stack from bottom-left to top-right
            stack_idx = len(paths_to_draw) - 1 - i
            x = (size - card_width) // 2 - offset * stack_idx + offset
            y = (size - card_height) // 2 - offset * stack_idx + offset

            thumb = Image.open(path)
            thumb.load()  # Force full image load before any operations
            thumb = ImageOps.exif_transpose(thumb)
            if thumb.mode not in ('RGB', 'RGBA'):
                thumb = thumb.convert('RGB')

            # Center crop to card aspect ratio
            orig_w, orig_h = thumb.size
            target_ratio = card_width / card_height
            orig_ratio = orig_w / orig_h

            if orig_ratio > target_ratio:
                new_w = int(orig_h * target_ratio)
                left = (orig_w - new_w) // 2
                thumb = thumb.crop((left, 0, left + new_w, orig_h))
            else:
                new_h = int(orig_w / target_ratio)
                top = (orig_h - new_h) // 2
                thumb = thumb.crop((0, top, orig_w, top + new_h))

            # Resize to card size
            thumb = thumb.resize((card_width, card_height), Image.Resampling.LANCZOS)

            # Add a subtle border/shadow effect
            card = Image.new('RGB', (card_width + 4, card_height + 4), palette['set_card_border'])
            if thumb.mode == 'RGBA':
                # Composite RGBA onto white background to handle transparency properly
                # (just converting to RGB leaves transparent areas with garbage values)
                bg = Image.new('RGB', thumb.size, '#FFFFFF')
                bg.paste(thumb, mask=thumb.split()[3])  # Use alpha channel as mask
                thumb = bg
            card.paste(thumb, (2, 2))

            # Paste card onto canvas
            img.paste(card, (x - 2, y - 2))

            thumb.close()

        except Exception as e:
            log.warning(f"Failed to load stacked card image {path}: {e}")

    log.debug(f"Stacked cards complete: {len(paths_to_draw)} cards")
    return img


def _create_grid_mosaic(
    image_paths: list,
    size: int,
    accent_color: str,
    grid_cols: int = 3,
    grid_rows: int = 2,
    clip_last_col: bool = False,
    clip_last_row: bool = False,
    palette=None,
) -> Image.Image:
    """Create a grid thumbnail that reflects actual grid dimensions.

    Args:
        image_paths: List of image paths (or None for empty cells) in row-major order.
                     Should include cells for the clipped row/col if clip flags are True.
        size: Thumbnail size in pixels
        accent_color: Color for empty cell outlines
        grid_cols: Total number of columns in image_paths (including clipped col if any)
        grid_rows: Total number of rows in image_paths (including clipped row if any)
        clip_last_col: If True, the last column will be partially clipped at the edge
        clip_last_row: If True, the last row will be partially clipped at the edge
        palette: Theme palette dict for colors
    """
    from PIL import ImageDraw

    palette = palette or THEME_PALETTES['dark']

    # Create base image with background matching app theme
    img = Image.new('RGB', (size, size), palette['grid_bg'])

    if not image_paths:
        return img

    cols = grid_cols
    rows = grid_rows
    gap = max(2, size // 50)  # Small gap between cells

    # How much of the clipped cells to show (fraction)
    clip_fraction = 0.35

    # Minimal padding - just enough to not touch the edge
    padding = max(4, size // 32)

    # Calculate available space
    # For clipped edges, we want cells to extend TO the edge (no padding on that side)
    right_padding = 0 if clip_last_col else padding
    bottom_padding = 0 if clip_last_row else padding

    available_width = size - padding - right_padding
    available_height = size - padding - bottom_padding

    # Number of "full" columns/rows (not clipped)
    full_cols = cols - (1 if clip_last_col else 0)
    full_rows = rows - (1 if clip_last_row else 0)

    # Cell size calculation - fit full cells + partial clipped cells
    if clip_last_col and full_cols > 0:
        # Full cells + gaps + partial cell that extends to edge
        # full_cols * cell + (full_cols) * gap + clip_fraction * cell = available
        cell_size_w = int((available_width - full_cols * gap) / (full_cols + clip_fraction))
    elif cols > 0:
        cell_size_w = (available_width - (cols - 1) * gap) // cols
    else:
        cell_size_w = available_width

    if clip_last_row and full_rows > 0:
        cell_size_h = int((available_height - full_rows * gap) / (full_rows + clip_fraction))
    elif rows > 0:
        cell_size_h = (available_height - (rows - 1) * gap) // rows
    else:
        cell_size_h = available_height

    # Use the smaller dimension to keep cells square
    cell_size = min(cell_size_w, cell_size_h)

    # Simple small padding from top-left
    # Clipped cells will extend to edges via visible_width/height calculation
    start_x = padding
    start_y = padding

    draw = ImageDraw.Draw(img)

    # Load and place each image in grid order
    for i, path in enumerate(image_paths):
        row = i // cols
        col = i % cols

        # Determine if this cell will be clipped
        is_clipped_col = clip_last_col and col == cols - 1
        is_clipped_row = clip_last_row and row == rows - 1

        # Position calculation - cells are positioned normally in the grid
        x = start_x + col * (cell_size + gap)
        y = start_y + row * (cell_size + gap)

        # Skip cells that are entirely outside the image bounds
        if x >= size or y >= size:
            continue

        # Calculate visible size
        # Clipped cells should be partial (smaller than cell_size) to indicate more content
        # Cap at clip_fraction * cell_size to ensure they always look partial
        target_partial = int(clip_fraction * cell_size)

        if is_clipped_col:
            visible_width = min(target_partial, max(1, size - x))
        else:
            visible_width = cell_size

        if is_clipped_row:
            visible_height = min(target_partial, max(1, size - y))
        else:
            visible_height = cell_size

        if path:
            try:
                thumb = Image.open(path)
                thumb.load()  # Force full image load before any operations
                thumb = ImageOps.exif_transpose(thumb)
                if thumb.mode not in ('RGB', 'RGBA'):
                    thumb = thumb.convert('RGB')

                # Center crop to square
                orig_w, orig_h = thumb.size
                crop_size = min(orig_w, orig_h)
                left = (orig_w - crop_size) // 2
                top = (orig_h - crop_size) // 2
                thumb = thumb.crop((left, top, left + crop_size, top + crop_size))

                # Resize to visible size (clipped cells will be smaller)
                thumb = thumb.resize((visible_width, visible_height), Image.Resampling.LANCZOS)

                # Convert to RGB for consistent pasting
                if thumb.mode == 'RGBA':
                    # Composite RGBA onto white background to handle transparency properly
                    bg = Image.new('RGB', thumb.size, '#FFFFFF')
                    bg.paste(thumb, mask=thumb.split()[3])
                    thumb = bg

                # Paste into grid
                img.paste(thumb, (x, y))

                thumb.close()
                continue

            except Exception as e:
                log.debug(f"Failed to load grid image {path}: {e}")

        # Draw placeholder cell for missing/failed images
        # But skip placeholders for clipped edge cells - just leave as background
        if is_clipped_col or is_clipped_row:
            continue

        draw.rectangle(
            [x, y, x + visible_width - 1, y + visible_height - 1],
            fill=palette['grid_empty_fill'],
            outline=accent_color,
            width=1
        )

    # Calculate the bottom edge of the grid content
    grid_bottom = start_y + rows * cell_size + (rows - 1) * gap
    grid_right = start_x + cols * cell_size + (cols - 1) * gap

    # Explicitly clear any area below and to the right of the grid to prevent artifacts
    # This ensures the background color is consistent in unused areas
    if grid_bottom < size:
        draw.rectangle([0, grid_bottom, size, size], fill=palette['grid_bg'])
    if grid_right < size:
        draw.rectangle([grid_right, 0, size, grid_bottom], fill=palette['grid_bg'])

    return img


async def _generate_layout_preview(
    file_path: str,
    size: int,
    palette=None,
    *,
    wait_for_client_timeout_s: float = 0.25,
    queue_timeout_s: float = 0.25,
    render_timeout_s: float = 30.0,
    raise_transient: bool = False,
) -> Optional[Image.Image]:
    """Render a .stimmalayout bundle to a PIL image via the connected UI client.

    The UI's real browser engine (WKWebView in Tauri, the user's browser
    elsewhere) does the rasterization over a WebSocket RPC. Returns ``None``
    on failure, including the timeout-with-no-client case — callers treat
    that as "thumbnail not available right now" and may retry later.

    When ``raise_transient`` is set, the "renderer busy / no client yet" cases
    re-raise instead of collapsing to ``None`` so callers can tell a transient
    miss (retry later) apart from a genuine render failure.

    ``size`` is the longest-side target for the returned image. We render at a
    dpr scaled to that target rather than a fixed 2x — a full-res canvas of a
    large layout is dramatically slower to rasterize (WebKit's foreignObject
    filter path) for no benefit when we're only going to downscale to ``size``.
    """
    from pathlib import Path as PathLib

    bundle_dir = PathLib(file_path)
    if not (bundle_dir / 'index.html').exists():
        return None

    try:
        from utils.ui_render import (
            LayoutRenderBusy,
            LayoutRenderUnavailable,
            render_layout_bundle,
        )
        png_bytes, _w, _h = await render_layout_bundle(
            bundle_dir,
            wait_for_client_timeout_s=wait_for_client_timeout_s,
            render_timeout_s=render_timeout_s,
            queue_timeout_s=queue_timeout_s,
            target_long_side=size,
        )
        img = Image.open(io.BytesIO(png_bytes))
        img.load()
        img.thumbnail((size, size), Image.LANCZOS)
        return img
    except (LayoutRenderBusy, LayoutRenderUnavailable) as e:
        log.debug(f"Skipped layout preview for {file_path}: {e}")
        if raise_transient:
            raise
        return None
    except Exception as e:
        log.warning(f"Failed to generate layout preview for {file_path}: {e}")
        return None


# Result of an on-demand layout thumbnail render. "transient" means the UI
# renderer was busy or not yet connected — the same content will render fine
# moments later, so the caller should tell the client to retry rather than
# surface a hard error.
LAYOUT_THUMB_OK = "ok"
LAYOUT_THUMB_TRANSIENT = "transient"
LAYOUT_THUMB_FAILED = "failed"


async def _generate_layout_thumbnail_to_cache(
    file_path: str, cache_path: Path, size: int, palette=None,
) -> str:
    """Render a layout bundle and save a JPEG thumbnail to ``cache_path``.

    Returns one of ``LAYOUT_THUMB_{OK,TRANSIENT,FAILED}``. ``TRANSIENT`` means
    the render slot/UI client was momentarily unavailable (e.g. right after the
    layout is created, while the agent is still rendering) — retrying shortly
    will succeed. We wait a little longer here than the agent-vision path since
    a thumbnail GET can afford to block briefly for the slot.
    """
    from utils.ui_render import LayoutRenderBusy, LayoutRenderUnavailable

    try:
        img = await _generate_layout_preview(
            file_path,
            size,
            palette=palette,
            wait_for_client_timeout_s=2.0,
            queue_timeout_s=5.0,
            raise_transient=True,
        )
    except (LayoutRenderBusy, LayoutRenderUnavailable):
        return LAYOUT_THUMB_TRANSIENT
    if img is None:
        return LAYOUT_THUMB_FAILED
    if img.mode not in ('RGB',):
        img = img.convert('RGB')
    _atomic_save(img, cache_path, 'JPEG', quality=85, optimize=True)
    return LAYOUT_THUMB_OK


def _atomic_save(img: Image.Image, cache_path: Path, format: str, **kwargs):
    """
    Save image to cache_path atomically using write-to-temp-then-rename pattern.
    This prevents race conditions where concurrent requests could read a partially-written file.
    """
    # Write to temp file in same directory (ensures same filesystem for atomic rename)
    temp_path = cache_path.parent / f".tmp_{uuid.uuid4().hex}_{cache_path.name}"
    try:
        img.save(temp_path, format, **kwargs)
        # Atomic rename - on POSIX, this is guaranteed atomic if same filesystem
        os.replace(temp_path, cache_path)
    except Exception:
        # Clean up temp file on failure
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        # If another thread created the cache file, that's fine - not an error
        if not cache_path.exists():
            raise


def _generate_thumbnail_sync(
    file_path: str,
    file_format: str,
    cache_path: Path,
    size: int,
    faces_data: list = None,
    palette: dict = None,
    mode: str = "crop",
):
    """
    Synchronous thumbnail generation (runs in thread pool).
    Returns True on success, False on failure.

    Args:
        file_path: Path to the media file
        file_format: File format (jpg, png, mp4, etc.)
        cache_path: Path to save the thumbnail
        size: Target size for shortest dimension
        faces_data: Optional list of face bounding boxes for smart cropping
                    Each face dict should have: {bbox: {x, y, width, height}} in normalized coords
        palette: Theme palette dict for themed synthetic thumbnails
    """
    img = None
    try:
        video_formats = {'mp4', 'webm', 'mov', 'avi', 'mkv'}
        audio_formats = {'mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg'}

        format_lower = file_format.lower()

        # Handle audio files - generate waveform
        if format_lower in audio_formats:
            img = _generate_audio_waveform(file_path, size, palette=palette)
            _atomic_save(img, cache_path, 'JPEG', quality=85, optimize=True)
            return True

        # Handle structured types - generate placeholders
        if format_lower == 'md':
            img = _generate_text_preview(file_path, size, palette=palette)
            _atomic_save(img, cache_path, 'JPEG', quality=85, optimize=True)
            return True

        if format_lower == 'stimmaset.json':
            img = _generate_set_preview(file_path, size, palette=palette)
            _atomic_save(img, cache_path, 'JPEG', quality=85, optimize=True)
            return True

        if format_lower == 'stimmagrid.json':
            img = _generate_grid_preview(file_path, size, palette=palette)
            _atomic_save(img, cache_path, 'JPEG', quality=85, optimize=True)
            return True

        if format_lower == 'stimmalayout':
            # Layouts route through the UI client (async) — callers must
            # dispatch via _generate_layout_thumbnail_to_cache, not the sync path.
            log.error(
                "stimmalayout dispatched to sync thumbnail path; "
                "this is a bug in the calling code"
            )
            return False

        image_formats = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'}

        if format_lower in video_formats:
            # Extract first frame from video
            import ffmpeg
            out, _ = (
                ffmpeg
                .input(str(file_path), ss=0)
                .output('pipe:', vframes=1, format='image2', vcodec='mjpeg')
                .run(capture_stdout=True, capture_stderr=True, quiet=True)
            )
            img = Image.open(io.BytesIO(out))
        elif format_lower in image_formats:
            # Load image
            img = Image.open(file_path)
            img = ImageOps.exif_transpose(img)
        else:
            # Unsupported format - no thumbnail possible
            return False

        # Track if we should preserve transparency
        has_alpha = img.mode in ('RGBA', 'LA', 'PA')

        # Convert to appropriate mode
        if has_alpha:
            # Keep RGBA for transparency
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        orig_width, orig_height = img.size

        if mode == "fit":
            width, height = img.size
            longest_side = max(width, height)
            scale = size / longest_side if longest_side > size else 1
            new_width = max(1, int(width * scale))
            new_height = max(1, int(height * scale))
        else:
            # Smart crop calculation - pan to center on faces without zooming
            crop_region = None
            if faces_data and len(faces_data) > 0:
                total_x, total_y = 0, 0
                for face in faces_data:
                    bbox = face['bbox']
                    face_center_x = (bbox['x'] + bbox['width'] / 2) * orig_width
                    face_center_y = (bbox['y'] + bbox['height'] / 2) * orig_height
                    total_x += face_center_x
                    total_y += face_center_y

                faces_center_x = total_x / len(faces_data)
                faces_center_y = total_y / len(faces_data)

                if orig_width < orig_height:
                    crop_width = orig_width
                    crop_height = orig_width
                else:
                    crop_height = orig_height
                    crop_width = orig_height

                crop_x1 = faces_center_x - crop_width / 2
                crop_y1 = faces_center_y - crop_height / 2

                if crop_x1 < 0:
                    crop_x1 = 0
                if crop_y1 < 0:
                    crop_y1 = 0
                if crop_x1 + crop_width > orig_width:
                    crop_x1 = orig_width - crop_width
                if crop_y1 + crop_height > orig_height:
                    crop_y1 = orig_height - crop_height

                crop_region = (int(crop_x1), int(crop_y1), int(crop_x1 + crop_width), int(crop_y1 + crop_height))

            if crop_region:
                img = img.crop(crop_region)
            else:
                width, height = orig_width, orig_height
                if width < height:
                    crop_size = width
                    top = (height - crop_size) // 2
                    img = img.crop((0, top, width, top + crop_size))
                elif width > height:
                    crop_size = height
                    left = (width - crop_size) // 2
                    img = img.crop((left, 0, left + crop_size, height))

            width, height = img.size
            if width < height:
                new_width = size
                new_height = int(height * (size / width))
            else:
                new_height = size
                new_width = int(width * (size / height))

        # Resize with high-quality LANCZOS resampling
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Save to cache - use PNG for transparency, JPEG otherwise
        if has_alpha:
            _atomic_save(img, cache_path, 'PNG', optimize=True)
        else:
            _atomic_save(img, cache_path, 'JPEG', quality=85, optimize=True)
        return True

    except Exception as e:
        log.error(f"Error generating thumbnail for {file_path}: {e}", exc_info=True)
        return False
    finally:
        # Always close the image to free file handles
        if img is not None:
            img.close()


# IMPORTANT: Static path routes must come BEFORE parameterized routes
# Otherwise /media/by-hash/... would match /media/{media_id}/...

@router.get("/media/by-hash/{file_hash}/file")
async def get_media_file(
    file_hash: str,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Serve the original media file (full-size image or video) by file hash.
    Used in slideshow mode to display full-quality media.

    Note: Uses file_hash for stable caching. If multiple files have same hash (duplicates),
    returns file for any one of them (they're identical anyway).
    """
    # Get any media item with this hash (duplicates will have same content)
    # Prefer available files over unavailable/deleted ones when there are duplicates
    # Note: We include soft-deleted (trashed) items because trashed files stay in place
    # and should be viewable until permanently deleted
    result = await session.execute(
        select(MediaItem)
        .where(MediaItem.file_hash == file_hash)
        .order_by(
            # Prefer non-deleted files first
            MediaItem.deleted_at.asc().nulls_first(),
            # Then prefer available files (file_unavailable=False/NULL sorts before True)
            MediaItem.file_unavailable.asc().nulls_first()
        )
        .limit(1)
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    file_path = Path(item.file_path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Asset file not found on disk")

    # For directory-based media (e.g., .stimmalayout), serve the index.html
    if file_path.is_dir():
        index_path = file_path / 'index.html'
        if index_path.exists():
            return FileResponse(
                index_path,
                media_type='text/html',
                headers={
                    'Content-Disposition': f'inline; filename="{file_path.name}.html"',
                    'Access-Control-Allow-Origin': '*',
                }
            )
        raise HTTPException(status_code=404, detail="Layout index.html not found")

    # Determine media type based on file format
    video_formats = {'mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'}
    if item.file_format.lower() in video_formats:
        media_type = f"video/{item.file_format.lower()}"
    else:
        # For images, try to determine correct MIME type
        format_map = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'bmp': 'image/bmp'
        }
        media_type = format_map.get(item.file_format.lower(), 'application/octet-stream')

    # Extract filename from path and set Content-Disposition header
    # This preserves the original filename when dragging/downloading from browser
    filename = file_path.name
    return FileResponse(
        file_path,
        media_type=media_type,
        headers={
            'Content-Disposition': f'inline; filename="{filename}"',
            'Access-Control-Allow-Origin': '*',
        }
    )


@router.get("/media/{media_id}/thumbnail")
async def get_thumbnail_by_media_id(
    media_id: int,
    size: int = Query(512, ge=64, le=1024),
    mode: str = Query("crop", pattern="^(crop|fit)$"),
    theme: str = Query("dark"),
    session: AsyncSession = Depends(get_db_session)
):
    """Get thumbnail for a media item by media ID."""
    theme = theme if theme in ('dark', 'light') else 'dark'

    result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Redirect to file_hash endpoint, preserving profile for cross-profile support
    from fastapi.responses import RedirectResponse
    profile_id = get_current_profile()
    return RedirectResponse(url=f"/api/thumbnail/{item.file_hash}?size={size}&mode={mode}&profile={profile_id}&theme={theme}")


@router.get("/media/{media_id}/file")
async def get_file_by_media_id(
    media_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Get full media file by media ID."""
    result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    file_path = Path(item.file_path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Asset file not found on disk")

    # For directory-based media (e.g., .stimmalayout), serve the index.html
    if file_path.is_dir():
        index_path = file_path / 'index.html'
        if index_path.exists():
            return FileResponse(
                index_path,
                media_type='text/html',
                headers={'Access-Control-Allow-Origin': '*'}
            )
        raise HTTPException(status_code=404, detail="Layout index.html not found")

    # Determine media type based on file format
    video_formats = {'mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'}
    if item.file_format.lower() in video_formats:
        media_type = f"video/{item.file_format.lower()}"
    else:
        format_map = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'bmp': 'image/bmp'
        }
        media_type = format_map.get(item.file_format.lower(), 'application/octet-stream')

    return FileResponse(
        file_path,
        media_type=media_type,
        headers={'Access-Control-Allow-Origin': '*'}
    )


@router.get("/media/{media_id}/layout-html")
async def get_layout_html(
    media_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Get self-contained HTML for a .stimmalayout bundle with images inlined as data URIs."""
    import base64
    import mimetypes
    import re as re_mod

    result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")
    if item.file_format != 'stimmalayout':
        raise HTTPException(status_code=400, detail="Not a layout asset")

    bundle_dir = Path(item.file_path)
    index_path = bundle_dir / 'index.html'
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Layout index.html not found")

    html_content = index_path.read_text(encoding='utf-8')

    # Inline local file references as data URIs
    def _inline_ref(src_value):
        """Convert a local filename to a data URI, or return None to skip."""
        if src_value.startswith(('data:', 'http://', 'https://')):
            return None
        asset_path = bundle_dir / src_value
        if not asset_path.exists():
            return None
        mime_type = mimetypes.guess_type(str(asset_path))[0] or 'application/octet-stream'
        data = base64.b64encode(asset_path.read_bytes()).decode('ascii')
        return f'data:{mime_type};base64,{data}'

    # Inline src="..." attributes (img tags etc.)
    def replace_src(match):
        attr, quote, src_value = match.group(1), match.group(2), match.group(3)
        data_uri = _inline_ref(src_value)
        if data_uri is None:
            return match.group(0)
        return f'{attr}={quote}{data_uri}{quote}'

    html_content = re_mod.sub(
        r'(src)\s*=\s*(["\'])([^"\']+)\2',
        replace_src,
        html_content,
        flags=re_mod.IGNORECASE,
    )

    # Inline CSS url() references (background-image etc.)
    def replace_css_url(match):
        keyword, quote, src_value = match.group(1), match.group(2), match.group(3)
        data_uri = _inline_ref(src_value)
        if data_uri is None:
            return match.group(0)
        return f'{keyword}({quote}{data_uri}{quote})'

    html_content = re_mod.sub(
        r'(url)\((["\']?)([^"\')\s]+)\2\)',
        replace_css_url,
        html_content,
    )

    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_content, headers={'Access-Control-Allow-Origin': '*'})


class LayoutExportOptions(BaseModel):
    format: str = "pdf"  # "pdf", "png", "html"
    # PNG options — scale multiplier OR explicit width (height derived from aspect ratio)
    scale: Optional[float] = None  # e.g. 1.0, 2.0, 3.0
    width: Optional[int] = None    # explicit pixel width


@router.post("/media/{media_id}/layout-export")
async def export_layout(
    media_id: int,
    request: LayoutExportOptions = LayoutExportOptions(),
    session: AsyncSession = Depends(get_db_session),
):
    """Export a .stimmalayout bundle as PDF, PNG, or self-contained HTML."""
    import math
    import re as re_mod
    import base64
    import mimetypes
    import tempfile
    from pathlib import Path as PathLib

    result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")
    if item.file_format != 'stimmalayout':
        raise HTTPException(status_code=400, detail="Not a layout asset")

    bundle_dir = PathLib(item.file_path)
    index_path = bundle_dir / 'index.html'
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Layout index.html not found")

    html_content = index_path.read_text(encoding='utf-8')

    # Parse layout dimensions
    layout_width = 800
    layout_height = None
    w_match = re_mod.search(r'data-stimma-width="(\d+)"', html_content)
    h_match = re_mod.search(r'data-stimma-height="(\d+|auto)"', html_content)
    if w_match:
        layout_width = int(w_match.group(1))
    if h_match and h_match.group(1) != 'auto':
        layout_height = int(h_match.group(1))

    base_name = bundle_dir.stem.replace('.stimmalayout', '') or f"layout-{media_id}"

    fmt = request.format.lower()

    if fmt == "html":
        # Return self-contained HTML with inlined assets
        def _inline_ref(src_value):
            if src_value.startswith(('data:', 'http://', 'https://')):
                return None
            asset_path = bundle_dir / src_value
            if not asset_path.exists():
                return None
            mime_type = mimetypes.guess_type(str(asset_path))[0] or 'application/octet-stream'
            data = base64.b64encode(asset_path.read_bytes()).decode('ascii')
            return f'data:{mime_type};base64,{data}'

        def replace_src(match):
            attr, quote, src_value = match.group(1), match.group(2), match.group(3)
            data_uri = _inline_ref(src_value)
            if data_uri is None:
                return match.group(0)
            return f'{attr}={quote}{data_uri}{quote}'

        inlined = re_mod.sub(
            r'(src)\s*=\s*(["\'])([^"\']+)\2',
            replace_src, html_content, flags=re_mod.IGNORECASE,
        )

        def replace_css_url(match):
            keyword, quote, src_value = match.group(1), match.group(2), match.group(3)
            data_uri = _inline_ref(src_value)
            if data_uri is None:
                return match.group(0)
            return f'{keyword}({quote}{data_uri}{quote})'

        inlined = re_mod.sub(
            r'(url)\((["\']?)([^"\')\s]+)\2\)',
            replace_css_url, inlined,
        )

        filename = f"{base_name}.html"
        return StreamingResponse(
            io.BytesIO(inlined.encode('utf-8')),
            media_type='text/html',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Access-Control-Allow-Origin': '*',
            }
        )

    # PDF and PNG both go through WeasyPrint
    try:
        from weasyprint import HTML as WeasyprintHTML, CSS
    except ImportError:
        raise HTTPException(status_code=500, detail="WeasyPrint not available")

    try:
        base_url = str(bundle_dir.resolve())
        reset_css = CSS(string=(
            "body { margin: 0 !important; padding: 0 !important;"
            " display: block !important; position: relative !important;"
            " overflow: hidden !important; }"
            " body > *:first-child { position: absolute !important;"
            " top: 0 !important; left: 0 !important;"
            " width: 100% !important; height: 100% !important;"
            " overflow: hidden !important; }"
        ))

        if layout_height is None:
            # Auto-height: measure content
            measure_css = CSS(string=f"@page {{ size: {layout_width}px 100000px; margin: 0; }}")
            doc = WeasyprintHTML(string=html_content, base_url=base_url).render(
                stylesheets=[measure_css, reset_css],
                presentational_hints=True,
            )
            page_box = doc.pages[0]._page_box
            content_height = layout_width
            if hasattr(page_box, "children") and page_box.children:
                html_box = page_box.children[0]
                content_height = math.ceil(html_box.height)
            layout_height = max(1, content_height)

        page_css = CSS(string=f"@page {{ size: {layout_width}px {layout_height}px; margin: 0; }}")

        if fmt == "pdf":
            pdf_bytes = WeasyprintHTML(string=html_content, base_url=base_url).write_pdf(
                stylesheets=[page_css, reset_css],
                presentational_hints=True,
            )
            filename = f"{base_name}.pdf"
            return StreamingResponse(
                io.BytesIO(pdf_bytes),
                media_type='application/pdf',
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Access-Control-Allow-Origin': '*',
                }
            )

        elif fmt == "png":
            import pypdfium2 as pdfium

            # Determine render scale
            if request.width:
                render_scale = request.width / layout_width
            elif request.scale:
                render_scale = request.scale
            else:
                render_scale = 2.0  # default 2x

            pdf_bytes = WeasyprintHTML(string=html_content, base_url=base_url).write_pdf(
                stylesheets=[page_css, reset_css],
                presentational_hints=True,
            )
            pdf = pdfium.PdfDocument(pdf_bytes)
            page = pdf[0]
            bitmap = page.render(scale=render_scale)
            img = bitmap.to_pil()

            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)

            filename = f"{base_name}.png"
            return StreamingResponse(
                buf,
                media_type='image/png',
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Access-Control-Allow-Origin': '*',
                }
            )

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}")

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Layout export failed for {media_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@router.get("/thumbnail/{file_hash}")
async def get_thumbnail(
    file_hash: str,
    size: int = Query(512, ge=64, le=1024),
    mode: str = Query("crop", pattern="^(crop|fit)$"),
    theme: str = Query("dark"),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get thumbnail for a media item by file hash.
    Generates thumbnails with shortest side = requested size (default 512px) on-the-fly with caching.
    For videos, extracts first frame.
    Uses thread pool for parallel generation.
    If faces are detected, crops thumbnail to include all faces.

    Note: Uses file_hash for stable caching. If multiple files have same hash (duplicates),
    returns thumbnail for any one of them (they're identical anyway).
    """
    theme = theme if theme in ('dark', 'light') else 'dark'

    # Get any media item with this hash (duplicates will have same content)
    # Prefer available files over unavailable/deleted ones when there are duplicates
    # Note: We include soft-deleted (trashed) items because trashed files stay in place
    # and should be viewable until permanently deleted
    result = await session.execute(
        select(MediaItem)
        .where(MediaItem.file_hash == file_hash)
        .order_by(
            # Prefer non-deleted files first
            MediaItem.deleted_at.asc().nulls_first(),
            # Then prefer available files (file_unavailable=False/NULL sorts before True)
            MediaItem.file_unavailable.asc().nulls_first()
        )
        .limit(1)
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Fetch face data for this item
    from database import Face
    faces_result = await session.execute(
        select(Face).where(Face.media_id == item.id)
    )
    faces = faces_result.scalars().all()
    faces_data = [face.to_dict() for face in faces] if faces else None

    # Create cache directory from settings (computed via app_dirs)
    settings = get_settings()
    cache_dir = settings.get_thumbnail_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Cache key based on file path, size, face count, and algorithm version
    # Increment THUMBNAIL_VERSION when the cropping/generation algorithm changes
    THUMBNAIL_VERSION = 31  # v31: apply EXIF orientation when generating thumbnails
    face_count = len(faces) if faces else 0

    # For text files and sets, include mtime so edits invalidate the thumbnail cache
    mtime_suffix = ""
    fmt_lower = item.file_format.lower()
    if fmt_lower in ('md', 'stimmaset.json', 'stimmagrid.json', 'stimmalayout'):
        try:
            mtime_path = Path(item.file_path)
            if fmt_lower == 'stimmalayout':
                mtime_path = mtime_path / 'index.html'
            mtime_suffix = f"_mtime{mtime_path.stat().st_mtime}"
        except OSError:
            pass

    # Include theme in cache key only for synthetic thumbnail types
    theme_suffix = f"_theme{theme}" if fmt_lower in THEMED_FORMATS else ""
    cache_key = hashlib.md5(f"{item.file_path}_{size}_{mode}_{face_count}_v{THUMBNAIL_VERSION}{mtime_suffix}{theme_suffix}".encode()).hexdigest()

    # Check for cached thumbnail (PNG for transparent images, JPG otherwise)
    cache_path_png = _sharded_cache_path(cache_dir, cache_key, "png")
    cache_path_jpg = _sharded_cache_path(cache_dir, cache_key, "jpg")

    cors_headers = {'Access-Control-Allow-Origin': '*'}
    if cache_path_png.exists():
        await _record_thumbnail_cache(session, item.id, cache_path_png)
        return FileResponse(cache_path_png, media_type="image/png", headers=cors_headers)
    if cache_path_jpg.exists():
        await _record_thumbnail_cache(session, item.id, cache_path_jpg)
        return FileResponse(cache_path_jpg, media_type="image/jpeg", headers=cors_headers)

    # Determine if source might have transparency (PNG format)
    might_have_alpha = item.file_format.lower() == 'png'
    cache_path = cache_path_png if might_have_alpha else cache_path_jpg

    # Ensure shard subdirectory exists
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve palette for synthetic thumbnails
    palette = THEME_PALETTES.get(theme, THEME_PALETTES['dark'])

    # Generate thumbnail. Layouts go through the async UI-render path; everything
    # else runs in the thread pool.
    layout_status = None
    if item.file_format.lower() == 'stimmalayout':
        layout_status = await _generate_layout_thumbnail_to_cache(
            item.file_path, cache_path, size, palette=palette,
        )
        success = layout_status == LAYOUT_THUMB_OK
    else:
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(
            thumbnail_executor,
            _generate_thumbnail_sync,
            item.file_path,
            item.file_format,
            cache_path,
            size,
            faces_data,
            palette,
            mode,
        )

    if not success:
        # Check if another thread succeeded while we were generating
        if cache_path_png.exists():
            return FileResponse(cache_path_png, media_type="image/png", headers=cors_headers)
        if cache_path_jpg.exists():
            return FileResponse(cache_path_jpg, media_type="image/jpeg", headers=cors_headers)
        if layout_status == LAYOUT_THUMB_TRANSIENT:
            # UI renderer was busy/unconnected — the same layout will render
            # fine shortly. Signal a retry instead of a hard failure so the
            # client refetches rather than showing a permanent broken image.
            raise HTTPException(
                status_code=503,
                detail="Layout thumbnail not ready yet",
                headers={"Retry-After": "1", **cors_headers},
            )
        raise HTTPException(status_code=500, detail="Failed to generate thumbnail")

    # Return with correct media type
    media_type = "image/png" if might_have_alpha else "image/jpeg"
    await _record_thumbnail_cache(session, item.id, cache_path)
    return FileResponse(cache_path, media_type=media_type, headers=cors_headers)


@router.get("/media/{media_id}/lineage")
async def get_media_lineage(
    media_id: int,
    include_ancestors: bool = Query(False, description="Include full ancestor tree (recursive)"),
    include_descendants: bool = Query(False, description="Include full descendant tree (recursive)"),
    max_depth: int = Query(50, ge=1, le=100, description="Maximum recursion depth for ancestor/descendant queries"),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get source images (parents) and derivatives (children) for a media item.

    Returns:
    - sources: List of immediate source media items
    - derivatives: List of immediate derivative media items
    - ancestors: (if include_ancestors=true) Full ancestor tree
    - descendants: (if include_descendants=true) Full descendant tree
    """
    # Get sources (what was used to create this media)
    sources_result = await session.execute(
        select(MediaLineage)
        .where(MediaLineage.media_id == media_id)
        .order_by(MediaLineage.source_order)
    )
    sources = sources_result.scalars().all()

    # Get derivatives (what was created from this media)
    derivatives_result = await session.execute(
        select(MediaLineage)
        .where(MediaLineage.source_media_id == media_id)
        .order_by(MediaLineage.created_at.desc())
    )
    derivatives = derivatives_result.scalars().all()

    # Build response with resolved media items
    source_data = []
    source_ids = set()  # Track IDs we've already added

    for s in sources:
        item = {
            "order": s.source_order,
            "task_type": s.task_type,
        }
        if s.source_media_id:
            media_result = await session.execute(
                select(MediaItem).where(MediaItem.id == s.source_media_id)
            )
            media = media_result.scalar_one_or_none()
            if media and not media.deleted_at:
                item["type"] = "internal"
                item["media"] = media.to_dict()
                source_ids.add(media.id)
            else:
                item["type"] = "deleted"
                item["media_id"] = s.source_media_id
        else:
            item["type"] = "external"
            item["file_path"] = s.source_file_path
        source_data.append(item)

    # LEGACY: Find sources via deprecated superseded_by field (for pre-lineage data only)
    # This field is no longer written to - new lineage uses the media_lineage table
    supersede_source_result = await session.execute(
        select(MediaItem).where(MediaItem.superseded_by == media_id)
    )
    supersede_sources = supersede_source_result.scalars().all()
    for source_media in supersede_sources:
        if source_media and not source_media.deleted_at and source_media.id not in source_ids:
            source_data.append({
                "order": 0,
                "task_type": "upscale",
                "type": "internal",
                "media": source_media.to_dict()
            })
            source_ids.add(source_media.id)

    derivative_data = []
    derivative_ids = set()  # Track IDs we've already added

    for d in derivatives:
        media_result = await session.execute(
            select(MediaItem).where(MediaItem.id == d.media_id)
        )
        media = media_result.scalar_one_or_none()
        if media and not media.deleted_at:
            derivative_data.append({
                "media": media.to_dict(),
                "task_type": d.task_type,
                "relationship_type": getattr(d, 'relationship_type', 'derived'),
                "created_at": d.created_at.isoformat()
            })
            derivative_ids.add(media.id)

    # LEGACY: Find derivatives via deprecated superseded_by field (for pre-lineage data only)
    # This field is no longer written to - new lineage uses the media_lineage table
    current_media_result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    current_media = current_media_result.scalar_one_or_none()

    if current_media and current_media.superseded_by:
        superseded_result = await session.execute(
            select(MediaItem).where(MediaItem.id == current_media.superseded_by)
        )
        superseded_media = superseded_result.scalar_one_or_none()
        if superseded_media and not superseded_media.deleted_at and superseded_media.id not in derivative_ids:
            derivative_data.append({
                "media": superseded_media.to_dict(),
                "task_type": "upscale",
                "created_at": superseded_media.created_date.isoformat() if superseded_media.created_date else None
            })
            derivative_ids.add(superseded_media.id)

    result = {
        "media_id": media_id,
        "sources": source_data,
        "derivatives": derivative_data
    }

    log.debug(f"Lineage for {media_id}: {len(source_data)} sources, {len(derivative_data)} derivatives")

    # Optional: Get full ancestor tree using recursive query
    if include_ancestors:
        from sqlalchemy import text
        ancestors_query = text("""
            WITH RECURSIVE ancestors(media_id, source_media_id, source_file_path, task_type, depth) AS (
                -- Base case: immediate parents
                SELECT ml.media_id, ml.source_media_id, ml.source_file_path, ml.task_type, 1
                FROM media_lineage ml
                WHERE ml.media_id = :start_id AND ml.source_media_id IS NOT NULL

                UNION ALL

                -- Recursive case: parents of parents
                SELECT ml.media_id, ml.source_media_id, ml.source_file_path, ml.task_type, a.depth + 1
                FROM media_lineage ml
                INNER JOIN ancestors a ON ml.media_id = a.source_media_id
                WHERE ml.source_media_id IS NOT NULL AND a.depth < :max_depth
            )
            SELECT DISTINCT source_media_id, depth, task_type
            FROM ancestors
            ORDER BY depth
        """)
        ancestors_result = await session.execute(
            ancestors_query, {"start_id": media_id, "max_depth": max_depth}
        )
        ancestor_rows = ancestors_result.fetchall()

        ancestors_data = []
        for row in ancestor_rows:
            source_id, depth, task_type = row
            media_result = await session.execute(
                select(MediaItem).where(MediaItem.id == source_id)
            )
            media = media_result.scalar_one_or_none()
            if media and not media.deleted_at:
                ancestors_data.append({
                    "media": media.to_dict(),
                    "depth": depth,
                    "task_type": task_type
                })
        result["ancestors"] = ancestors_data

    # Optional: Get full descendant tree using recursive query
    if include_descendants:
        from sqlalchemy import text
        descendants_query = text("""
            WITH RECURSIVE descendants(media_id, source_media_id, task_type, relationship_type, depth) AS (
                -- Base case: immediate children
                SELECT ml.media_id, ml.source_media_id, ml.task_type, COALESCE(ml.relationship_type, 'derived'), 1
                FROM media_lineage ml
                WHERE ml.source_media_id = :start_id

                UNION ALL

                -- Recursive case: children of children
                SELECT ml.media_id, ml.source_media_id, ml.task_type, COALESCE(ml.relationship_type, 'derived'), d.depth + 1
                FROM media_lineage ml
                INNER JOIN descendants d ON ml.source_media_id = d.media_id
                WHERE d.depth < :max_depth
            )
            SELECT DISTINCT media_id, depth, task_type, relationship_type
            FROM descendants
            ORDER BY depth
        """)
        descendants_result = await session.execute(
            descendants_query, {"start_id": media_id, "max_depth": max_depth}
        )
        descendant_rows = descendants_result.fetchall()

        descendants_data = []
        for row in descendant_rows:
            child_id, depth, task_type, rel_type = row
            media_result = await session.execute(
                select(MediaItem).where(MediaItem.id == child_id)
            )
            media = media_result.scalar_one_or_none()
            if media and not media.deleted_at:
                descendants_data.append({
                    "media": media.to_dict(),
                    "depth": depth,
                    "task_type": task_type,
                    "relationship_type": rel_type or 'derived'
                })
        result["descendants"] = descendants_data

    return result


@router.get("/media/{media_id}/lineage/tree")
async def get_media_lineage_tree(
    media_id: int,
    max_depth: int = Query(50, ge=1, le=100, description="Maximum recursion depth"),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get the full connected lineage graph for a media item.

    Walks ALL edges in both directions (parents and children) from the focus node,
    then continues walking from every discovered node until the entire connected
    component is found. This means siblings, cousins, and their descendants are
    all included — not just the direct ancestor/descendant chain.

    Returns a graph structure with:
    - nodes: All media items in the connected component with depth relative to focus
    - edges: All parent-child relationships with task_type and relationship_type
    """
    from sqlalchemy import text

    # Verify focus media exists
    focus_result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    focus_media = focus_result.scalar_one_or_none()
    if not focus_media:
        raise HTTPException(status_code=404, detail="Media item not found")

    # Walk the full connected component using BFS in both directions.
    # We fetch ALL edges from the media_lineage table that touch any node we've
    # discovered, repeating until no new nodes are found.
    visited = {media_id}
    frontier = {media_id}
    all_edges = []  # (child_id, parent_id, task_type, relationship_type, source_order)
    seen_edge_keys = set()
    # Pre-load set of trashed media IDs so we don't walk through them
    trashed_ids = set()

    for _ in range(max_depth):
        if not frontier:
            break

        frontier_list = list(frontier)

        # Find all edges where any frontier node is the child (i.e. walk to parents)
        parents_result = await session.execute(
            select(MediaLineage).where(
                MediaLineage.media_id.in_(frontier_list),
                MediaLineage.source_media_id.is_not(None)
            )
        )
        # Find all edges where any frontier node is the parent (i.e. walk to children)
        children_result = await session.execute(
            select(MediaLineage).where(
                MediaLineage.source_media_id.in_(frontier_list)
            )
        )

        # Collect candidate new IDs to check for trashed status
        candidate_ids = set()
        parent_rows = parents_result.scalars().all()
        child_rows = children_result.scalars().all()
        for ml in parent_rows:
            if ml.source_media_id not in visited:
                candidate_ids.add(ml.source_media_id)
        for ml in child_rows:
            if ml.media_id not in visited:
                candidate_ids.add(ml.media_id)

        # Check which candidates are trashed
        if candidate_ids:
            trashed_result = await session.execute(
                select(MediaItem.id).where(
                    MediaItem.id.in_(list(candidate_ids)),
                    MediaItem.deleted_at.is_not(None)
                )
            )
            trashed_ids.update(trashed_result.scalars().all())

        new_frontier = set()
        for ml in parent_rows:
            if ml.source_media_id in trashed_ids:
                continue
            key = (ml.source_media_id, ml.media_id)
            if key not in seen_edge_keys:
                seen_edge_keys.add(key)
                all_edges.append((ml.media_id, ml.source_media_id, ml.task_type,
                                  getattr(ml, 'relationship_type', 'derived') or 'derived',
                                  ml.source_order or 0))
            if ml.source_media_id not in visited:
                visited.add(ml.source_media_id)
                new_frontier.add(ml.source_media_id)

        for ml in child_rows:
            if ml.media_id in trashed_ids:
                continue
            key = (ml.source_media_id, ml.media_id)
            if key not in seen_edge_keys:
                seen_edge_keys.add(key)
                all_edges.append((ml.media_id, ml.source_media_id, ml.task_type,
                                  getattr(ml, 'relationship_type', 'derived') or 'derived',
                                  ml.source_order or 0))
            if ml.media_id not in visited:
                visited.add(ml.media_id)
                new_frontier.add(ml.media_id)

        frontier = new_frontier

    # LEGACY: Include superseded_by edges for nodes we've found
    # Check if any visited node has superseded_by pointing outside the set
    if visited:
        legacy_result = await session.execute(
            select(MediaItem).where(
                MediaItem.superseded_by.in_(list(visited)),
                MediaItem.deleted_at.is_(None)
            )
        )
        for source_media in legacy_result.scalars().all():
            key = (source_media.id, source_media.superseded_by)
            if key not in seen_edge_keys:
                seen_edge_keys.add(key)
                all_edges.append((source_media.superseded_by, source_media.id,
                                  "upscale", "derived", 0))
                visited.add(source_media.id)

    # Final sweep: find ALL edges between visited nodes that BFS may have missed.
    # This catches edges where both endpoints were discovered from different directions,
    # or edges between nodes that were found via superseded_by.
    if visited:
        sweep_result = await session.execute(
            select(MediaLineage).where(
                MediaLineage.media_id.in_(list(visited)),
                MediaLineage.source_media_id.in_(list(visited))
            )
        )
        for ml in sweep_result.scalars().all():
            key = (ml.source_media_id, ml.media_id)
            if key not in seen_edge_keys:
                seen_edge_keys.add(key)
                all_edges.append((ml.media_id, ml.source_media_id, ml.task_type,
                                  getattr(ml, 'relationship_type', 'derived') or 'derived',
                                  ml.source_order or 0))

        # Also check superseded_by edges between visited nodes
        supersede_result = await session.execute(
            select(MediaItem).where(
                MediaItem.id.in_(list(visited)),
                MediaItem.superseded_by.in_(list(visited)),
                MediaItem.deleted_at.is_(None)
            )
        )
        for m in supersede_result.scalars().all():
            key = (m.id, m.superseded_by)
            if key not in seen_edge_keys:
                seen_edge_keys.add(key)
                all_edges.append((m.superseded_by, m.id, "upscale", "derived", 0))

    # Compute depth via BFS from focus node using the edge adjacency
    # Build adjacency: parent -> [children], child -> [parents]
    children_of = {}
    parents_of = {}
    for child_id, parent_id, *_ in all_edges:
        children_of.setdefault(parent_id, []).append(child_id)
        parents_of.setdefault(child_id, []).append(parent_id)

    depth_map = {media_id: 0}
    # BFS backward (to ancestors)
    queue = [media_id]
    bfs_visited = {media_id}
    while queue:
        nid = queue.pop(0)
        for pid in parents_of.get(nid, []):
            if pid not in bfs_visited:
                bfs_visited.add(pid)
                depth_map[pid] = depth_map[nid] - 1
                queue.append(pid)
    # BFS forward (to descendants) — from focus and also from nodes already visited
    queue = [media_id]
    bfs_visited2 = {media_id}
    while queue:
        nid = queue.pop(0)
        for cid in children_of.get(nid, []):
            if cid not in bfs_visited2:
                bfs_visited2.add(cid)
                if cid not in depth_map:
                    depth_map[cid] = depth_map[nid] + 1
                queue.append(cid)

    # Any nodes still without depth (disconnected via only legacy edges) get depth 0
    for nid in visited:
        if nid not in depth_map:
            depth_map[nid] = 0

    # Batch-fetch all media items
    if visited:
        media_result = await session.execute(
            select(MediaItem).where(
                MediaItem.id.in_(list(visited)),
                MediaItem.deleted_at.is_(None)
            ).options(
                selectinload(MediaItem.marker_associations).selectinload(MediaMarker.marker)
            )
        )
        media_items = {m.id: m for m in media_result.scalars().all()}
    else:
        media_items = {}

    valid_ids = set(media_items.keys())
    nodes = [
        {"id": mid, "media": media_items[mid].to_dict(), "depth": depth_map.get(mid, 0)}
        for mid in valid_ids
    ]

    edges = [
        {
            "source_id": parent_id,
            "target_id": child_id,
            "task_type": task_type,
            "relationship_type": rel_type,
            "source_order": source_order
        }
        for child_id, parent_id, task_type, rel_type, source_order in all_edges
        if parent_id in valid_ids and child_id in valid_ids
    ]

    log.debug(f"Lineage tree for {media_id}: {len(nodes)} nodes, {len(edges)} edges")

    return {
        "focus_media_id": media_id,
        "nodes": nodes,
        "edges": edges
    }


# ============================================================================
# New db_guid-based routes for profile-safe URLs
# These routes include the database GUID in the path, making URLs globally unique
# and preventing cross-profile caching issues
# ============================================================================

@router.get("/db/{db_guid}/thumbnail/{file_hash}")
async def get_thumbnail_by_db_guid(
    db_guid: str,
    file_hash: str,
    size: int = Query(512, ge=64, le=1024),
    mode: str = Query("crop", pattern="^(crop|fit)$"),
    theme: str = Query("dark"),
    session: AsyncSession = Depends(get_db_session_by_guid)
):
    """
    Get thumbnail by db_guid and file hash.
    This is the preferred endpoint as the URL is globally unique.
    """
    theme = theme if theme in ('dark', 'light') else 'dark'

    # Query is same as get_thumbnail but session is from db_guid lookup
    result = await session.execute(
        select(MediaItem)
        .where(MediaItem.file_hash == file_hash)
        .order_by(
            MediaItem.deleted_at.asc().nulls_first(),
            MediaItem.file_unavailable.asc().nulls_first()
        )
        .limit(1)
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Fetch face data for this item
    faces_result = await session.execute(
        select(Face).where(Face.media_id == item.id)
    )
    faces = faces_result.scalars().all()
    faces_data = [face.to_dict() for face in faces] if faces else None

    # Create cache directory from settings
    settings = get_settings()
    cache_dir = settings.get_thumbnail_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Cache key includes db_guid for profile isolation in cache
    THUMBNAIL_VERSION = 31  # v31: apply EXIF orientation when generating thumbnails
    face_count = len(faces) if faces else 0

    # For text files and sets, include mtime so edits invalidate the thumbnail cache
    mtime_suffix = ""
    fmt_lower = item.file_format.lower()
    if fmt_lower in ('md', 'stimmaset.json', 'stimmagrid.json', 'stimmalayout'):
        try:
            mtime_path = Path(item.file_path)
            if fmt_lower == 'stimmalayout':
                mtime_path = mtime_path / 'index.html'
            mtime_suffix = f"_mtime{mtime_path.stat().st_mtime}"
        except OSError:
            pass

    # Include theme in cache key only for synthetic thumbnail types
    theme_suffix = f"_theme{theme}" if fmt_lower in THEMED_FORMATS else ""
    cache_key = hashlib.md5(f"{db_guid}_{item.file_path}_{size}_{mode}_{face_count}_v{THUMBNAIL_VERSION}{mtime_suffix}{theme_suffix}".encode()).hexdigest()

    cache_path_png = _sharded_cache_path(cache_dir, cache_key, "png")
    cache_path_jpg = _sharded_cache_path(cache_dir, cache_key, "jpg")

    if cache_path_png.exists():
        await _record_thumbnail_cache(session, item.id, cache_path_png)
        return FileResponse(cache_path_png, media_type="image/png", headers=CACHE_HEADERS)
    if cache_path_jpg.exists():
        await _record_thumbnail_cache(session, item.id, cache_path_jpg)
        return FileResponse(cache_path_jpg, media_type="image/jpeg", headers=CACHE_HEADERS)

    might_have_alpha = item.file_format.lower() == 'png'
    cache_path = cache_path_png if might_have_alpha else cache_path_jpg

    # Ensure shard subdirectory exists
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve palette for synthetic thumbnails
    palette = THEME_PALETTES.get(theme, THEME_PALETTES['dark'])

    layout_status = None
    if item.file_format.lower() == 'stimmalayout':
        layout_status = await _generate_layout_thumbnail_to_cache(
            item.file_path, cache_path, size, palette=palette,
        )
        success = layout_status == LAYOUT_THUMB_OK
    else:
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(
            thumbnail_executor,
            _generate_thumbnail_sync,
            item.file_path,
            item.file_format,
            cache_path,
            size,
            faces_data,
            palette,
            mode,
        )

    if not success:
        # Check if another thread succeeded while we were generating
        if cache_path_png.exists():
            await _record_thumbnail_cache(session, item.id, cache_path_png)
            return FileResponse(cache_path_png, media_type="image/png", headers=CACHE_HEADERS)
        if cache_path_jpg.exists():
            await _record_thumbnail_cache(session, item.id, cache_path_jpg)
            return FileResponse(cache_path_jpg, media_type="image/jpeg", headers=CACHE_HEADERS)
        if layout_status == LAYOUT_THUMB_TRANSIENT:
            # UI renderer momentarily busy/unconnected — retryable, not a hard
            # failure. Client should refetch rather than show a broken image.
            raise HTTPException(
                status_code=503,
                detail="Layout thumbnail not ready yet",
                headers={"Retry-After": "1"},
            )
        raise HTTPException(status_code=500, detail="Failed to generate thumbnail")

    media_type = "image/png" if might_have_alpha else "image/jpeg"
    await _record_thumbnail_cache(session, item.id, cache_path)
    return FileResponse(cache_path, media_type=media_type, headers=CACHE_HEADERS)


@router.get("/db/{db_guid}/media/by-hash/{file_hash}/file")
async def get_media_file_by_db_guid(
    db_guid: str,
    file_hash: str,
    session: AsyncSession = Depends(get_db_session_by_guid)
):
    """
    Serve original media file by db_guid and file hash.
    This is the preferred endpoint as the URL is globally unique.
    """
    result = await session.execute(
        select(MediaItem)
        .where(MediaItem.file_hash == file_hash)
        .order_by(
            MediaItem.deleted_at.asc().nulls_first(),
            MediaItem.file_unavailable.asc().nulls_first()
        )
        .limit(1)
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    file_path = Path(item.file_path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Asset file not found on disk")

    # For directory-based media (e.g., .stimmalayout), serve the index.html
    if file_path.is_dir():
        index_path = file_path / 'index.html'
        if index_path.exists():
            return FileResponse(
                index_path,
                media_type='text/html',
                headers={**CACHE_HEADERS, 'Content-Disposition': f'inline; filename="{file_path.name}.html"'}
            )
        raise HTTPException(status_code=404, detail="Layout index.html not found")

    video_formats = {'mp4', 'webm', 'mov', 'avi', 'mkv'}
    audio_formats = {
        'mp3': 'audio/mpeg',
        'wav': 'audio/wav',
        'flac': 'audio/flac',
        'aac': 'audio/aac',
        'm4a': 'audio/mp4',
        'ogg': 'audio/ogg',
    }
    fmt = item.file_format.lower()
    if fmt in video_formats:
        media_type = f"video/{fmt}"
    elif fmt in audio_formats:
        media_type = audio_formats[fmt]
    else:
        format_map = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'bmp': 'image/bmp'
        }
        media_type = format_map.get(fmt, 'application/octet-stream')

    filename = file_path.name
    headers = {
        **CACHE_HEADERS,
        'Content-Disposition': f'inline; filename="{filename}"'
    }
    return FileResponse(file_path, media_type=media_type, headers=headers)


@router.get("/db/{db_guid}/media/{media_id}/file")
async def get_file_by_media_id_and_db_guid(
    db_guid: str,
    media_id: int,
    session: AsyncSession = Depends(get_db_session_by_guid)
):
    """
    Get full media file by db_guid and media ID.
    This is the preferred endpoint as the URL is globally unique.
    """
    result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    file_path = Path(item.file_path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Asset file not found on disk")

    # For directory-based media (e.g., .stimmalayout), serve the index.html
    if file_path.is_dir():
        index_path = file_path / 'index.html'
        if index_path.exists():
            return FileResponse(
                index_path,
                media_type='text/html',
                headers={**CACHE_HEADERS, 'Content-Disposition': f'inline; filename="{file_path.name}.html"'}
            )
        raise HTTPException(status_code=404, detail="Layout index.html not found")

    video_formats = {'mp4', 'webm', 'mov', 'avi', 'mkv'}
    audio_formats = {
        'mp3': 'audio/mpeg',
        'wav': 'audio/wav',
        'flac': 'audio/flac',
        'aac': 'audio/aac',
        'm4a': 'audio/mp4',
        'ogg': 'audio/ogg',
    }
    fmt = item.file_format.lower()
    if fmt in video_formats:
        media_type = f"video/{fmt}"
    elif fmt in audio_formats:
        media_type = audio_formats[fmt]
    else:
        format_map = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'bmp': 'image/bmp'
        }
        media_type = format_map.get(fmt, 'application/octet-stream')

    filename = file_path.name
    headers = {
        **CACHE_HEADERS,
        'Content-Disposition': f'inline; filename="{filename}"'
    }
    return FileResponse(file_path, media_type=media_type, headers=headers)


@router.get("/db/{db_guid}/media/{media_id}/thumbnail")
async def get_thumbnail_by_media_id_and_db_guid(
    db_guid: str,
    media_id: int,
    size: int = Query(512, ge=64, le=1024),
    mode: str = Query("crop", pattern="^(crop|fit)$"),
    theme: str = Query("dark"),
    session: AsyncSession = Depends(get_db_session_by_guid)
):
    """Get thumbnail by db_guid and media ID."""
    theme = theme if theme in ('dark', 'light') else 'dark'

    result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Redirect to hash-based endpoint (keeps URL consistent)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/api/db/{db_guid}/thumbnail/{item.file_hash}?size={size}&mode={mode}&theme={theme}")


@router.get("/db/{db_guid}/media/{media_id}/thumbnail-path")
async def get_thumbnail_path_by_media_id(
    db_guid: str,
    media_id: int,
    size: int = Query(128, ge=64, le=1024),
    mode: str = Query("crop", pattern="^(crop|fit)$"),
    theme: str = Query("dark"),
    session: AsyncSession = Depends(get_db_session_by_guid)
):
    """
    Get the file system path to a thumbnail (for native drag preview).
    Returns the path to an existing thumbnail, or generates one if needed.
    """
    theme = theme if theme in ('dark', 'light') else 'dark'

    result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Get faces for smart crop
    faces_result = await session.execute(
        select(Face).where(Face.media_id == media_id)
    )
    faces = faces_result.scalars().all()
    faces_data = [face.to_dict() for face in faces] if faces else None

    # Compute cache path (must match get_thumbnail_by_db_guid so the caches are shared)
    settings = get_settings()
    cache_dir = settings.get_thumbnail_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    THUMBNAIL_VERSION = 31  # v31: apply EXIF orientation when generating thumbnails
    face_count = len(faces) if faces else 0

    # For text files and sets, include mtime so edits invalidate the thumbnail cache
    mtime_suffix = ""
    fmt_lower = item.file_format.lower()
    if fmt_lower in ('md', 'stimmaset.json', 'stimmagrid.json', 'stimmalayout'):
        try:
            mtime_path = Path(item.file_path)
            if fmt_lower == 'stimmalayout':
                mtime_path = mtime_path / 'index.html'
            mtime_suffix = f"_mtime{mtime_path.stat().st_mtime}"
        except OSError:
            pass

    # Include theme in cache key only for synthetic thumbnail types
    theme_suffix = f"_theme{theme}" if fmt_lower in THEMED_FORMATS else ""
    cache_key = hashlib.md5(f"{db_guid}_{item.file_path}_{size}_{mode}_{face_count}_v{THUMBNAIL_VERSION}{mtime_suffix}{theme_suffix}".encode()).hexdigest()

    cache_path_png = _sharded_cache_path(cache_dir, cache_key, "png")
    cache_path_jpg = _sharded_cache_path(cache_dir, cache_key, "jpg")

    # Return existing thumbnail path
    if cache_path_png.exists():
        await _record_thumbnail_cache(session, item.id, cache_path_png)
        return {"path": str(cache_path_png)}
    if cache_path_jpg.exists():
        await _record_thumbnail_cache(session, item.id, cache_path_jpg)
        return {"path": str(cache_path_jpg)}

    # Generate thumbnail
    might_have_alpha = item.file_format.lower() == 'png'
    cache_path = cache_path_png if might_have_alpha else cache_path_jpg

    # Ensure shard subdirectory exists
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve palette for synthetic thumbnails
    palette = THEME_PALETTES.get(theme, THEME_PALETTES['dark'])

    if item.file_format.lower() == 'stimmalayout':
        success = await _generate_layout_thumbnail_to_cache(
            item.file_path, cache_path, size, palette=palette,
        ) == LAYOUT_THUMB_OK
    else:
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(
            thumbnail_executor,
            _generate_thumbnail_sync,
            item.file_path,
            item.file_format,
            cache_path,
            size,
            faces_data,
            palette,
            mode,
        )

    if not success:
        # Fall back to original file path if thumbnail generation fails
        return {"path": item.file_path}

    await _record_thumbnail_cache(session, item.id, cache_path)
    return {"path": str(cache_path)}


# ============================================================================
# Bulk Download
# ============================================================================

import zipfile
from datetime import datetime


from typing import Optional, Dict, Any
import subprocess
import tempfile
import shutil


class BulkDownloadRequest(BaseModel):
    media_ids: List[int]


class ResizeOptions(BaseModel):
    mode: str  # "max_dimension", "exact", "scale"
    max_dimension: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    scale: Optional[float] = None


class ExportOptions(BaseModel):
    format: Optional[str] = None  # "jpeg", "png", "webp", "mp4", "webm", "mp3", "wav", "flac"
    quality: Optional[int] = None  # 1-100
    resize: Optional[ResizeOptions] = None
    video_resolution: Optional[str] = None  # "2160", "1080", "720"
    strip_metadata: Optional[bool] = False


class ExportRequest(BaseModel):
    media_ids: List[int]
    options: ExportOptions = ExportOptions()


@router.post("/media/download")
async def bulk_download_media(
    request: BulkDownloadRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Download one or more media files.

    - If 1 item: returns the file directly
    - If multiple items: returns a zip file containing all media
    """
    if not request.media_ids:
        raise HTTPException(status_code=400, detail="No media IDs provided")

    # Fetch all requested media items (including trashed items so we can download from trash)
    result = await session.execute(
        select(MediaItem).where(MediaItem.id.in_(request.media_ids))
    )
    items = result.scalars().all()

    if not items:
        raise HTTPException(status_code=404, detail="No media items found")

    # Check all files exist
    valid_items = []
    for item in items:
        file_path = Path(item.file_path)
        if file_path.exists():
            valid_items.append(item)
        else:
            log.warning(f"File not found for download: {item.file_path}")

    if not valid_items:
        raise HTTPException(status_code=404, detail="No media files found on disk")

    # Single file: return directly
    if len(valid_items) == 1:
        item = valid_items[0]
        file_path = Path(item.file_path)

        # Directory-based media (e.g., .stimmalayout bundles) - zip the directory
        if file_path.is_dir():
            import zipfile
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for child in file_path.rglob('*'):
                    if child.is_file():
                        zf.write(child, f"{file_path.name}/{child.relative_to(file_path)}")
            buffer.seek(0)
            zip_data = buffer.read()
            return StreamingResponse(
                io.BytesIO(zip_data),
                media_type="application/zip",
                headers={
                    'Content-Disposition': f'attachment; filename="{file_path.name}.zip"',
                    'Content-Length': str(len(zip_data)),
                    'Access-Control-Allow-Origin': '*',
                }
            )

        video_formats = {'mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'}
        if item.file_format.lower() in video_formats:
            media_type = f"video/{item.file_format.lower()}"
        else:
            format_map = {
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'png': 'image/png',
                'gif': 'image/gif',
                'webp': 'image/webp',
                'bmp': 'image/bmp'
            }
            media_type = format_map.get(item.file_format.lower(), 'application/octet-stream')

        filename = file_path.name
        return FileResponse(
            file_path,
            media_type=media_type,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Access-Control-Allow-Origin': '*',
            }
        )

    # Multiple files: create zip stream
    def generate_zip():
        """Generator that yields zip file chunks."""
        # Use a BytesIO buffer to accumulate zip data
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            seen_names = {}  # Track filenames to handle duplicates

            for item in valid_items:
                file_path = Path(item.file_path)
                if not file_path.exists():
                    continue

                # Handle duplicate filenames by adding a suffix
                base_name = file_path.name
                if base_name in seen_names:
                    seen_names[base_name] += 1
                    stem = file_path.stem
                    suffix = file_path.suffix
                    base_name = f"{stem}_{seen_names[base_name]}{suffix}"
                else:
                    seen_names[base_name] = 0

                # Write file or directory to zip
                if file_path.is_dir():
                    for child in file_path.rglob('*'):
                        if child.is_file():
                            zf.write(child, f"{base_name}/{child.relative_to(file_path)}")
                else:
                    zf.write(file_path, base_name)

        # Return complete buffer
        buffer.seek(0)
        return buffer.read()

    # Generate the zip file
    zip_data = generate_zip()

    # Create timestamp for filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"stimma-download-{timestamp}.zip"

    return StreamingResponse(
        io.BytesIO(zip_data),
        media_type="application/zip",
        headers={
            'Content-Disposition': f'attachment; filename="{zip_filename}"',
            'Content-Length': str(len(zip_data))
        }
    )


# ============================================================================
# Drag-out metadata payload (hybrid: Python prepares format-specific payload
# strings/bytes here, Tauri Rust side splices them into the source file at
# byte level — avoids PIL pixel re-encode which costs ~500ms on a 1MP PNG and
# multi-seconds on larger images, causing a multi-second drag-start stall).
# ============================================================================

_DRAG_FORMATS = {'png', 'jpg', 'jpeg'}


@router.post("/db/{db_guid}/media/{media_id}/exportable-snapshot")
async def get_exportable_metadata_payload(
    db_guid: str,
    media_id: int,
    session: AsyncSession = Depends(get_db_session_by_guid),
):
    """Return the bits Tauri-side needs to embed A1111 + Stimma metadata into
    the source file at drag time. Pure-string payload — no image work here.

    Response shape:
      { source_path, format, a1111, stimma_json, jpeg_exif_hex }

    `format` is "png" or "jpeg"; "passthrough" indicates nothing to embed —
    caller drags the original file as-is. `jpeg_exif_hex` is populated for
    JPEG only and contains the full EXIF block (piexif.dump output) as hex.
    """
    result = await session.execute(select(MediaItem).where(MediaItem.id == media_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    src_path = Path(item.file_path)
    if not src_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    fmt = (item.file_format or '').lower()
    gen_metadata = metadata_embed.load_generation_metadata(item.generation_metadata)

    if fmt not in _DRAG_FORMATS or gen_metadata is None:
        return {"source_path": str(src_path), "format": "passthrough"}

    input_hashes = await _resolve_input_hash_lookup(session, [item])
    a1111 = metadata_embed.build_a1111_string(gen_metadata)
    sidecar = metadata_embed.build_stimma_sidecar(gen_metadata, input_hashes)
    stimma_json = json.dumps(sidecar, separators=(",", ":"))

    payload = {
        "source_path": str(src_path),
        "format": "jpeg" if fmt in ("jpg", "jpeg") else "png",
        "a1111": a1111,
        "stimma_json": stimma_json,
    }
    if payload["format"] == "jpeg":
        exif_bytes = metadata_embed.build_jpeg_exif(a1111, sidecar)
        payload["jpeg_exif_hex"] = exif_bytes.hex()
    return payload


# ============================================================================
# Export with conversion
# ============================================================================

async def _resolve_input_hash_lookup(
    session: AsyncSession,
    items: list,
) -> dict:
    """Collect file_hashes for any source_input media_ids referenced by the items."""
    import json as _json
    needed: set[int] = set()
    for item in items:
        raw = getattr(item, 'generation_metadata', None)
        if not raw:
            continue
        try:
            parsed = _json.loads(raw)
        except (TypeError, ValueError):
            continue
        for src in (parsed.get('source_inputs') or []):
            mid = src.get('media_id') if isinstance(src, dict) else None
            if isinstance(mid, int):
                needed.add(mid)
    if not needed:
        return {}
    rows = await session.execute(
        select(MediaItem.id, MediaItem.file_hash).where(MediaItem.id.in_(needed))
    )
    return {row.id: row.file_hash for row in rows if row.file_hash}


def _convert_image(
    file_path: Path,
    options: ExportOptions,
    generation_metadata_json: Optional[str] = None,
    input_hash_lookup: Optional[dict] = None,
) -> tuple[io.BytesIO, str, str]:
    """Convert an image according to export options. Returns (buffer, filename, media_type).

    When `options.strip_metadata` is False and `generation_metadata_json` is provided,
    embeds A1111-style `parameters` plus a `stimma` JSON sidecar (PNG tEXt chunks for
    PNG; EXIF UserComment + ImageDescription for JPEG). See metadata_embed module.
    """
    img = Image.open(file_path)
    img = ImageOps.exif_transpose(img)

    # Handle RGBA for formats that don't support it
    target_format = options.format or file_path.suffix.lstrip('.').lower()
    if target_format in ('jpeg', 'jpg') and img.mode in ('RGBA', 'LA', 'P'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        background.paste(img, mask=img.split()[-1] if 'A' in img.mode else None)
        img = background

    # Resize
    if options.resize:
        r = options.resize
        if r.mode == 'max_dimension' and r.max_dimension:
            img.thumbnail((r.max_dimension, r.max_dimension), Image.LANCZOS)
        elif r.mode == 'exact' and r.width and r.height:
            img = img.resize((r.width, r.height), Image.LANCZOS)
        elif r.mode == 'scale' and r.scale:
            new_w = max(1, int(img.width * r.scale))
            new_h = max(1, int(img.height * r.scale))
            img = img.resize((new_w, new_h), Image.LANCZOS)

    # Strip metadata by clearing the info dict (EXIF, ICC, etc.)
    if options.strip_metadata:
        img.info = {}
        if hasattr(img, '_exif'):
            img._exif = None

    # Save to buffer
    buffer = io.BytesIO()
    save_kwargs = {}

    format_map = {
        'jpeg': ('JPEG', 'image/jpeg', '.jpg'),
        'jpg': ('JPEG', 'image/jpeg', '.jpg'),
        'png': ('PNG', 'image/png', '.png'),
        'webp': ('WEBP', 'image/webp', '.webp'),
    }

    pil_format, media_type, ext = format_map.get(target_format, ('PNG', 'image/png', '.png'))

    if pil_format in ('JPEG', 'WEBP'):
        save_kwargs['quality'] = options.quality or 85

    # Build A1111 + Stimma metadata when not stripping and we have generation data.
    gen_metadata = None
    if not options.strip_metadata and generation_metadata_json:
        gen_metadata = metadata_embed.load_generation_metadata(generation_metadata_json)

    if gen_metadata and pil_format == 'PNG':
        a1111 = metadata_embed.build_a1111_string(gen_metadata)
        sidecar = metadata_embed.build_stimma_sidecar(gen_metadata, input_hash_lookup)
        save_kwargs['pnginfo'] = metadata_embed.attach_png_metadata(img, a1111, sidecar)
    elif gen_metadata and pil_format == 'JPEG':
        a1111 = metadata_embed.build_a1111_string(gen_metadata)
        sidecar = metadata_embed.build_stimma_sidecar(gen_metadata, input_hash_lookup)
        save_kwargs['exif'] = metadata_embed.build_jpeg_exif(a1111, sidecar, img.info.get('exif'))

    img.save(buffer, format=pil_format, **save_kwargs)
    buffer.seek(0)

    filename = file_path.stem + ext
    return buffer, filename, media_type


def _convert_video(file_path: Path, options: ExportOptions, tmp_dir: str) -> tuple[Path, str, str]:
    """Convert a video using ffmpeg. Returns (output_path, filename, media_type)."""
    target_format = options.format or file_path.suffix.lstrip('.').lower()

    format_info = {
        'mp4': ('mp4', 'video/mp4', '.mp4'),
        'webm': ('webm', 'video/webm', '.webm'),
    }
    container, media_type, ext = format_info.get(target_format, ('mp4', 'video/mp4', '.mp4'))

    output_filename = file_path.stem + ext
    output_path = Path(tmp_dir) / output_filename

    cmd = ['ffmpeg', '-y', '-i', str(file_path)]

    # Video codec
    if container == 'mp4':
        cmd += ['-c:v', 'libx264', '-preset', 'medium']
    elif container == 'webm':
        cmd += ['-c:v', 'libvpx-vp9']

    # Quality (CRF)
    if options.quality:
        # Map 1-100 quality to CRF (lower CRF = higher quality)
        # CRF range: 0-51 for x264, 0-63 for VP9
        if container == 'mp4':
            crf = max(0, min(51, int(51 - (options.quality / 100 * 41))))
            cmd += ['-crf', str(crf)]
        elif container == 'webm':
            crf = max(0, min(63, int(63 - (options.quality / 100 * 53))))
            cmd += ['-crf', str(crf), '-b:v', '0']

    # Resolution
    if options.video_resolution and options.video_resolution != 'original':
        height = int(options.video_resolution)
        cmd += ['-vf', f'scale=-2:{height}']

    # Audio
    if container == 'mp4':
        cmd += ['-c:a', 'aac']
    elif container == 'webm':
        cmd += ['-c:a', 'libopus']

    cmd.append(str(output_path))

    result = subprocess.run(cmd, capture_output=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()[:500]}")

    return output_path, output_filename, media_type


def _convert_audio(file_path: Path, options: ExportOptions, tmp_dir: str) -> tuple[Path, str, str]:
    """Convert an audio file using ffmpeg. Returns (output_path, filename, media_type)."""
    target_format = options.format or file_path.suffix.lstrip('.').lower()

    format_info = {
        'mp3': ('mp3', 'audio/mpeg', '.mp3'),
        'wav': ('wav', 'audio/wav', '.wav'),
        'flac': ('flac', 'audio/flac', '.flac'),
    }
    container, media_type, ext = format_info.get(target_format, ('mp3', 'audio/mpeg', '.mp3'))

    output_filename = file_path.stem + ext
    output_path = Path(tmp_dir) / output_filename

    cmd = ['ffmpeg', '-y', '-i', str(file_path)]

    if container == 'mp3':
        # Map quality 1-100 to bitrate
        bitrate = options.quality * 3.2 if options.quality else 256
        bitrate = max(64, min(320, int(bitrate)))
        cmd += ['-c:a', 'libmp3lame', '-b:a', f'{bitrate}k']
    elif container == 'wav':
        cmd += ['-c:a', 'pcm_s16le']
    elif container == 'flac':
        cmd += ['-c:a', 'flac']

    cmd.append(str(output_path))

    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()[:500]}")

    return output_path, output_filename, media_type


IMAGE_EXPORT_FORMATS = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'heic', 'heif'}
VIDEO_EXPORT_FORMATS = {'mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'}
AUDIO_EXPORT_FORMATS = {'mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg'}


@router.post("/media/export")
async def export_media(
    request: ExportRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Export media with optional format conversion, resize, and metadata stripping.
    """
    if not request.media_ids:
        raise HTTPException(status_code=400, detail="No media IDs provided")

    result = await session.execute(
        select(MediaItem).where(MediaItem.id.in_(request.media_ids))
    )
    items = result.scalars().all()

    if not items:
        raise HTTPException(status_code=404, detail="No media items found")

    valid_items = []
    for item in items:
        file_path = Path(item.file_path)
        if file_path.exists():
            valid_items.append(item)
        else:
            log.warning(f"File not found for export: {item.file_path}")

    if not valid_items:
        raise HTTPException(status_code=404, detail="No media files found on disk")

    from telemetry import get_telemetry_client
    get_telemetry_client().track("media_exported", {"count": len(valid_items)})

    opts = request.options
    tmp_dir = None
    input_hashes = await _resolve_input_hash_lookup(session, valid_items)

    try:
        # Single file export
        if len(valid_items) == 1:
            item = valid_items[0]
            file_path = Path(item.file_path)
            fmt = (item.file_format or '').lower()

            if fmt in IMAGE_EXPORT_FORMATS:
                buf, filename, media_type = _convert_image(
                    file_path, opts, item.generation_metadata, input_hashes
                )
                return StreamingResponse(
                    buf,
                    media_type=media_type,
                    headers={
                        'Content-Disposition': f'attachment; filename="{filename}"',
                        'Access-Control-Allow-Origin': '*',
                    }
                )
            elif fmt in VIDEO_EXPORT_FORMATS:
                tmp_dir = tempfile.mkdtemp(prefix='stimma-export-')
                output_path, filename, media_type = _convert_video(file_path, opts, tmp_dir)
                return FileResponse(
                    output_path,
                    media_type=media_type,
                    headers={
                        'Content-Disposition': f'attachment; filename="{filename}"',
                        'Access-Control-Allow-Origin': '*',
                    },
                    background=None  # cleanup handled below
                )
            elif fmt in AUDIO_EXPORT_FORMATS:
                tmp_dir = tempfile.mkdtemp(prefix='stimma-export-')
                output_path, filename, media_type = _convert_audio(file_path, opts, tmp_dir)
                return FileResponse(
                    output_path,
                    media_type=media_type,
                    headers={
                        'Content-Disposition': f'attachment; filename="{filename}"',
                        'Access-Control-Allow-Origin': '*',
                    },
                    background=None
                )

        # Multiple files: export to zip
        tmp_dir = tempfile.mkdtemp(prefix='stimma-export-')
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            seen_names = {}

            for item in valid_items:
                file_path = Path(item.file_path)
                if not file_path.exists():
                    continue

                fmt = (item.file_format or '').lower()

                try:
                    if fmt in IMAGE_EXPORT_FORMATS:
                        buf, filename, _ = _convert_image(
                            file_path, opts, item.generation_metadata, input_hashes
                        )
                        data = buf.read()
                    elif fmt in VIDEO_EXPORT_FORMATS:
                        output_path, filename, _ = _convert_video(file_path, opts, tmp_dir)
                        data = output_path.read_bytes()
                    elif fmt in AUDIO_EXPORT_FORMATS:
                        output_path, filename, _ = _convert_audio(file_path, opts, tmp_dir)
                        data = output_path.read_bytes()
                    else:
                        filename = file_path.name
                        if file_path.is_dir():
                            data = None  # handled below
                        else:
                            data = file_path.read_bytes()
                except Exception as e:
                    log.warning(f"Failed to convert {file_path.name}: {e}")
                    # Fall back to original file
                    filename = file_path.name
                    if file_path.is_dir():
                        data = None
                    else:
                        data = file_path.read_bytes()

                # Handle duplicate filenames
                if filename in seen_names:
                    seen_names[filename] += 1
                    stem = Path(filename).stem
                    suffix = Path(filename).suffix
                    filename = f"{stem}_{seen_names[filename]}{suffix}"
                else:
                    seen_names[filename] = 0

                if data is None and file_path.is_dir():
                    # Directory-based media: add all files under the directory name
                    for child in file_path.rglob('*'):
                        if child.is_file():
                            zf.write(child, f"{filename}/{child.relative_to(file_path)}")
                else:
                    zf.writestr(filename, data)

        buffer.seek(0)
        zip_data = buffer.read()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"stimma-export-{timestamp}.zip"

        return StreamingResponse(
            io.BytesIO(zip_data),
            media_type="application/zip",
            headers={
                'Content-Disposition': f'attachment; filename="{zip_filename}"',
                'Content-Length': str(len(zip_data))
            }
        )
    finally:
        # Clean up temp directory in background
        if tmp_dir:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass
