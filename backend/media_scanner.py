import os
import hashlib
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple, AsyncGenerator
from PIL import Image, ImageOps
import asyncio

from core.logging import get_logger
from utils.image_ops import has_alpha_channel

log = get_logger(__name__)

# Supported file extensions
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.ogg'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.aac', '.m4a', '.ogg'}
# Structured media types: markdown files (.md) and compound extensions (.stimmaset.json, etc.)
TEXT_EXTENSIONS = {'.md'}
SET_EXTENSIONS = {'.stimmaset.json'}
GRID_EXTENSIONS = {'.stimmagrid.json'}
LAYOUT_EXTENSIONS = {'.stimmalayout'}  # Directory-based bundles (contains index.html + assets)
STRUCTURED_EXTENSIONS = TEXT_EXTENSIONS | SET_EXTENSIONS | GRID_EXTENSIONS | LAYOUT_EXTENSIONS

# All supported extensions
ALL_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | STRUCTURED_EXTENSIONS


def get_file_extension(file_path: Path) -> str:
    """
    Get the file extension, handling compound extensions for structured types.

    For structured media (.md, .stimmaset.json, .stimmagrid.json),
    returns the compound extension. For regular files, returns the simple suffix.

    Returns extension with leading dot (e.g., '.png', '.md', '.stimmaset.json')
    """
    name = file_path.name.lower()

    # Check for compound extensions first
    for ext in STRUCTURED_EXTENSIONS:
        if name.endswith(ext):
            return ext

    # Fall back to simple suffix
    return file_path.suffix.lower()


def is_layout_directory(dir_path: Path) -> bool:
    """Check if a directory is a .stimmalayout bundle (contains index.html)."""
    return dir_path.name.lower().endswith('.stimmalayout') and (dir_path / 'index.html').exists()


def is_supported_extension(file_path: Path) -> bool:
    """Check if a file has a supported extension."""
    ext = get_file_extension(file_path)
    return ext in ALL_EXTENSIONS


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_image_dimensions(file_path: Path) -> Tuple[int, int, bool]:
    """Get width, height, and alpha-channel presence of an image, honoring EXIF orientation."""
    with Image.open(file_path) as img:
        has_alpha = has_alpha_channel(img)
        rotated = ImageOps.exif_transpose(img)
        width, height = rotated.size
        return width, height, has_alpha


def get_video_dimensions(file_path: Path) -> Tuple[int, int, Optional[float]]:
    """
    Get width, height, and duration of a video.
    Returns (width, height, duration_in_seconds)
    """
    try:
        import ffmpeg
        probe = ffmpeg.probe(str(file_path))

        video_stream = next(
            (stream for stream in probe['streams'] if stream['codec_type'] == 'video'),
            None
        )

        if video_stream is None:
            raise ValueError("No video stream found")

        width = int(video_stream['width'])
        height = int(video_stream['height'])

        # Get duration
        duration = None
        if 'duration' in video_stream:
            duration = float(video_stream['duration'])
        elif 'duration' in probe.get('format', {}):
            duration = float(probe['format']['duration'])

        return width, height, duration
    except Exception as e:
        log.warning(f"Failed to get video dimensions for {file_path}: {e}")
        # Fallback: try to get first frame dimensions
        try:
            with Image.open(file_path) as img:
                width, height = img.size
                return width, height, None
        except:
            return 1920, 1080, None  # Default fallback


def get_file_dates(file_path: Path) -> Tuple[Optional[datetime], datetime]:
    """
    Get creation and modification dates.
    Returns (created_date, modified_date)
    """
    stat = file_path.stat()

    # Try to get creation time (platform-dependent)
    try:
        created_date = datetime.utcfromtimestamp(stat.st_birthtime)
    except AttributeError:
        # Fall back to modification time on platforms without birthtime
        created_date = datetime.utcfromtimestamp(stat.st_mtime)

    modified_date = datetime.utcfromtimestamp(stat.st_mtime)

    return created_date, modified_date


