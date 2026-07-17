import random
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    event,
    text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
import numpy as np

Base = declarative_base()


class MediaItem(Base):
    __tablename__ = "media_items"

    id = Column(Integer, primary_key=True, index=True)

    # File information
    # A source locator is not Media identity: watched files can change in place,
    # producing multiple immutable Media revisions at the same external path.
    file_path = Column(String, nullable=False, index=True)
    file_hash = Column(String, nullable=False, index=True)
    file_size = Column(Integer, nullable=False)  # bytes
    file_format = Column(String, nullable=False, index=True)  # jpg, png, mp4, etc.
    original_filename = Column(String, nullable=True)

    # Media properties
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    megapixels = Column(Float, nullable=False, index=True)
    duration = Column(Float, nullable=True)  # seconds, for videos/audio

    # Whether the file's format declares an alpha channel (PNG RGBA/tRNS, WebP
    # alpha, etc.) — read from the header only, no pixel decode. NULL = not yet
    # computed (pre-dates this field; backfilled via metadata_status='pending').
    has_alpha = Column(Boolean, nullable=True, index=True)

    # Audio-specific properties
    audio_sample_rate = Column(Integer, nullable=True)  # Hz (e.g., 44100, 48000)
    audio_channels = Column(Integer, nullable=True)  # 1=mono, 2=stereo, etc.
    audio_bit_depth = Column(Integer, nullable=True)  # bits per sample (16, 24, 32)
    audio_bitrate = Column(Integer, nullable=True)  # bits per second
    audio_codec = Column(String, nullable=True)  # codec name (mp3, flac, aac, etc.)

    # Dates
    created_date = Column(DateTime, nullable=True, index=True)
    modified_date = Column(DateTime, nullable=True, index=True)
    indexed_date = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)  # Soft delete timestamp (user-initiated)
    # Durable privacy-deletion barrier. Once set, no new root may acquire this
    # Media even though the worker has not yet removed its bytes and row.
    deletion_pending_at = Column(DateTime, nullable=True, index=True)
    # Legacy inert column. Auto-delete belongs exclusively to Asset.expires_at.
    auto_delete_at = Column(DateTime, nullable=True, index=True)

    # File availability tracking (system-detected missing files)
    file_unavailable = Column(Boolean, default=False, index=True)  # True if file not found on disk
    file_unavailable_since = Column(DateTime, nullable=True)  # When the file was first found missing

    # Chat reference (if generated via chat system)
    chat_item_id = Column(Integer, nullable=True, index=True)  # FK to chat_items.id

    # Ephemeral one-shot-run media: created while running a flow behind the tool
    # abstraction (flow-as-tool). These are NEVER part of the user's library — they
    # are tagged with the run id, excluded from every user-facing query / ingestion /
    # lineage / websocket path, and hard-deleted when the run ends (or swept if the
    # run crashes). NULL = normal, permanent media. See plans/CUSTOM_TOOLS_BUILD.md.
    ephemeral_run_id = Column(String, nullable=True, index=True)

    # Tool/preset provenance - which tool and preset created this media
    tool_id = Column(String, nullable=True, index=True)  # Full tool ID (provider:tool_id) that created this media
    preset_id = Column(Integer, ForeignKey('presets.id', ondelete='SET NULL'), nullable=True, index=True)  # Preset active during generation

    # Physical storage indirection. NULL means legacy path-backed Media until
    # the object-store migration classifies it.
    storage_object_id = Column(Integer, ForeignKey('storage_objects.id', ondelete='RESTRICT'), nullable=True, index=True)

    # Random sort value (stable, set once on creation). The default fires on every
    # ORM insert path (generation, upload, sets/grids, layouts, agent tools, ingestion)
    # so random-sort + re-shuffle works for all media, not just disk-scanned items.
    # NULL here would collapse every such item to an equal sort key, pinning them to
    # id order and making re-randomize a no-op.
    random_sort_value = Column(Float, nullable=True, index=True, default=lambda: random.random())

    # AI/ML processed data
    clip_embedding = Column(LargeBinary, nullable=True)
    vlm_caption = Column(String, nullable=True)
    raw_metadata = Column(String, nullable=True)
    extracted_prompt = Column(String, nullable=True)
    keywords = Column(String, nullable=True)
    generation_metadata = Column(String, nullable=True)  # JSON string for generation params

    # Non-destructive editor project state stored in sidecar file
    has_editor_sidecar = Column(Boolean, nullable=True, default=False)

    # Config version tracking (hash of config used for each phase)
    metadata_config_version = Column(String, nullable=True)
    clip_config_version = Column(String, nullable=True)
    vlm_caption_config_version = Column(String, nullable=True)
    face_detection_config_version = Column(String, nullable=True)

    # Per-phase status (pending/processing/completed/failed)
    metadata_status = Column(String, default='pending', index=True)
    clip_status = Column(String, default='pending', index=True)
    vlm_caption_status = Column(String, default='pending', index=True)
    face_detection_status = Column(String, default='pending', index=True)

    # Per-phase completion timestamps
    metadata_processed_at = Column(DateTime, nullable=True)
    clip_processed_at = Column(DateTime, nullable=True)
    vlm_caption_processed_at = Column(DateTime, nullable=True)
    face_detection_processed_at = Column(DateTime, nullable=True)

    # Per-phase error tracking
    metadata_error = Column(String, nullable=True)
    metadata_retry_count = Column(Integer, default=0)
    clip_error = Column(String, nullable=True)
    clip_retry_count = Column(Integer, default=0)
    vlm_caption_error = Column(String, nullable=True)
    vlm_caption_retry_count = Column(Integer, default=0)
    face_detection_error = Column(String, nullable=True)
    face_detection_retry_count = Column(Integer, default=0)

    # Additional indexes for common queries
    __table_args__ = (
        Index('idx_created_desc', created_date.desc()),
        Index('idx_indexed_desc', indexed_date.desc()),
        {'sqlite_autoincrement': True},  # Prevent ID reuse after deletion
    )

    # Relationships (note: these are not columns, they're for ORM convenience)
    # These will be loaded via explicit joins when needed
    markers = relationship(
        "Marker",
        secondary="media_markers",
        lazy="select",
        viewonly=True
    )

    # Direct access to MediaMarker junction records (for source filtering)
    marker_associations = relationship(
        "MediaMarker",
        lazy="select",
        viewonly=True
    )

    tags = relationship(
        "Tag",
        secondary="media_tags",
        lazy="select",
        viewonly=True
    )

    @property
    def member_count(self) -> Optional[int]:
        """Compute member count for structured media (sets/grids) from raw_metadata."""
        if not self.file_format or not self.raw_metadata:
            return None
        fmt = self.file_format.lower()
        if fmt in ('stimmaset.json', 'stimmagrid.json'):
            try:
                import json
                content = json.loads(self.raw_metadata)
                if fmt == 'stimmaset.json':
                    return len(content.get('items', []))
                elif fmt == 'stimmagrid.json':
                    return len(content.get('cells', []))
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    def set_embedding(self, embedding: np.ndarray):
        """Convert numpy array to bytes for storage."""
        self.clip_embedding = embedding.astype(np.float32).tobytes()

    def get_embedding(self) -> Optional[np.ndarray]:
        """Convert bytes back to numpy array."""
        if self.clip_embedding is None:
            return None
        return np.frombuffer(self.clip_embedding, dtype=np.float32)

    def to_dict(self):
        """Convert to dictionary for API responses."""
        result = {
            "id": self.id,
            "file_hash": self.file_hash,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "file_format": self.file_format,
            "original_filename": self.original_filename,
            "width": self.width,
            "height": self.height,
            "has_alpha": self.has_alpha,
            "megapixels": self.megapixels,
            "duration": self.duration,
            # Audio metadata
            "audio_sample_rate": self.audio_sample_rate,
            "audio_channels": self.audio_channels,
            "audio_bit_depth": self.audio_bit_depth,
            "audio_bitrate": self.audio_bitrate,
            "audio_codec": self.audio_codec,
            "created_date": self.created_date.isoformat() if self.created_date else None,
            "modified_date": self.modified_date.isoformat() if self.modified_date else None,
            "indexed_date": self.indexed_date.isoformat(),
            # Media has no independent auto-delete lifecycle. Keep the column
            # readable for migration only; never expose it as live state.
            "auto_delete_at": None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "chat_item_id": self.chat_item_id,
            "tool_id": self.tool_id,
            "preset_id": self.preset_id,
            "vlm_caption": self.vlm_caption,
            "raw_metadata": self.raw_metadata,
            "extracted_prompt": self.extracted_prompt,
            "keywords": self.keywords.split(",") if self.keywords else [],
            "generation_metadata": self.generation_metadata,
            "has_editor_sidecar": self.has_editor_sidecar or False,
            "has_clip_embedding": self.clip_embedding is not None,
            "has_vlm_caption": self.vlm_caption is not None,
            "vlm_error": self.vlm_caption_error,
            # Processing statuses
            "metadata_status": self.metadata_status,
            "clip_status": self.clip_status,
            "face_detection_status": self.face_detection_status,
            "vlm_caption_status": self.vlm_caption_status,
        }

        # Include markers if relationship is loaded
        # Use marker_associations to filter out suppressed markers and include source
        if hasattr(self, '_sa_instance_state') and 'marker_associations' in self._sa_instance_state.dict:
            result["markers"] = [
                {**assoc.marker.to_dict(), "source": assoc.source}
                for assoc in self.marker_associations
                if assoc.source != 'suppressed' and assoc.marker is not None
            ]
        elif hasattr(self, '_sa_instance_state') and 'markers' in self._sa_instance_state.dict:
            # Fallback for legacy queries that use markers relationship
            result["markers"] = [marker.to_dict() for marker in self.markers]
        else:
            result["markers"] = []

        # Include tags if relationship is loaded
        if hasattr(self, '_sa_instance_state') and 'tags' in self._sa_instance_state.dict:
            result["tags"] = [tag.to_dict() for tag in self.tags]
        else:
            result["tags"] = []

        # Add member_count and title for structured media (sets/grids)
        if self.file_format:
            fmt = self.file_format.lower()
            if fmt in ('stimmaset.json', 'stimmagrid.json'):
                import json
                content = None
                # Try raw_metadata first
                if self.raw_metadata:
                    try:
                        content = json.loads(self.raw_metadata)
                    except (json.JSONDecodeError, TypeError):
                        pass
                # Fall back to reading from file if raw_metadata is empty
                if not content and self.file_path:
                    try:
                        with open(self.file_path, 'r', encoding='utf-8') as f:
                            content = json.load(f)
                    except Exception:
                        pass
                if content:
                    if fmt == 'stimmaset.json':
                        result["member_count"] = len(content.get('items', []))
                        if content.get('title'):
                            result["title"] = content.get('title')
                    elif fmt == 'stimmagrid.json':
                        result["member_count"] = len(content.get('cells', []))
                        if content.get('title'):
                            result["title"] = content.get('title')

        return result


