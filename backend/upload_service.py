"""
Upload service for library-integrated file uploads.

This service handles uploading files directly into the library with immediate
database record creation and synchronous metadata extraction. Background
processing (CLIP, captions, etc.) is triggered asynchronously.
"""

import os
import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List
from PIL import Image

from config import get_settings, FolderConfig
from config_version import get_config_version_manager
from database import MediaItem
from database_registry import get_database_registry
from core.logging import get_logger
from core.app import get_process_pending_event
from core.profile_context import get_current_profile
from media_scanner import VIDEO_EXTENSIONS
from project_service import attach_media_to_project

log = get_logger(__name__)


class UploadError(Exception):
    """Error during file upload."""
    pass


class NoUploadsFolderError(UploadError):
    """No uploads folder configured for the profile."""
    pass


class UploadService:
    """Service for uploading files to the library."""

    ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
    ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov', '.avi', '.mkv'}
    # Mirrors media_scanner.AUDIO_EXTENSIONS
    ALLOWED_AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.aac', '.m4a', '.ogg'}
    ALLOWED_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS | ALLOWED_AUDIO_EXTENSIONS

    def __init__(self, profile_id: str = None):
        self.profile_id = profile_id or get_current_profile()
        self.settings = get_settings()

    def get_uploads_folder(self) -> FolderConfig:
        """Get the uploads folder for the current profile.

        Raises:
            NoUploadsFolderError: If no uploads folder is configured.
        """
        folder = self.settings.get_uploads_folder_for_profile(self.profile_id)
        if folder is None:
            raise NoUploadsFolderError(
                f"No uploads folder configured for profile '{self.profile_id}'. "
                f"Add 'is_uploads_folder: true' to one of your folders in config.yaml."
            )
        return folder

    def get_upload_destination(self, original_filename: str, project_id: Optional[int] = None) -> Tuple[Path, str]:
        """Get the destination path for an uploaded file.

        Returns:
            Tuple of (full_path, relative_subfolder)
        """
        folder = self.get_uploads_folder()

        # Build subfolder path: uploads_subfolder/YYYY/MM
        now = datetime.now()
        subfolder = Path(folder.uploads_subfolder) / str(now.year) / f"{now.month:02d}"

        # Build destination directory
        dest_dir = Path(folder.path) / subfolder
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename
        ext = Path(original_filename).suffix.lower()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        filename = f"upload_{timestamp}_{unique_id}{ext}"

        return dest_dir / filename, str(subfolder)

    def validate_file(self, filename: str) -> str:
        """Validate file extension and return the normalized extension.

        Raises:
            UploadError: If file type is not allowed.
        """
        ext = Path(filename).suffix.lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            raise UploadError(
                f"File type '{ext}' not allowed. "
                f"Allowed types: {', '.join(sorted(self.ALLOWED_EXTENSIONS))}"
            )
        return ext

    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file."""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _get_image_dimensions(self, file_path: Path) -> Tuple[int, int, Optional[bool]]:
        """Get image dimensions and alpha-channel presence, honoring EXIF orientation."""
        try:
            from PIL import ImageOps
            from utils.image_ops import has_alpha_channel
            with Image.open(file_path) as img:
                has_alpha = has_alpha_channel(img)
                rotated = ImageOps.exif_transpose(img)
                width, height = rotated.size
            return width, height, has_alpha
        except Exception as e:
            log.warning(f"Failed to get image dimensions for {file_path}: {e}")
            return 0, 0, None

    def _get_video_dimensions(self, file_path: Path) -> Tuple[int, int]:
        """Get video dimensions using ffprobe."""
        import subprocess
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=width,height', '-of', 'csv=p=0', str(file_path)],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(',')
                return int(parts[0]), int(parts[1])
        except Exception as e:
            log.warning(f"Failed to get video dimensions for {file_path}: {e}")
        return 0, 0

    def _compute_content_hash(self, content: bytes) -> str:
        """Compute SHA256 hash of content bytes."""
        return hashlib.sha256(content).hexdigest()

    async def upload_file(
        self,
        file_content: bytes,
        original_filename: str,
        project_id: Optional[int] = None,
        materialize_asset: bool = True,
    ) -> Tuple[MediaItem, str]:
        """
        Upload a file to the library and create a database record.

        This method:
        1. Validates the file type
        2. Checks if file already exists by hash (deduplication)
        3. Saves to the uploads folder with date organization
        4. Computes dimensions synchronously
        5. Creates MediaItem database record
        6. Signals ingestion worker for background processing

        Args:
            file_content: The file bytes to save
            original_filename: Original name of the uploaded file

        Returns:
            Tuple of (MediaItem, file_path as string)

        Raises:
            NoUploadsFolderError: If no uploads folder configured
            UploadError: If file validation or save fails
        """
        # Validate file type
        ext = self.validate_file(original_filename)

        # Media identity is per import/save operation. Byte deduplication happens
        # below Media at StorageObject, so identical uploads still produce
        # distinct provenance-bearing Media identities.
        file_hash = self._compute_content_hash(file_content)

        # Get destination path
        dest_path, subfolder = self.get_upload_destination(original_filename, project_id=project_id)

        try:
            # Write file to disk
            with open(dest_path, 'wb') as f:
                f.write(file_content)

            # Get file stats
            stat_info = os.stat(dest_path)

            # Compute hash
            file_hash = self._compute_file_hash(dest_path)

            # Determine media kind
            is_video = ext in self.ALLOWED_VIDEO_EXTENSIONS
            is_audio = ext in self.ALLOWED_AUDIO_EXTENSIONS
            file_format = ext.lstrip('.')

            # Get dimensions (audio has none)
            duration = None
            audio_sample_rate = None
            audio_channels = None
            audio_bit_depth = None
            audio_bitrate = None
            audio_codec = None
            has_alpha = None
            if is_audio:
                width, height = 0, 0
                # Audio has no visual dimensions but has audio-specific metadata.
                # Extract it inline (same extractor as the scan/ingestion and
                # generation paths) so uploaded audio is a first-class media item
                # with duration + sample rate + channels + codec. Uploads set
                # metadata_status='completed', so the background metadata pass
                # never backfills this — it must happen here.
                try:
                    from media_scanner import get_audio_metadata
                    audio_meta = get_audio_metadata(dest_path)
                    duration = audio_meta.get('duration')
                    audio_sample_rate = audio_meta.get('sample_rate')
                    audio_channels = audio_meta.get('channels')
                    audio_bit_depth = audio_meta.get('bit_depth')
                    audio_bitrate = audio_meta.get('bitrate')
                    audio_codec = audio_meta.get('codec')
                except Exception as e:
                    log.warning(f"Failed to extract audio metadata from upload {dest_path}: {e}")
                has_alpha = False
            elif is_video:
                width, height = self._get_video_dimensions(dest_path)
                has_alpha = False
            else:
                width, height, has_alpha = self._get_image_dimensions(dest_path)

            megapixels = (width * height) / 1_000_000

            # Extract raw metadata from external images (ComfyUI, A1111, etc.)
            raw_metadata = None
            extracted_prompt = None
            generation_metadata = None
            if not is_video and not is_audio:
                try:
                    from exif_extractor import extract_prompt_from_exif, parse_external_metadata
                    raw_metadata, extracted_prompt = extract_prompt_from_exif(dest_path)
                    if raw_metadata:
                        log.info(f"Extracted raw metadata from upload: {len(raw_metadata)} chars")
                        # Parse structured parameters from external metadata
                        parsed = parse_external_metadata(raw_metadata)
                        if parsed:
                            import json as _json
                            generation_metadata = _json.dumps(parsed)
                            log.info(f"Parsed external generation metadata from upload")
                except Exception as e:
                    log.warning(f"Failed to extract metadata from upload {dest_path}: {e}")

            # Create database record
            db = get_database_registry().get_database(self.profile_id)
            async with db.async_session_maker() as session:
                from sqlalchemy import select
                from sqlalchemy.exc import IntegrityError

                media_item = MediaItem(
                    file_path=str(dest_path),
                    file_hash=file_hash,
                    file_size=stat_info.st_size,
                    file_format=file_format,
                    original_filename=original_filename,
                    created_date=datetime.utcfromtimestamp(stat_info.st_ctime),
                    modified_date=datetime.utcfromtimestamp(stat_info.st_mtime),
                    indexed_date=datetime.utcnow(),
                    metadata_status='completed',
                    metadata_processed_at=datetime.utcnow(),
                    metadata_config_version=get_config_version_manager().get_version('metadata'),
                    width=width,
                    height=height,
                    has_alpha=has_alpha,
                    megapixels=megapixels,
                    duration=duration,
                    audio_sample_rate=audio_sample_rate,
                    audio_channels=audio_channels,
                    audio_bit_depth=audio_bit_depth,
                    audio_bitrate=audio_bitrate,
                    audio_codec=audio_codec,
                    raw_metadata=raw_metadata,
                    extracted_prompt=extracted_prompt,
                    generation_metadata=generation_metadata,
                )

                session.add(media_item)
                try:
                    await session.flush()
                    from asset_service import create_asset_from_media
                    from storage_service import stage_managed_media
                    await stage_managed_media(
                        session,
                        media=media_item,
                        profile_id=self.profile_id,
                        remove_source=True,
                    )
                    asset = None
                    if materialize_asset:
                        asset = await create_asset_from_media(
                            session,
                            media_id=media_item.id,
                            origin_type="upload",
                        )
                    else:
                        from asset_service import acquire_media_owner
                        await acquire_media_owner(
                            session,
                            media_id=media_item.id,
                            root_kind="upload",
                            root_id=media_item.id,
                            role="provisional",
                            idempotency_key=f"upload:{media_item.id}:provisional",
                        )
                    await session.commit()
                    await session.refresh(media_item)
                    if project_id is not None:
                        await attach_media_to_project(session, project_id, media_item.id)
                        if asset is not None:
                            from asset_association_service import attach_asset_to_project
                            await attach_asset_to_project(session, project_id, asset.id)
                        await session.commit()
                    try:
                        from storage_service import cleanup_staged_source
                        await cleanup_staged_source(session, media_id=media_item.id)
                    except Exception as exc:
                        log.warning(f"Deferred upload-source cleanup: {type(exc).__name__}")
                    log.info(f"Created media item {media_item.id} for upload: {dest_path}")
                except IntegrityError:
                    # File already exists - fetch existing record
                    await session.rollback()
                    result = await session.execute(
                        select(MediaItem).where(MediaItem.file_path == str(dest_path))
                        .order_by(MediaItem.id.desc()).limit(1)
                    )
                    media_item = result.scalar_one_or_none()
                    if media_item is None:
                        raise UploadError(f"Failed to create or find media item for {dest_path}")
                    if project_id is not None:
                        await attach_media_to_project(session, project_id, media_item.id)
                        await session.commit()

                # Signal ingestion worker for background processing (CLIP, captions, etc.)
                process_pending_event = get_process_pending_event()
                if process_pending_event:
                    process_pending_event.set()

                return media_item, media_item.file_path

        except UploadError:
            raise
        except Exception as e:
            # Clean up file on failure
            if dest_path.exists():
                dest_path.unlink()
            log.error(f"Upload failed for {original_filename}: {e}")
            raise UploadError(f"Upload failed: {e}")

    async def copy_existing_to_library(
        self,
        source_path: str,
    ) -> Tuple[MediaItem, str]:
        """
        Copy an existing file into the uploads library folder.

        Used when "sending" an existing library image to a generation task -
        creates a separate copy so the original is preserved.

        Args:
            source_path: Path to existing file to copy

        Returns:
            Tuple of (MediaItem, new_file_path as string)
        """
        source = Path(source_path)
        if not source.exists():
            raise UploadError(f"Source file not found: {source_path}")

        # Read file content
        with open(source, 'rb') as f:
            content = f.read()

        # Upload as new file
        return await self.upload_file(content, source.name)

    async def upload_multiple(
        self,
        files: List[Tuple[bytes, str]],
    ) -> List[dict]:
        """
        Upload multiple files to the library.

        Args:
            files: List of (file_content, original_filename) tuples

        Returns:
            List of result dicts with keys:
                - filename: Original filename
                - status: "success" or "error"
                - path: File path (if success)
                - media_id: MediaItem ID (if success)
                - file_hash: File hash (if success)
                - width, height: Dimensions (if success)
                - error: Error message (if error)
        """
        results = []

        for content, filename in files:
            try:
                media_item, path = await self.upload_file(content, filename)
                results.append({
                    "filename": filename,
                    "status": "success",
                    "path": path,
                    "media_id": media_item.id,
                    "file_hash": media_item.file_hash,
                    "width": media_item.width,
                    "height": media_item.height,
                })
            except Exception as e:
                results.append({
                    "filename": filename,
                    "status": "error",
                    "error": str(e),
                })

        return results


# Convenience function for creating service with current profile
def get_upload_service(profile_id: str = None) -> UploadService:
    """Get an UploadService for the given or current profile."""
    return UploadService(profile_id)