async def fast_scan_directories(paths: List[str]) -> List[dict]:
    """
    Ultra-fast file discovery - loads all paths and basic stats into RAM.

    This function does ZERO heavy I/O:
    - Only stat() syscalls for file metadata
    - No file reading (no hashing, no dimensions, no EXIF)
    - No database operations

    Returns list of dicts with basic file info for batched DB operations.

    Args:
        paths: List of directory paths to scan

    Returns:
        List of dicts with: file_path, file_size, file_format, created_date, modified_date
    """
    log.debug(f"FAST DISCOVERY: Starting ultra-fast scan of {len(paths)} path(s)")
    files = []

    for path_str in paths:
        path = Path(path_str).expanduser().resolve()
        log.debug(f"FAST DISCOVERY: Scanning path: {path}")

        if not path.exists():
            log.warning(f"FAST DISCOVERY: Path does not exist: {path}")
            continue

        if path.is_file():
            if is_supported_extension(path):
                stat = path.stat()
                ext = get_file_extension(path)
                files.append({
                    'file_path': str(path),
                    'file_size': stat.st_size,
                    'file_format': ext[1:],  # Remove leading dot
                    'created_date': datetime.utcfromtimestamp(getattr(stat, 'st_birthtime', stat.st_mtime)),
                    'modified_date': datetime.utcfromtimestamp(stat.st_mtime),
                })
        elif path.is_dir():
            # Fast directory walk - just stat() calls
            for root, dirs, filenames in os.walk(path):
                # Check for .stimmalayout directories (treat as media items, don't descend into them)
                layout_dirs = []
                for d in dirs:
                    dir_path = Path(root) / d
                    if is_layout_directory(dir_path):
                        layout_dirs.append(d)
                        try:
                            index_path = dir_path / 'index.html'
                            stat = index_path.stat()
                            files.append({
                                'file_path': str(dir_path),
                                'file_size': stat.st_size,
                                'file_format': 'stimmalayout',
                                'created_date': datetime.utcfromtimestamp(getattr(stat, 'st_birthtime', stat.st_mtime)),
                                'modified_date': datetime.utcfromtimestamp(stat.st_mtime),
                            })
                        except (OSError, IOError) as e:
                            log.warning(f"FAST DISCOVERY: Cannot stat layout dir {dir_path}: {e}")
                # Don't descend into layout directories
                for ld in layout_dirs:
                    dirs.remove(ld)

                for filename in filenames:
                    file_path = Path(root) / filename
                    if is_supported_extension(file_path):
                        try:
                            stat = file_path.stat()
                            ext = get_file_extension(file_path)
                            files.append({
                                'file_path': str(file_path),
                                'file_size': stat.st_size,
                                'file_format': ext[1:],  # Remove leading dot
                                'created_date': datetime.utcfromtimestamp(getattr(stat, 'st_birthtime', stat.st_mtime)),
                                'modified_date': datetime.utcfromtimestamp(stat.st_mtime),
                            })
                        except (OSError, IOError) as e:
                            log.warning(f"FAST DISCOVERY: Cannot stat {file_path}: {e}")
                            continue

                # Yield control periodically
                if len(files) % 1000 == 0:
                    await asyncio.sleep(0)

    log.debug(f"FAST DISCOVERY: Completed - found {len(files)} files in RAM")
    return files