class Asset(Base):
    """Stable user-facing identity whose saved states are AssetRevisions."""
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    asset_type = Column(String, nullable=False, index=True)
    title = Column(String, nullable=True)
    # Deliberately service-validated instead of a circular FK to asset_revisions.
    current_revision_id = Column(Integer, nullable=True, index=True)
    state = Column(String, nullable=False, default="active", index=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    origin_type = Column(String, nullable=True, index=True)
    origin_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)
    __table_args__ = (
        CheckConstraint("state IN ('active', 'trashed', 'deleting')", name="ck_assets_state"),
        {'sqlite_autoincrement': True},
    )

    def to_dict(self):
        return {
            "id": self.id,
            "asset_type": self.asset_type,
            "title": self.title,
            "current_revision_id": self.current_revision_id,
            "state": self.state,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "origin_type": self.origin_type,
            "origin_id": self.origin_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class AssetRevision(Base):
    """Immutable saved state of an Asset."""
    __tablename__ = "asset_revisions"

    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey('assets.id', ondelete='CASCADE'), nullable=False, index=True)
    parent_revision_id = Column(Integer, ForeignKey('asset_revisions.id', ondelete='SET NULL'), nullable=True, index=True)
    primary_media_id = Column(Integer, ForeignKey('media_items.id', ondelete='RESTRICT'), nullable=False, index=True)
    revision_number = Column(Integer, nullable=False)
    note = Column(String, nullable=True)
    missing_parent = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index('idx_asset_revisions_asset_number', 'asset_id', 'revision_number', unique=True),
        Index('idx_asset_revisions_primary_media', 'primary_media_id', unique=True),
        {'sqlite_autoincrement': True},
    )

    def to_dict(self):
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "parent_revision_id": self.parent_revision_id,
            "primary_media_id": self.primary_media_id,
            "revision_number": self.revision_number,
            "note": self.note,
            "missing_parent": self.missing_parent,
            "created_at": self.created_at.isoformat(),
        }


class StorageObject(Base):
    """Physical managed bytes or a verified external source locator."""
    __tablename__ = "storage_objects"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, nullable=False, index=True)  # managed | external
    object_key = Column(String, nullable=True, unique=True)
    external_path = Column(String, nullable=True)
    expected_hash = Column(String, nullable=False, index=True)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)
    state = Column(String, nullable=False, default="available", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    verified_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        CheckConstraint("kind IN ('managed', 'external')", name="ck_storage_objects_kind"),
        CheckConstraint("state IN ('available', 'missing', 'deleting')", name="ck_storage_objects_state"),
        CheckConstraint(
            "(kind = 'managed' AND object_key IS NOT NULL AND external_path IS NULL) OR "
            "(kind = 'external' AND external_path IS NOT NULL AND object_key IS NULL)",
            name="ck_storage_objects_locator",
        ),
        {'sqlite_autoincrement': True},
    )


class MediaOwner(Base):
    """Typed strong-retention edge from a live root to Media."""
    __tablename__ = "media_owners"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(Integer, ForeignKey('media_items.id', ondelete='CASCADE'), nullable=False, index=True)
    root_kind = Column(String, nullable=False, index=True)
    root_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)
    idempotency_key = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index('idx_media_owners_root', 'root_kind', 'root_id', 'deleted_at'),
        Index('idx_media_owners_media_live', 'media_id', 'deleted_at'),
        Index(
            'idx_media_owners_live_edge',
            'media_id', 'root_kind', 'root_id', 'role',
            unique=True,
            sqlite_where=text('deleted_at IS NULL'),
        ),
        {'sqlite_autoincrement': True},
    )


class WorkingDocument(Base):
    """Mutable autosaved editor state for an Asset branch."""
    __tablename__ = "working_documents"

    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey('assets.id', ondelete='CASCADE'), nullable=False, index=True)
    editor_type = Column(String, nullable=False, index=True)
    branch_key = Column(String, nullable=False, default="main")
    base_revision_id = Column(Integer, ForeignKey('asset_revisions.id', ondelete='SET NULL'), nullable=True, index=True)
    state_locator = Column(String, nullable=True)
    generation = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index('idx_working_documents_asset_branch', 'asset_id', 'editor_type', 'branch_key'),
        {'sqlite_autoincrement': True},
    )


class AssetSnapshot(Base):
    """Exact Media snapshot plus weak semantic binding to a source Asset."""
    __tablename__ = "asset_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    owner_kind = Column(String, nullable=False, index=True)  # revision | working_document
    owner_id = Column(String, nullable=False, index=True)
    media_id = Column(Integer, ForeignKey('media_items.id', ondelete='RESTRICT'), nullable=False, index=True)
    source_asset_id = Column(Integer, ForeignKey('assets.id', ondelete='SET NULL'), nullable=True, index=True)
    source_revision_id = Column(Integer, ForeignKey('asset_revisions.id', ondelete='SET NULL'), nullable=True, index=True)
    role = Column(String, nullable=False)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        CheckConstraint("owner_kind IN ('revision', 'working_document')", name="ck_asset_snapshots_owner_kind"),
        Index('idx_asset_snapshots_owner', 'owner_kind', 'owner_id', 'deleted_at'),
        {'sqlite_autoincrement': True},
    )


class ContainerMember(Base):
    """One live-Asset link or exact direct-Media member in a container Revision."""
    __tablename__ = "container_members"

    id = Column(Integer, primary_key=True, index=True)
    container_revision_id = Column(Integer, ForeignKey('asset_revisions.id', ondelete='CASCADE'), nullable=False, index=True)
    linked_asset_id = Column(Integer, ForeignKey('assets.id', ondelete='RESTRICT'), nullable=True, index=True)
    embedded_media_id = Column(Integer, ForeignKey('media_items.id', ondelete='RESTRICT'), nullable=True, index=True)
    # Privacy deletion can erase the linked Asset identity while preserving the
    # container's structural slot as an unavailable placeholder.
    missing_linked_asset = Column(Boolean, nullable=False, default=False)
    member_order = Column(Integer, nullable=False, default=0)
    row_index = Column(Integer, nullable=True)
    column_index = Column(Integer, nullable=True)
    caption = Column(String, nullable=True)
    title = Column(String, nullable=True)
    member_metadata = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        CheckConstraint(
            "(linked_asset_id IS NOT NULL AND embedded_media_id IS NULL AND missing_linked_asset = 0) OR "
            "(linked_asset_id IS NULL AND embedded_media_id IS NOT NULL AND missing_linked_asset = 0) OR "
            "(linked_asset_id IS NULL AND embedded_media_id IS NULL AND missing_linked_asset = 1)",
            name="ck_container_members_target",
        ),
        Index('idx_container_members_revision_order', 'container_revision_id', 'member_order'),
        {'sqlite_autoincrement': True},
    )


class AssetMigrationMap(Base):
    """Recoverable explanation of how one legacy MediaItem was classified."""
    __tablename__ = "asset_migration_map"

    id = Column(Integer, primary_key=True, index=True)
    legacy_media_id = Column(Integer, nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey('assets.id', ondelete='SET NULL'), nullable=True, index=True)
    classification = Column(String, nullable=False, index=True)
    reason = Column(Text, nullable=False)
    evidence = Column(Text, nullable=True)
    migration_version = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="classified", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index('idx_asset_migration_media_version', 'legacy_media_id', 'migration_version'),
        {'sqlite_autoincrement': True},
    )


class AssetMigrationState(Base):
    """Single profile-local gate for expand/shadow/cutover/contract rollout."""
    __tablename__ = "asset_migration_state"

    id = Column(Integer, primary_key=True, index=True)
    migration_key = Column(String, nullable=False, unique=True)
    phase = Column(String, nullable=False, default="expanded", index=True)
    migration_version = Column(Integer, nullable=False, default=1)
    report_digest = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        CheckConstraint(
            "phase IN ('expanded', 'shadow', 'dual_write', 'asset_reads', 'object_store', 'contracted')",
            name="ck_asset_migration_state_phase",
        ),
        {'sqlite_autoincrement': True},
    )


class ManagedArtifact(Base):
    """Indexed implementation resource that must participate in deletion."""
    __tablename__ = "managed_artifacts"

    id = Column(Integer, primary_key=True, index=True)
    owner_kind = Column(String, nullable=False, index=True)
    owner_id = Column(String, nullable=False, index=True)
    media_id = Column(Integer, ForeignKey('media_items.id', ondelete='CASCADE'), nullable=True, index=True)
    artifact_kind = Column(String, nullable=False, index=True)
    locator = Column(String, nullable=False)
    state = Column(String, nullable=False, default="available", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        CheckConstraint("state IN ('available', 'deleting', 'missing')", name="ck_managed_artifacts_state"),
        Index('idx_managed_artifacts_owner', 'owner_kind', 'owner_id', 'deleted_at'),
        {'sqlite_autoincrement': True},
    )


class AssetMarker(Base):
    """Asset-level marker assignment; replaces MediaMarker after cutover."""
    __tablename__ = "asset_markers"

    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey('assets.id', ondelete='CASCADE'), nullable=False, index=True)
    marker_id = Column(Integer, ForeignKey('markers.id', ondelete='CASCADE'), nullable=False, index=True)
    source = Column(String, nullable=False, default='manual')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index(
            'idx_asset_markers_live', 'asset_id', 'marker_id',
            unique=True, sqlite_where=text('deleted_at IS NULL'),
        ),
        {'sqlite_autoincrement': True},
    )


class AssetTag(Base):
    """Asset-level tag assignment; replaces MediaTag after cutover."""
    __tablename__ = "asset_tags"

    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey('assets.id', ondelete='CASCADE'), nullable=False, index=True)
    tag_id = Column(Integer, ForeignKey('tags.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index(
            'idx_asset_tags_live', 'asset_id', 'tag_id',
            unique=True, sqlite_where=text('deleted_at IS NULL'),
        ),
        {'sqlite_autoincrement': True},
    )


class ProjectAsset(Base):
    """Many-to-many organizational membership for Assets and Projects."""
    __tablename__ = "project_assets"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey('assets.id', ondelete='CASCADE'), nullable=False, index=True)
    added_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index(
            'idx_project_assets_live', 'project_id', 'asset_id',
            unique=True, sqlite_where=text('deleted_at IS NULL'),
        ),
        {'sqlite_autoincrement': True},
    )


class BoardAssetItem(Base):
    """Ordered Asset membership in a board section."""
    __tablename__ = "board_asset_items"

    id = Column(Integer, primary_key=True, index=True)
    board_section_id = Column(Integer, ForeignKey('board_sections.id', ondelete='CASCADE'), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey('assets.id', ondelete='CASCADE'), nullable=False, index=True)
    display_order = Column(Integer, nullable=False, default=0)
    added_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index('idx_board_asset_items_order', 'board_section_id', 'display_order'),
        Index(
            'idx_board_asset_items_live', 'board_section_id', 'asset_id',
            unique=True, sqlite_where=text('deleted_at IS NULL'),
        ),
        {'sqlite_autoincrement': True},
    )


class Face(Base):
    """Face detection results table."""
    __tablename__ = "faces"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(Integer, ForeignKey('media_items.id', ondelete='CASCADE'), nullable=False, index=True)

    # Bounding box (normalized coordinates 0-1)
    bbox_x = Column(Float, nullable=False)
    bbox_y = Column(Float, nullable=False)
    bbox_width = Column(Float, nullable=False)
    bbox_height = Column(Float, nullable=False)

    # Detection confidence
    confidence = Column(Float, nullable=False, index=True)

    # Auraface embedding vector (stored as bytes)
    auraface_embedding = Column(LargeBinary, nullable=True)

    # Facial landmarks (JSON string)
    landmarks = Column(String, nullable=True)

    # Timestamp
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def set_embedding(self, embedding: np.ndarray):
        """Convert numpy array to bytes for storage."""
        self.auraface_embedding = embedding.astype(np.float32).tobytes()

    def get_embedding(self) -> Optional[np.ndarray]:
        """Convert bytes back to numpy array."""
        if self.auraface_embedding is None:
            return None
        return np.frombuffer(self.auraface_embedding, dtype=np.float32)

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "media_id": self.media_id,
            "bbox": {
                "x": self.bbox_x,
                "y": self.bbox_y,
                "width": self.bbox_width,
                "height": self.bbox_height,
            },
            "confidence": self.confidence,
            "landmarks": self.landmarks,
            "has_embedding": self.auraface_embedding is not None,
            "created_at": self.created_at.isoformat(),
        }