async def scan_directories(paths: List[str]) -> AsyncGenerator[Path, None]:
    """
    Recursively scan directories for media files.

    Args:
        paths: List of directory paths to scan

    Yields:
        Path objects for media files
    """
    log.info(f"FILE DISCOVERY: Starting scan of {len(paths)} path(s)")
    for path_str in paths:
        path = Path(path_str).expanduser().resolve()
        log.info(f"FILE DISCOVERY: Scanning path: {path}")

        if not path.exists():
            log.warning(f"FILE DISCOVERY: Path does not exist: {path}")
            continue

        if path.is_file():
            if is_supported_extension(path):
                log.info(f"FILE DISCOVERY: Found media file: {path}")
                yield path
        elif path.is_dir():
            log.info(f"FILE DISCOVERY: Walking directory tree: {path}")
            # Recursively walk directory
            file_count = 0
            for root, dirs, files in os.walk(path):
                # Check for .stimmalayout directories
                layout_dirs = []
                for d in dirs:
                    dir_path = Path(root) / d
                    if is_layout_directory(dir_path):
                        layout_dirs.append(d)
                        file_count += 1
                        log.info(f"FILE DISCOVERY: Found layout bundle #{file_count}: {dir_path}")
                        yield dir_path
                # Don't descend into layout directories
                for ld in layout_dirs:
                    dirs.remove(ld)

                for filename in files:
                    file_path = Path(root) / filename
                    if is_supported_extension(file_path):
                        file_count += 1
                        log.info(f"FILE DISCOVERY: Found media file #{file_count}: {file_path}")
                        yield file_path

                # Allow other coroutines to run
                await asyncio.sleep(0)
            log.info(f"FILE DISCOVERY: Completed scanning {path} - found {file_count} files")


def get_audio_metadata(file_path: Path) -> dict:
    """
    Get metadata for an audio file using ffmpeg.

    Returns dict with:
        - duration: float or None (seconds)
        - sample_rate: int or None (Hz, e.g., 44100)
        - channels: int or None (1=mono, 2=stereo)
        - bit_depth: int or None (bits per sample)
        - bitrate: int or None (bits per second)
        - codec: str or None (codec name)
    """
    result = {
        'duration': None,
        'sample_rate': None,
        'channels': None,
        'bit_depth': None,
        'bitrate': None,
        'codec': None,
    }

    try:
        import ffmpeg
        probe = ffmpeg.probe(str(file_path))

        # Get duration from format metadata
        if 'duration' in probe.get('format', {}):
            result['duration'] = float(probe['format']['duration'])

        # Get bitrate from format (overall file bitrate)
        if 'bit_rate' in probe.get('format', {}):
            result['bitrate'] = int(probe['format']['bit_rate'])

        # Get details from audio stream
        audio_stream = next(
            (stream for stream in probe['streams'] if stream['codec_type'] == 'audio'),
            None
        )

        if audio_stream:
            # Duration fallback
            if result['duration'] is None and 'duration' in audio_stream:
                result['duration'] = float(audio_stream['duration'])

            # Sample rate
            if 'sample_rate' in audio_stream:
                result['sample_rate'] = int(audio_stream['sample_rate'])

            # Channels
            if 'channels' in audio_stream:
                result['channels'] = int(audio_stream['channels'])

            # Codec name
            if 'codec_name' in audio_stream:
                result['codec'] = audio_stream['codec_name']

            # Bit depth - varies by codec
            # For PCM formats, it's in bits_per_sample or bits_per_raw_sample
            # For compressed formats like FLAC, it's in bits_per_raw_sample
            if 'bits_per_sample' in audio_stream and audio_stream['bits_per_sample'] > 0:
                result['bit_depth'] = int(audio_stream['bits_per_sample'])
            elif 'bits_per_raw_sample' in audio_stream:
                try:
                    result['bit_depth'] = int(audio_stream['bits_per_raw_sample'])
                except (ValueError, TypeError):
                    pass

            # Stream-specific bitrate (more accurate than format bitrate for audio-only)
            if 'bit_rate' in audio_stream:
                result['bitrate'] = int(audio_stream['bit_rate'])

    except Exception as e:
        log.warning(f"Failed to get audio metadata for {file_path}: {e}")

    return result


def get_audio_duration(file_path: Path) -> Optional[float]:
    """
    Get duration of an audio file using ffmpeg.
    Returns duration in seconds or None if extraction fails.

    Note: For full metadata, use get_audio_metadata() instead.
    """
    return get_audio_metadata(file_path)['duration']