class Keyword(Base):
    """Normalized keyword table for fast lookups."""
    __tablename__ = "keywords"

    id = Column(Integer, primary_key=True, index=True)
    keyword_text = Column(String, unique=True, nullable=False, index=True)

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "keyword": self.keyword_text,
        }


class MediaKeyword(Base):
    """Junction table for media items and keywords (many-to-many)."""
    __tablename__ = "media_keywords"

    media_id = Column(Integer, nullable=False, primary_key=True)
    keyword_id = Column(Integer, nullable=False, primary_key=True)

    # Composite indexes for fast lookups in both directions
    __table_args__ = (
        Index('idx_keyword_media', keyword_id, media_id),
        Index('idx_media_keyword', media_id, keyword_id),
    )


class ControlFlag(Base):
    """Simple key-value table for inter-process communication flags."""
    __tablename__ = "control_flags"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class DatabaseMeta(Base):
    """Metadata table for storing database-level configuration like unique identifiers."""
    __tablename__ = "_meta"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)


class GenerationJob(Base):
    """Table for tracking image generation jobs."""
    __tablename__ = "generation_jobs"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, nullable=False, index=True)  # queued, assigned, processing, completed, failed
    task_type = Column(String, nullable=False, default="text-to-image", index=True)  # text-to-image, image-to-image, etc.
    generator_type = Column(String, nullable=False)  # comfyui, runware, etc.
    generator_name = Column(String, nullable=False)  # Name from config (DEPRECATED - use backend_name)
    model_name = Column(String, nullable=False)  # Model being used
    parameters = Column(String, nullable=False)  # JSON string of generation parameters
    # Private staging path. The name is retained for database compatibility.
    folder_path = Column(String, nullable=False)

    # Generator tracking (new architecture)
    generator_instance_id = Column(String, nullable=True, index=True)  # Which generator owns this job (UUID for clients, ID for server-side)
    backend_name = Column(String, nullable=True, index=True)  # Which backend to execute on (e.g., "comfyui-1")
    worker_id = Column(String, nullable=True)  # Which worker is processing this job

    # Tool provenance
    tool_id = Column(String, nullable=True, index=True)  # Full tool ID (provider:tool_id) that created this generation
    preset_id = Column(Integer, ForeignKey('presets.id', ondelete='SET NULL'), nullable=True, index=True)  # Preset active during generation
    project_id = Column(Integer, nullable=True, index=True)  # Project to associate generated media with

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    assigned_at = Column(DateTime, nullable=True)  # When job was assigned to a generator
    started_at = Column(DateTime, nullable=True)  # When generation actually started
    completed_at = Column(DateTime, nullable=True)  # When generation finished

    # Auto-delete settings. Duration remains the generation preference; the
    # resulting deadline lives on Asset.expires_at.
    auto_delete_duration = Column(String, nullable=True)  # e.g., "24h", "3d", "never"
    auto_delete_at = Column(DateTime, nullable=True, index=True)  # Legacy inert column

    # Results
    result_media_id = Column(Integer, nullable=True)  # FK to media_items
    error = Column(String, nullable=True)  # Error message if failed

    # Batch processing
    batch_id = Column(String, nullable=True, index=True)  # Groups related jobs in a batch
    batch_total = Column(Integer, nullable=True)  # Total jobs in batch (stored on first job only)
    batch_output_set_id = Column(Integer, nullable=True)  # Result set media ID (stored on first job only)

    # Invocation-specific Asset disposition. This is explicit because the same
    # STP tool produces an Asset in Tool View but provisional Media in a chat.
    output_disposition = Column(String, nullable=False, default='asset', index=True)
    output_context_kind = Column(String, nullable=True, index=True)
    output_context_id = Column(String, nullable=True, index=True)
    result_asset_id = Column(Integer, ForeignKey('assets.id', ondelete='SET NULL'), nullable=True, index=True)

    __table_args__ = {'sqlite_autoincrement': True}  # Prevent ID reuse after deletion

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "status": self.status,
            "task_type": self.task_type,
            "generator_type": self.generator_type,
            "generator_name": self.generator_name,
            "model_name": self.model_name,
            "parameters": self.parameters,
            "folder_path": self.folder_path,
            "generator_instance_id": self.generator_instance_id,
            "backend_name": self.backend_name,
            "worker_id": self.worker_id,
            "tool_id": self.tool_id,
            "preset_id": self.preset_id,
            "project_id": self.project_id,
            "created_at": self.created_at.isoformat(),
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "auto_delete_duration": self.auto_delete_duration,
            "auto_delete_at": None,
            "result_media_id": self.result_media_id,
            "error": self.error,
            "batch_id": self.batch_id,
            "batch_total": self.batch_total,
            "batch_output_set_id": self.batch_output_set_id,
            "output_disposition": self.output_disposition,
            "output_context_kind": self.output_context_kind,
            "output_context_id": self.output_context_id,
            "result_asset_id": self.result_asset_id,
        }


class UserPreference(Base):
    """Table for storing user preferences."""
    __tablename__ = "user_preferences"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)  # JSON string
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TaskDefaults(Base):
    """Table for storing user default parameters per task type."""
    __tablename__ = "task_defaults"

    id = Column(Integer, primary_key=True, index=True)
    task_type = Column(String, nullable=False, index=True)  # e.g., "text-to-image", "image-to-image"
    scope = Column(String, nullable=False, default="global")  # "global" or scope identifier (e.g., "chat-xyz")
    parameters = Column(String, nullable=False)  # JSON string of default parameters
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Unique constraint on task_type + scope
    __table_args__ = (
        Index('idx_task_defaults_task_scope', task_type, scope, unique=True),
    )


class Marker(Base):
    """Table for image markers (favorite, collect, etc.)."""
    __tablename__ = "markers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    icon_svg = Column(String, nullable=False)  # SVG markup
    color = Column(String, nullable=False)  # Hex color code
    config_id = Column(String, nullable=True, index=True)  # Stable ID from config for safe renaming
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = {'sqlite_autoincrement': True}  # Prevent ID reuse after deletion

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "icon_svg": self.icon_svg,
            "color": self.color,
            "config_id": self.config_id,
            "created_at": self.created_at.isoformat(),
        }


class MediaMarker(Base):
    """Junction table for media items and markers (many-to-many)."""
    __tablename__ = "media_markers"

    media_id = Column(Integer, ForeignKey('media_items.id'), primary_key=True, nullable=False)
    marker_id = Column(Integer, ForeignKey('markers.id'), primary_key=True, nullable=False)
    # source: 'auto' (from folder config), 'manual' (user added), 'suppressed' (user removed auto)
    source = Column(String, nullable=False, default='manual')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationship to get the Marker object
    marker = relationship("Marker", lazy="joined")

    # Composite indexes for fast lookups in both directions
    __table_args__ = (
        Index('idx_marker_media', marker_id, media_id),
        Index('idx_media_marker', media_id, marker_id),
        # Covering index for marker filter queries that also check source != 'suppressed'
        Index('idx_marker_media_source', marker_id, media_id, source),
    )


class Tag(Base):
    """Table for user-defined tags (separate from AI-generated keywords)."""
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    tag_text = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = {'sqlite_autoincrement': True}  # Prevent ID reuse after deletion

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "tag": self.tag_text,
            "created_at": self.created_at.isoformat(),
        }


class MediaTag(Base):
    """Junction table for media items and tags (many-to-many)."""
    __tablename__ = "media_tags"

    media_id = Column(Integer, ForeignKey('media_items.id'), nullable=False, primary_key=True)
    tag_id = Column(Integer, ForeignKey('tags.id'), nullable=False, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Composite indexes for fast lookups in both directions
    __table_args__ = (
        Index('idx_tag_media', tag_id, media_id),
        Index('idx_media_tag', media_id, tag_id),
    )


class Project(Base):
    """Scoped working world for assets, chats, boards, and agent state."""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    root_path = Column(String, nullable=True)
    additional_instructions = Column(Text, nullable=True)
    memory = Column(Text, nullable=True)
    agent_tool_config = Column(String, nullable=True)
    default_model_slug = Column(String, nullable=True)  # Default LLM model for chats in this project
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = {'sqlite_autoincrement': True}

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "name": self.name,
            "root_path": self.root_path,
            "additional_instructions": self.additional_instructions,
            "memory": self.memory,
            "agent_tool_config": json.loads(self.agent_tool_config) if self.agent_tool_config else None,
            "default_model_slug": self.default_model_slug,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class ProjectMedia(Base):
    """Project membership edge for library media."""
    __tablename__ = "project_media"

    project_id = Column(Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, primary_key=True)
    media_id = Column(Integer, ForeignKey('media_items.id', ondelete='CASCADE'), nullable=False, primary_key=True)
    added_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_project_media_media', media_id),
        Index('idx_project_media_project_added', project_id, added_at),
    )


class Flow(Base):
    """A flow: a repeatable parameterized process for producing assets.

    Heavy state (equations, tasks, HITL results) lives in a per-flow SQLite
    database at <data_dir>/flows/<id>/state.db. This table stores metadata only.
    """
    __tablename__ = "flows"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    parent_id = Column(Integer, ForeignKey('flows.id', ondelete='SET NULL'), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='SET NULL'), nullable=True, index=True)

    # JSON text
    input_schema = Column(Text, nullable=True)   # typed input definition
    output_schema = Column(Text, nullable=True)  # typed output definition
    inputs = Column(Text, nullable=True)         # current input values

    program_hash = Column(String, nullable=True)
    execution_state = Column(String, nullable=False, default='idle', index=True)  # idle | running | paused

    # Denormalized count of pending tasks across the per-flow state.db.
    # Maintained incrementally via WebSocket events and reconciled on startup.
    pending_task_count = Column(Integer, nullable=False, default=0, server_default='0')

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = {'sqlite_autoincrement': True}

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parent_id": self.parent_id,
            "project_id": self.project_id,
            "input_schema": json.loads(self.input_schema) if self.input_schema else None,
            "output_schema": json.loads(self.output_schema) if self.output_schema else None,
            "inputs": json.loads(self.inputs) if self.inputs else None,
            "program_hash": self.program_hash,
            "execution_state": self.execution_state,
            "pending_task_count": self.pending_task_count or 0,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class UserTool(Base):
    """A flow frozen into a first-class tool (atom).

    A frozen flow *is* a tool: ``program_text`` is the self-contained runnable
    body (a snapshot of the flow's program, so the tool runs even if the source
    flow is later deleted), and ``flow_id`` is the editing handle back to that
    source. The interface is canonical STP (``parameter_schema`` /
    ``output_schema`` / ``task_types``); the freeze settings (``hitl_policies``,
    ``output_map``) record how the flow was made unattended-runnable.

    Registered into the tool namespace by ``UserToolsProvider`` and executed via
    ``flow_runtime.oneshot.run_flow_once``. See plans/FLOW_TO_TOOL.md §2/§7.
    """
    __tablename__ = "user_tools"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    # Stable URL slug, frozen at creation. The tool id (slug-id) is used for
    # routing / pins / presets, so it must NOT change when the tool is renamed.
    slug = Column(String, nullable=True)
    description = Column(Text, nullable=True)

    # Editing handle: the source flow (may be deleted — the tool still runs).
    flow_id = Column(Integer, ForeignKey('flows.id', ondelete='SET NULL'), nullable=True, index=True)
    # Runnable body: a snapshot of the flow's program at freeze time.
    program_text = Column(Text, nullable=False)

    # Canonical STP interface (JSON text).
    task_types = Column(Text, nullable=True)         # JSON: ["image-to-image", ...]
    parameter_schema = Column(Text, nullable=True)   # JSON: STP parameter_schema
    output_schema = Column(Text, nullable=True)      # JSON: STP output_schema (assets/detections)

    # Freeze settings (JSON text).
    hitl_policies = Column(Text, nullable=True)       # JSON: {equation_key: {"policy": "first"|...}}
    output_map = Column(Text, nullable=True)          # JSON: {task_output: flow_output_name}

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = {'sqlite_autoincrement': True}

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "flow_id": self.flow_id,
            "task_types": json.loads(self.task_types) if self.task_types else [],
            "parameter_schema": json.loads(self.parameter_schema) if self.parameter_schema else {},
            "output_schema": json.loads(self.output_schema) if self.output_schema else {},
            "hitl_policies": json.loads(self.hitl_policies) if self.hitl_policies else {},
            "output_map": json.loads(self.output_map) if self.output_map else {},
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class Board(Base):
    """Curated board containing ordered sections of assets."""
    __tablename__ = "boards"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = {'sqlite_autoincrement': True}

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "project_id": self.project_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class BoardSection(Base):
    """Ordered section within a board."""
    __tablename__ = "board_sections"

    id = Column(Integer, primary_key=True, index=True)
    board_id = Column(Integer, ForeignKey('boards.id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False, index=True)
    is_collapsed = Column(Boolean, nullable=False, default=False)
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index('idx_board_sections_board_order', board_id, display_order),
        {'sqlite_autoincrement': True},
    )

    def to_dict(self):
        return {
            "id": self.id,
            "board_id": self.board_id,
            "name": self.name,
            "is_default": self.is_default,
            "is_collapsed": self.is_collapsed,
            "display_order": self.display_order,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class BoardItem(Base):
    """Ordered media membership within a board section."""
    __tablename__ = "board_items"

    board_section_id = Column(Integer, ForeignKey('board_sections.id', ondelete='CASCADE'), nullable=False, primary_key=True)
    media_id = Column(Integer, ForeignKey('media_items.id', ondelete='CASCADE'), nullable=False, primary_key=True)
    display_order = Column(Integer, nullable=False, default=0)
    added_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_board_items_section_order', board_section_id, display_order),
        Index('idx_board_items_media', media_id),
    )


class MediaLineage(Base):
    """Tracks generation lineage - which images were used to create which outputs."""
    __tablename__ = "media_lineage"

    id = Column(Integer, primary_key=True, index=True)

    # Output (child) - always exists
    media_id = Column(Integer, ForeignKey('media_items.id', ondelete='CASCADE'), nullable=False, index=True)

    # Source - either internal ID or external path
    source_media_id = Column(Integer, ForeignKey('media_items.id', ondelete='SET NULL'), nullable=True, index=True)
    source_file_path = Column(String, nullable=True)  # For external/imported files

    # Ordering for multi-input tasks (image-to-image can have multiple inputs)
    source_order = Column(Integer, nullable=False, default=0)

    # Metadata
    task_type = Column(String, nullable=False)
    relationship_type = Column(String, nullable=False, server_default='derived')  # 'derived' | 'inspired'
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    media_item = relationship("MediaItem", foreign_keys=[media_id])
    source_media = relationship("MediaItem", foreign_keys=[source_media_id])

    __table_args__ = (
        Index('idx_lineage_media_source', media_id, source_order, unique=True),
    )

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "media_id": self.media_id,
            "source_media_id": self.source_media_id,
            "source_file_path": self.source_file_path,
            "source_order": self.source_order,
            "task_type": self.task_type,
            "created_at": self.created_at.isoformat(),
        }