def parse_structured_media(file_path: Path) -> Optional[dict]:
    """
    Parse a structured media file (.stimmaset.json, .stimmagrid.json).
    Returns the parsed JSON content or None if parsing fails.
    """
    import json
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"Failed to parse structured media file {file_path}: {e}")
        return None


def parse_markdown_frontmatter(file_path: Path) -> Optional[dict]:
    """
    Extract only the YAML front matter from a markdown file.
    Content is read from disk at display time, not stored in database.
    Returns dict with frontmatter fields, or None if parsing fails.
    """
    try:
        import frontmatter
        with open(file_path, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
        return dict(post.metadata) if post.metadata else {}
    except Exception as e:
        log.warning(f"Failed to parse markdown frontmatter {file_path}: {e}")
        return None


def extract_metadata(file_path: Path) -> dict:
    """
    Extract metadata from a media file.

    Returns:
        Dictionary with file metadata
    """
    ext = get_file_extension(file_path)
    is_video = ext in VIDEO_EXTENSIONS
    is_audio = ext in AUDIO_EXTENSIONS
    is_structured = ext in STRUCTURED_EXTENSIONS
    is_layout = ext in LAYOUT_EXTENSIONS

    # Get file info — for directory-based media, use index.html
    if is_layout and file_path.is_dir():
        index_file = file_path / 'index.html'
        file_size = index_file.stat().st_size if index_file.exists() else 0
        created_date, modified_date = get_file_dates(index_file if index_file.exists() else file_path)
        file_hash = compute_file_hash(index_file) if index_file.exists() else ""
    else:
        file_size = file_path.stat().st_size
        created_date, modified_date = get_file_dates(file_path)
        file_hash = compute_file_hash(file_path)

    # Initialize defaults
    width = 0
    height = 0
    has_alpha = None
    duration = None
    raw_metadata = None
    audio_sample_rate = None
    audio_channels = None
    audio_bit_depth = None
    audio_bitrate = None
    audio_codec = None

    # Get dimensions/duration based on type
    if is_video:
        width, height, duration = get_video_dimensions(file_path)
        has_alpha = False  # No video format in this pipeline carries real alpha
    elif is_audio:
        # Audio has no visual dimensions but has audio-specific metadata
        audio_meta = get_audio_metadata(file_path)
        duration = audio_meta['duration']
        audio_sample_rate = audio_meta['sample_rate']
        audio_channels = audio_meta['channels']
        audio_bit_depth = audio_meta['bit_depth']
        audio_bitrate = audio_meta['bitrate']
        audio_codec = audio_meta['codec']
        has_alpha = False
    elif is_structured:
        # Parse structured media for raw_metadata storage
        import json
        if ext == '.md':
            # Markdown: only store frontmatter, content is read from disk at display time
            frontmatter = parse_markdown_frontmatter(file_path)
            if frontmatter:
                raw_metadata = json.dumps({'frontmatter': frontmatter})
        else:
            # JSON-based structured types (.stimmaset.json, .stimmagrid.json)
            parsed = parse_structured_media(file_path)
            if parsed:
                raw_metadata = json.dumps(parsed)
    else:
        # Regular image
        width, height, has_alpha = get_image_dimensions(file_path)

    megapixels = (width * height) / 1_000_000 if width > 0 and height > 0 else 0

    return {
        "file_path": str(file_path),
        "file_hash": file_hash,
        "file_size": file_size,
        "file_format": ext[1:],  # Remove the leading dot
        "width": width,
        "height": height,
        "has_alpha": has_alpha,
        "megapixels": megapixels,
        "duration": duration,
        "created_date": created_date,
        "modified_date": modified_date,
        "raw_metadata": raw_metadata,
        # Audio-specific metadata
        "audio_sample_rate": audio_sample_rate,
        "audio_channels": audio_channels,
        "audio_bit_depth": audio_bit_depth,
        "audio_bitrate": audio_bitrate,
        "audio_codec": audio_codec,
    }