class MediaToolLineage(Base):
    """Denormalized junction table tracking all tools in a media item's lineage chain.

    For each media item, stores every full_tool_id from its entire ancestor chain
    (including its own tool). This enables efficient JOIN-based filtering by tool
    without expensive recursive queries at browse time.
    """
    __tablename__ = "media_tool_lineage"

    media_id = Column(Integer, ForeignKey('media_items.id', ondelete='CASCADE'), primary_key=True)
    full_tool_id = Column(String, primary_key=True)

    __table_args__ = (
        Index('idx_tool_lineage_tool', full_tool_id),
    )


class DeleteOperation(Base):
    """Durable background operation for permanent delete workflows."""
    __tablename__ = "delete_operations"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, nullable=False)  # single | batch | empty_trash
    profile_id = Column(String, nullable=False, index=True)
    # Operations enqueued by one user action share a group_id so progress can
    # be reported for the whole wave rather than per single-asset operation.
    group_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default='queued', index=True)  # queued | running | completed | failed | superseded
    current_phase = Column(String, nullable=True)
    total_items = Column(Integer, nullable=False, default=0)
    claimed_items = Column(Integer, nullable=False, default=0)
    processed_items = Column(Integer, nullable=False, default=0)
    deleted_items = Column(Integer, nullable=False, default=0)
    failed_items = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    __table_args__ = {'sqlite_autoincrement': True}

    def to_dict(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "profile_id": self.profile_id,
            "group_id": self.group_id,
            "status": self.status,
            "current_phase": self.current_phase,
            "total_items": self.total_items,
            "claimed_items": self.claimed_items,
            "processed_items": self.processed_items,
            "deleted_items": self.deleted_items,
            "failed_items": self.failed_items,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "last_error": self.last_error,
        }


class DeleteOperationItem(Base):
    """Per-media work item for a durable delete operation."""
    __tablename__ = "delete_operation_items"

    operation_id = Column(Integer, ForeignKey('delete_operations.id', ondelete='CASCADE'), nullable=False, primary_key=True)
    media_id = Column(Integer, nullable=False, primary_key=True, index=True)
    file_path = Column(String, nullable=True)
    file_hash = Column(String, nullable=True)
    storage_object_id = Column(Integer, nullable=True)
    storage_object_key = Column(String, nullable=True)
    storage_kind = Column(String, nullable=True)
    thumbnail_paths = Column(Text, nullable=True)
    state = Column(String, nullable=False, default='pending', index=True)
    lease_expires_at = Column(DateTime, nullable=True, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_delete_operation_items_state', operation_id, state, lease_expires_at),
    )


class MediaThumbnailCache(Base):
    """Exact thumbnail cache index so deletes can purge cached previews."""
    __tablename__ = "media_thumbnail_cache"

    media_id = Column(Integer, ForeignKey('media_items.id', ondelete='CASCADE'), nullable=False, primary_key=True)
    cache_path = Column(String, nullable=False, primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_media_thumbnail_cache_media', media_id),
    )


class Chat(Base):
    """Table for agent chat sessions."""
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # "Untitled", "Untitled 2", etc.
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)  # Soft delete

    # Forking support
    original_chatitem_id = Column(Integer, nullable=True)  # FK to chat_items.id
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='SET NULL'), nullable=True, index=True)
    flow_id = Column(Integer, ForeignKey('flows.id', ondelete='SET NULL'), nullable=True, index=True)

    # Per-chat settings
    throttle = Column(String, nullable=True, default='off')

    # Generation settings - flexible JSON bag
    # Example: {
    #   "generator": "comfyui_local",
    #   "model": "flux-dev",
    #   "parameters": {
    #     "width": 1024,
    #     "height": 1024,
    #     "cfg": 7.0,
    #     "steps": 20,
    #     "sampler": "euler",
    #     "scheduler": "simple",
    #     "negative_prompt": "",
    #     ...
    #   },
    #   "locked": ["cfg", "steps", "width", "height"],  # List of locked parameter names
    #   "loras": [{"lora": "name", "weight": 1.0, "min": 0.5, "max": 1.5}, ...]
    # }
    generation_settings = Column(String, nullable=True)

    # Agent settings (per-chat override)
    additional_instructions = Column(Text, nullable=True)  # Custom instructions for this chat
    # JSON: {allowed_tools: [], denied_tools: [], v2_permissions: {}}
    agent_tool_config = Column(String, nullable=True)
    model_slug = Column(String, nullable=True)  # LLM model override (NULL = inherit from project/global default)

    __table_args__ = {'sqlite_autoincrement': True}  # Prevent ID reuse after deletion

    def to_dict(self):
        """Convert to dictionary for API responses."""
        import json
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "original_chatitem_id": self.original_chatitem_id,
            "project_id": self.project_id,
            "flow_id": self.flow_id,
            "throttle": self.throttle,
            "generation_settings": json.loads(self.generation_settings) if self.generation_settings else None,
            "additional_instructions": self.additional_instructions,
            "agent_tool_config": json.loads(self.agent_tool_config) if self.agent_tool_config else None,
            "model_slug": self.model_slug,
        }


class ChatItem(Base):
    """Table for individual items in a chat (messages, tool calls, generated media, etc.)."""
    __tablename__ = "chat_items"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey('chats.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Item type: user_message, assistant_message, assistant_message_chunk,
    #           tool_call, tool_result, generated_media, media_grid, error, system
    item_type = Column(String, nullable=False, index=True)

    # Message fields
    message_text = Column(String, nullable=True)

    # Tool call fields
    tool_name = Column(String, nullable=True)
    tool_call_id = Column(String, nullable=True, index=True)
    tool_args = Column(String, nullable=True)  # JSON

    # Tool result fields
    tool_result = Column(String, nullable=True)  # JSON
    tool_error = Column(String, nullable=True)

    # Media fields
    media_id = Column(Integer, ForeignKey('media_items.id', ondelete='SET NULL'), nullable=True, index=True)
    media_ids = Column(String, nullable=True)  # JSON array
    asset_id = Column(Integer, ForeignKey('assets.id', ondelete='SET NULL'), nullable=True, index=True)
    asset_ids = Column(String, nullable=True)  # JSON array; weak organizational references
    show_role = Column(String, nullable=True, index=True)  # intermediate | final
    grid_layout = Column(String, nullable=True)  # JSON

    # Threading
    parent_item_id = Column(Integer, ForeignKey('chat_items.id', ondelete='SET NULL'), nullable=True)

    # Extensibility
    item_metadata = Column(String, nullable=True)  # JSON (renamed from 'metadata' to avoid SQLAlchemy conflict)

    # Indexes
    __table_args__ = (
        Index('idx_chat_items_chat_created', chat_id, created_at),
        {'sqlite_autoincrement': True},  # Prevent ID reuse after deletion
    )

    def _parse_tool_result(self):
        """Parse tool_result, handling both JSON and plain text gracefully."""
        import json
        if not self.tool_result:
            return None
        try:
            return json.loads(self.tool_result)
        except json.JSONDecodeError:
            # Tool result is plain text (e.g., error message from older format)
            return {"text": self.tool_result}

    def _parse_json_field(self, field_name, fallback=None):
        """Parse a JSON text column without letting legacy bad rows break reads."""
        import json
        raw_value = getattr(self, field_name)
        if not raw_value:
            return fallback
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            try:
                value, _ = json.JSONDecoder().raw_decode(raw_value)
                return value
            except json.JSONDecodeError:
                return fallback

    def to_dict(self):
        """Convert to dictionary for API responses."""
        result = {
            "id": self.id,
            "chat_id": self.chat_id,
            "created_at": self.created_at.isoformat(),
            "item_type": self.item_type,
            "message_text": self.message_text,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "tool_args": self._parse_json_field("tool_args"),
            "tool_result": self._parse_tool_result(),
            "tool_error": self.tool_error,
            "media_id": self.media_id,
            "asset_id": self.asset_id,
            "asset_ids": self._parse_json_field("asset_ids", []),
            "show_role": self.show_role,
            "media_ids": self._parse_json_field("media_ids"),
            "grid_layout": self._parse_json_field("grid_layout"),
            "parent_item_id": self.parent_item_id,
            "item_metadata": self._parse_json_field("item_metadata"),
        }
        return result


class SavedView(Base):
    """Table for saved browser views (filter + sort presets)."""
    __tablename__ = "saved_views"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    filters = Column(String, nullable=False)  # JSON string of filter criteria
    sort_by = Column(String, nullable=False, default='created_desc')
    display_order = Column(Integer, nullable=False, default=0)  # For manual ordering
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = {'sqlite_autoincrement': True}  # Prevent ID reuse after deletion

    def to_dict(self):
        """Convert to dictionary for API responses."""
        import json
        return {
            "id": self.id,
            "name": self.name,
            "filters": json.loads(self.filters) if self.filters else {},
            "sort_by": self.sort_by,
            "display_order": self.display_order,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# Task type to category mapping for tools
TASK_TYPE_TO_CATEGORY = {
    'text-to-image': 'Text to Image',
    'image-to-image': 'Image to Image',
    'inpaint-image': 'Inpaint',
    'outpaint-image': 'Outpaint',
    'image-to-video': 'Video',
    'text-to-video': 'Video',
    'upscale-image': 'Upscale Image',
    'upscale-video': 'Upscale Video',
}


class Tool(Base):
    """Table for saved generation tool configurations."""
    __tablename__ = "tools"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    # Classification
    task_type = Column(String, nullable=False, index=True)  # text-to-image, image-to-image, etc.

    # Toolsv3: Full tool ID linking to provider system (e.g., "builtin:ComfyUI:qwen-image:text-to-image")
    full_tool_id = Column(String, nullable=True, index=True)

    # Configuration (JSON)
    generator = Column(String, nullable=False)  # e.g., "comfyui"
    model = Column(String, nullable=False)  # e.g., "Qwen Image"
    # Unified state blob containing all tool settings (prompt, params, loras, etc.)
    state = Column(String, nullable=True)  # JSON blob of entire tool state
    # Legacy columns - kept for migration, will be removed later
    parameters = Column(String, nullable=True)  # JSON: {width, height, cfg, steps, ...}
    loras = Column(String, nullable=True)  # JSON array
    output_folder = Column(String, nullable=True)  # Legacy inert setting

    # Sidebar state
    pinned = Column(Boolean, default=False, index=True)
    pin_order = Column(Integer, nullable=True)  # Order among pinned tools

    # Metadata
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True, index=True)
    usage_count = Column(Integer, default=0)
    deleted_at = Column(DateTime, nullable=True, index=True)  # Soft delete timestamp

    # Source tracking (for drafts created from media)
    source_media_id = Column(Integer, ForeignKey("media_items.id", ondelete="SET NULL"), nullable=True)
    is_draft = Column(Boolean, default=False)  # True for unsaved "more like this" tools

    __table_args__ = (
        Index('idx_tools_pinned', pinned),
    )

    @property
    def category(self) -> str:
        """Get the category name for this tool's task type."""
        return TASK_TYPE_TO_CATEGORY.get(self.task_type, 'Other')

    def to_dict(self):
        """Convert to dictionary for API responses."""
        import json

        # If state exists, use it; otherwise build from legacy columns
        if self.state:
            state = json.loads(self.state)
        else:
            # Migration path: build state from legacy parameters and loras
            state = json.loads(self.parameters) if self.parameters else {}
            loras = json.loads(self.loras) if self.loras else []
            # Ensure loras have enabled flag
            state['loras'] = [
                {'lora': l.get('lora', l), 'weight': l.get('weight', 1.0), 'enabled': l.get('enabled', True)}
                if isinstance(l, dict) else {'lora': l, 'weight': 1.0, 'enabled': True}
                for l in loras
            ]

        return {
            "id": self.id,
            "name": self.name,
            "task_type": self.task_type,
            "category": self.category,
            "full_tool_id": self.full_tool_id,
            "generator": self.generator,
            "model": self.model,
            "state": state,
            # Legacy fields for backward compatibility (deprecated)
            "parameters": state,  # Alias to state for old frontend code
            "loras": state.get('loras', []),  # Extract loras for old frontend code
            "output_folder": self.output_folder,
            "pinned": self.pinned,
            "pin_order": self.pin_order,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "usage_count": self.usage_count,
            "source_media_id": self.source_media_id,
            "is_draft": self.is_draft,
        }


class Preset(Base):
    """
    Saved parameter configurations for tools (Toolsv3).

    Hierarchy: Task -> Tool -> Preset
    - Task: capability enum (text-to-image, etc.)
    - Tool: specific instance from provider (full_tool_id)
    - Preset: user-saved parameter set for a tool
    """
    __tablename__ = "presets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    # Link to provider tool (e.g., "builtin:ComfyUI:qwen-image:text-to-image")
    tool_id = Column(String, nullable=False, index=True)

    # Saved state (parameters, loras, prompt template, etc.)
    state = Column(String, nullable=True)  # JSON blob

    # Sidebar state
    pinned = Column(Boolean, default=False, index=True)
    pin_order = Column(Integer, nullable=True)

    # Metadata
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True, index=True)
    usage_count = Column(Integer, default=0)
    deleted_at = Column(DateTime, nullable=True, index=True)  # Soft delete

    __table_args__ = (
        Index('idx_presets_tool', tool_id),
        Index('idx_presets_pinned', pinned),
        {'sqlite_autoincrement': True},  # Prevent ID reuse after deletion
    )

    def to_dict(self):
        """Convert to dictionary for API responses."""
        import json

        state = json.loads(self.state) if self.state else {}

        return {
            "id": self.id,
            "name": self.name,
            "tool_id": self.tool_id,
            "state": state,
            "pinned": self.pinned,
            "pin_order": self.pin_order,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "usage_count": self.usage_count,
        }


class PinnedTool(Base):
    """
    Tracks which provider tools are pinned to the sidebar.
    Stores tool metadata so it's available even when providers aren't ready.
    """
    __tablename__ = "pinned_tools"

    full_tool_id = Column(String, primary_key=True)  # e.g., "builtin:comfyui:text-to-image:z-image-turbo"
    pin_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Cached tool metadata (populated at pin time, used when providers aren't ready)
    name = Column(String, nullable=True)
    task_type = Column(String, nullable=True)  # Primary task type (backward compat)
    task_types = Column(String, nullable=True)  # JSON array of all task types
    provider_id = Column(String, nullable=True)
    provider_name = Column(String, nullable=True)  # Friendly provider name, survives provider removal

    def to_dict(self):
        import json
        task_types_list = json.loads(self.task_types) if self.task_types else []
        return {
            "full_tool_id": self.full_tool_id,
            "pin_order": self.pin_order,
            "created_at": self.created_at.isoformat(),
            "name": self.name,
            "task_type": self.task_type,
            "task_types": task_types_list,
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
        }


class ToolState(Base):
    """
    Stores working state (parameters, loras, prompt, etc.) per tool.

    This is the "current session" state that survives page refresh.
    Separate from Presets which are explicitly saved configurations.
    """
    __tablename__ = "tool_state"

    full_tool_id = Column(String, primary_key=True)  # e.g., "builtin:comfyui:text-to-image:z-image-turbo"
    state = Column(String, nullable=True)  # JSON blob with parameters, loras, prompt, etc.
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        import json
        return {
            "full_tool_id": self.full_tool_id,
            "state": json.loads(self.state) if self.state else {},
            "updated_at": self.updated_at.isoformat(),
        }


class CachedProviderTool(Base):
    """
    Caches tool metadata from providers for offline display.

    Tools are cached when providers register, enabling display even when
    providers are disconnected. When a provider re-registers, only tools
    from the most recent registration are kept (old tools are deleted).

    When a provider is removed from config, its tools are soft-deleted.
    """
    __tablename__ = "cached_provider_tools"

    id = Column(Integer, primary_key=True, index=True)

    # Tool identity
    full_tool_id = Column(String, nullable=False, unique=True, index=True)  # provider_id:tool_id
    provider_id = Column(String, nullable=False, index=True)
    provider_name = Column(String, nullable=True)  # Human-readable provider name (e.g., "ComfyUI")
    tool_id = Column(String, nullable=False)

    # Display metadata
    name = Column(String, nullable=False)
    task_type = Column(String, nullable=True, index=True)  # Primary task type (backward compat)
    task_types = Column(String, nullable=True)  # JSON array of all task types: '["text-to-image", "image-to-image"]'

    # Optional model identity (STP: model_vendor / model). Used by the UI to
    # render vendor brand marks even when the provider is disconnected.
    model_vendor = Column(String, nullable=True)
    model = Column(String, nullable=True)

    # Full schemas (JSON) for offline display
    parameter_schema = Column(String, nullable=True)  # JSON (single schema for all params)
    output_schema = Column(String, nullable=True)     # JSON
    tool_metadata = Column(String, nullable=True)     # JSON (can't use 'metadata' - reserved by SQLAlchemy)

    # Registration tracking
    last_registered_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Soft delete (when provider is removed from config)
    deleted_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index('idx_cached_tools_provider', provider_id),
        {'sqlite_autoincrement': True},
    )

    def to_dict(self):
        """Convert to dictionary for API responses."""
        import json
        task_types_list = json.loads(self.task_types) if self.task_types else []
        return {
            "full_tool_id": self.full_tool_id,
            "provider_id": self.provider_id,
            "tool_id": self.tool_id,
            "name": self.name,
            "task_type": self.task_type,
            "task_types": task_types_list,
            "model_vendor": self.model_vendor,
            "model": self.model,
            "parameter_schema": json.loads(self.parameter_schema) if self.parameter_schema else {},
            "output_schema": json.loads(self.output_schema) if self.output_schema else {},
            "metadata": json.loads(self.tool_metadata) if self.tool_metadata else {},
            "last_registered_at": self.last_registered_at.isoformat() if self.last_registered_at else None,
        }




class LLMTrace(Base):
    """Stores LLM conversation traces for sub-agents (planner, prompt_craft, etc.)."""
    __tablename__ = "llm_traces"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False, index=True)
    plan_id = Column(String, nullable=True, index=True)  # Plan ID (e.g., "plan_abc123") to group traces
    trace_type = Column(String, nullable=False, index=True)  # "planner", "prompt_craft", "resolve_reference"
    node_id = Column(String, nullable=True)  # Plan node ID if applicable
    tool_call_id = Column(String, nullable=True)  # Tool call ID if applicable
    messages = Column(Text, nullable=False)  # JSON: Full messages array sent to LLM
    response = Column(Text, nullable=True)  # Raw LLM response before parsing
    model = Column(String, nullable=True)  # Model used
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index('idx_llm_traces_plan_id', plan_id),
        Index('idx_llm_traces_chat_created', chat_id, created_at.desc()),
    )

    def to_dict(self):
        """Convert to dictionary for API responses."""
        import json
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "trace_type": self.trace_type,
            "node_id": self.node_id,
            "tool_call_id": self.tool_call_id,
            "messages": json.loads(self.messages) if self.messages else [],
            "response": self.response,
            "model": self.model,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PostProcessingChainRun(Base):
    """One execution of a post-processing chain after a base generation.

    Tracks per-step progress so the UI can render step dots, and persists the
    pause-on-failure state (last good media + failed step) for Retry.
    """
    __tablename__ = "postprocessing_chain_runs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, nullable=False, index=True)  # base generation job
    base_media_id = Column(Integer, nullable=False)  # the generation the chain starts from
    project_id = Column(Integer, nullable=True)

    chain = Column(Text, nullable=False)  # JSON: the enabled steps being run
    step_index = Column(Integer, nullable=False, default=0)  # current (or failed) step
    step_count = Column(Integer, nullable=False)
    step_results = Column(Text, nullable=True)  # JSON: per-step {status, media_id, duration_ms, error}

    status = Column(String, nullable=False, default='running', index=True)  # running, paused, completed, failed
    last_good_media_id = Column(Integer, nullable=True)  # input to the current step; kept on failure
    final_media_id = Column(Integer, nullable=True)
    error = Column(String, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)  # soft delete

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "job_id": self.job_id,
            "base_media_id": self.base_media_id,
            "project_id": self.project_id,
            "chain": json.loads(self.chain) if self.chain else [],
            "step_index": self.step_index,
            "step_count": self.step_count,
            "step_results": json.loads(self.step_results) if self.step_results else [],
            "status": self.status,
            "last_good_media_id": self.last_good_media_id,
            "final_media_id": self.final_media_id,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Database:
    def __init__(self, db_path: str = "stimma.db"):
        self.db_path = db_path
        self._db_guid: Optional[str] = None  # Cached GUID
        self.async_engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=False,
            connect_args={
                "timeout": 30,  # Wait up to 30 seconds for locks
                "check_same_thread": False,
            },
        )
        # secure_delete is a per-connection PRAGMA in default sqlite builds;
        # apply it on every connection so DELETEs zero out freed pages instead
        # of leaving prompt/path/caption bytes recoverable in unallocated space.
        @event.listens_for(self.async_engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA secure_delete = ON")
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()
        self.async_session_maker = async_sessionmaker(
            self.async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init_db(self):
        """Initialize database tables and generate GUID if needed."""
        from core.logging import get_logger
        import uuid
        log = get_logger(__name__)
        log.info(f"DB init_db: starting for {self.db_path}")
        async with self.async_engine.begin() as conn:
            log.info(f"DB init_db: connection acquired for {self.db_path}")
            # Enable WAL mode for better concurrency
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            log.info(f"DB init_db: WAL mode set for {self.db_path}")
            await conn.execute(text("PRAGMA busy_timeout=30000"))  # 30 second timeout
            log.info(f"DB init_db: busy_timeout set for {self.db_path}")

            # Generate and store db_guid if not exists
            result = await conn.execute(
                text("SELECT value FROM _meta WHERE key = 'db_guid'")
            )
            row = result.fetchone()
            if row:
                self._db_guid = row[0]
                log.info(f"DB init_db: existing db_guid={self._db_guid} for {self.db_path}")
            else:
                self._db_guid = str(uuid.uuid4())[:8]  # Short 8-char GUID
                await conn.execute(
                    text("INSERT INTO _meta (key, value) VALUES ('db_guid', :guid)"),
                    {"guid": self._db_guid}
                )
                log.info(f"DB init_db: generated db_guid={self._db_guid} for {self.db_path}")

    @property
    def db_guid(self) -> str:
        """Get the unique database identifier."""
        if self._db_guid is None:
            raise RuntimeError("Database not initialized - call init_db() first")
        return self._db_guid

    async def get_session(self) -> AsyncSession:
        """Get an async database session."""
        async with self.async_session_maker() as session:
            yield session
